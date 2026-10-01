// Hyperledger Fabric anchoring of sealed batches.
//
// Each sealed batch's Merkle root is submitted to the `auditledger` chaincode
// (fabric/chaincode/auditledger). The chaincode accepts a batch id once and
// never lets it change, so the ledger is an independent witness of what each
// root was: rewriting sealed records in the database cannot also rewrite the
// ledger, which is run by its own peers under its own keys. No personal data
// goes on chain.
//
// Configuration, in order:
//   FABRIC_PEER_ENDPOINT  host:port of a gateway peer
//   FABRIC_PEER_HOST_ALIAS  name on the peer's TLS certificate, if it differs
//   FABRIC_MSP_ID, FABRIC_TLS_CERT, FABRIC_CLIENT_CERT, FABRIC_CLIENT_KEY
//       certificates as PEM text, base64 of the PEM, or a file path (a hosted
//       gateway has no files, so it uses base64 values)
//   otherwise, the local network created by fabric/network.sh, if present.
// With neither, anchoring is off and the PostgreSQL chain works as before.
import crypto from 'crypto';
import fs from 'fs';
import path from 'path';
import * as grpc from '@grpc/grpc-js';
import { connect, signers, type Contract, type Gateway } from '@hyperledger/fabric-gateway';

const LOCAL_ORG = path.resolve(process.cwd(), '..', 'fabric', 'network', 'organizations', 'peerOrganizations', 'ssb.pehchaan.local');
const LOCAL_PEER = 'peer0.ssb.pehchaan.local';

export interface FabricConfig {
  endpoint: string;
  hostAlias?: string;
  mspId: string;
  tlsCert: string;
  clientCert: string;
  clientKey: string;
  channel: string;
  chaincode: string;
  source: string;
  origin: 'environment' | 'local network';
}

export interface BatchAnchor {
  source: string;
  batchId: string;
  merkleRoot: string;
  leafCount: number;
  firstScan: string;
  lastScan: string;
  signature: string;
  submittedBy: string;
  txId: string;
  anchoredAt: string;
}

function pem(value: string, name: string): string {
  const raw = value.trim();
  if (raw.includes('-----BEGIN')) return raw.replace(/\\n/g, '\n');
  if (fs.existsSync(raw)) return fs.readFileSync(raw, 'utf8');
  const decoded = Buffer.from(raw, 'base64').toString('utf8');
  if (decoded.includes('-----BEGIN')) return decoded;
  throw new Error(`${name} is not PEM text, base64 PEM or a readable file`);
}

function firstFile(dir: string): string {
  const files = fs.readdirSync(dir);
  if (!files.length) throw new Error(`no file in ${dir}`);
  return fs.readFileSync(path.join(dir, files[0]), 'utf8');
}

export function fabricConfig(): FabricConfig | null {
  if (process.env.FABRIC_ANCHORING === 'off') return null;
  const env = process.env;
  const common = {
    channel: env.FABRIC_CHANNEL || 'pehchaan',
    chaincode: env.FABRIC_CHAINCODE || 'auditledger',
    // which deployment sealed the batch; batch numbers are only unique per database
    source: (env.FABRIC_SOURCE || 'pehchaan').replace(/[^A-Za-z0-9._-]/g, '-').slice(0, 64),
  };
  if (env.FABRIC_PEER_ENDPOINT) {
    const need = ['FABRIC_MSP_ID', 'FABRIC_TLS_CERT', 'FABRIC_CLIENT_CERT', 'FABRIC_CLIENT_KEY'].filter((k) => !env[k]);
    if (need.length) throw new Error(`FABRIC_PEER_ENDPOINT is set but ${need.join(', ')} ${need.length > 1 ? 'are' : 'is'} missing`);
    return {
      ...common, origin: 'environment', endpoint: env.FABRIC_PEER_ENDPOINT, hostAlias: env.FABRIC_PEER_HOST_ALIAS,
      mspId: env.FABRIC_MSP_ID as string,
      tlsCert: pem(env.FABRIC_TLS_CERT as string, 'FABRIC_TLS_CERT'),
      clientCert: pem(env.FABRIC_CLIENT_CERT as string, 'FABRIC_CLIENT_CERT'),
      clientKey: pem(env.FABRIC_CLIENT_KEY as string, 'FABRIC_CLIENT_KEY'),
    };
  }
  const user = path.join(LOCAL_ORG, 'users', 'User1@ssb.pehchaan.local', 'msp');
  if (!fs.existsSync(user)) return null;
  return {
    ...common, origin: 'local network', endpoint: 'localhost:7051', hostAlias: LOCAL_PEER, mspId: 'SSBMSP',
    tlsCert: fs.readFileSync(path.join(LOCAL_ORG, 'peers', LOCAL_PEER, 'tls', 'ca.crt'), 'utf8'),
    clientCert: firstFile(path.join(user, 'signcerts')),
    clientKey: firstFile(path.join(user, 'keystore')),
  };
}

export function fabricEnabled(): boolean {
  try { return fabricConfig() !== null; } catch { return true; } // misconfigured counts as "on" so the error surfaces
}

let cached: { gateway: Gateway; client: grpc.Client; contract: Contract; config: FabricConfig } | null = null;

function session() {
  const config = fabricConfig();
  if (!config) throw new Error('Fabric anchoring is not configured');
  if (cached && cached.config.endpoint === config.endpoint) return cached;
  const client = new grpc.Client(
    config.endpoint,
    grpc.credentials.createSsl(Buffer.from(config.tlsCert)),
    config.hostAlias ? { 'grpc.ssl_target_name_override': config.hostAlias, 'grpc.default_authority': config.hostAlias } : {},
  );
  const gateway = connect({
    client,
    identity: { mspId: config.mspId, credentials: Buffer.from(config.clientCert) },
    signer: signers.newPrivateKeySigner(crypto.createPrivateKey(config.clientKey)),
    evaluateOptions: () => ({ deadline: Date.now() + 8_000 }),
    endorseOptions: () => ({ deadline: Date.now() + 20_000 }),
    submitOptions: () => ({ deadline: Date.now() + 10_000 }),
    commitStatusOptions: () => ({ deadline: Date.now() + 60_000 }),
  });
  cached = { gateway, client, config, contract: gateway.getNetwork(config.channel).getContract(config.chaincode) };
  return cached;
}

export function closeFabric(): void {
  cached?.gateway.close();
  cached?.client.close();
  cached = null;
}

const text = (bytes: Uint8Array) => Buffer.from(bytes).toString('utf8');
const errorText = (err: any): string =>
  [err?.message, ...(err?.details || []).map((d: any) => d?.message)].filter(Boolean).join(' | ');

/** The ledger's record of a batch, or null if it was never anchored. */
export async function getAnchor(batchId: string | number): Promise<BatchAnchor | null> {
  const { contract, config } = session();
  try {
    return JSON.parse(text(await contract.evaluateTransaction('GetBatch', config.source, String(batchId))));
  } catch (err) {
    if (errorText(err).includes('is not anchored')) return null;
    throw err;
  }
}

export async function listAnchors(): Promise<BatchAnchor[]> {
  const { contract, config } = session();
  return JSON.parse(text(await contract.evaluateTransaction('ListBatches', config.source)) || '[]');
}

/**
 * Anchors one batch and waits for it to be committed in a block. If the batch
 * is already on the ledger with the same root (an earlier attempt committed
 * but its result was lost), that anchor is returned; a different root is an
 * error, because the ledger never lets an anchored batch change.
 */
export async function anchorBatch(batch: {
  id: string | number; merkle_root: string; leaf_count: number; first_scan: string; last_scan: string; signature: string;
}): Promise<BatchAnchor> {
  const { contract, config } = session();
  try {
    const result = await contract.submitTransaction(
      'AnchorBatch', config.source, String(batch.id), batch.merkle_root, String(batch.leaf_count),
      batch.first_scan, batch.last_scan, batch.signature,
    );
    return JSON.parse(text(result));
  } catch (err) {
    if (!errorText(err).includes('already anchored')) throw new Error(`Fabric anchoring failed: ${errorText(err)}`);
    const existing = await getAnchor(batch.id);
    if (existing && existing.merkleRoot === batch.merkle_root) return existing;
    throw new Error(`Batch ${batch.id} is already on the ledger with a different root (${existing?.merkleRoot?.slice(0, 12)}…): `
      + 'the database copy of this batch has been altered.');
  }
}

export async function fabricStatus(): Promise<{ enabled: boolean; reachable?: boolean; endpoint?: string; channel?: string; chaincode?: string; source?: string; origin?: string; anchors?: number; error?: string }> {
  let config: FabricConfig | null;
  try {
    config = fabricConfig();
  } catch (err) {
    return { enabled: true, reachable: false, error: (err as Error).message };
  }
  if (!config) return { enabled: false };
  const base = { enabled: true, endpoint: config.endpoint, channel: config.channel, chaincode: config.chaincode, source: config.source, origin: config.origin };
  try {
    return { ...base, reachable: true, anchors: (await listAnchors()).length };
  } catch (err) {
    closeFabric();
    return { ...base, reachable: false, error: errorText(err) };
  }
}
