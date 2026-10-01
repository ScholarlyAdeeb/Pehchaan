// How the gateway reaches the screening engine.
//
// The engine is never on the same host as a serverless gateway, so the link
// is mutual TLS: the gateway verifies the engine's certificate against the
// deployment's own certificate authority and presents a client certificate
// the engine checks the same way. The API key is still sent on top.
//
// Certificates come from, in order:
//   ENGINE_CA_CERT / ENGINE_CLIENT_CERT / ENGINE_CLIENT_KEY
//       PEM text, base64 of the PEM, or a file path (hosted gateways have no
//       files, so they paste base64: `python -m scripts.make_tls_certs --print-env`)
//   ../backend/certs/{ca,gateway}.pem + gateway.key
//       written by `python -m scripts.make_tls_certs` on a checkpoint machine
//
// Plain HTTP is accepted only for a loopback address.
import fs from 'fs';
import http from 'http';
import https from 'https';
import path from 'path';

const LOCAL_CERTS = path.resolve(process.cwd(), '..', 'backend', 'certs');
const LOOPBACK = new Set(['127.0.0.1', 'localhost', '[::1]', '::1']);

function material(envName: string, localFile: string): string | undefined {
  const raw = process.env[envName]?.trim();
  if (raw) {
    if (raw.includes('-----BEGIN')) return raw.replace(/\\n/g, '\n');
    if (fs.existsSync(raw)) return fs.readFileSync(raw, 'utf8');
    const decoded = Buffer.from(raw, 'base64').toString('utf8');
    if (decoded.includes('-----BEGIN')) return decoded;
    throw new Error(`${envName} is set but is not PEM text, base64 PEM or a readable file`);
  }
  const file = path.join(LOCAL_CERTS, localFile);
  return fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : undefined;
}

export interface EngineTls {
  ca?: string;
  cert?: string;
  key?: string;
}

export function engineTls(): EngineTls {
  return { ca: material('ENGINE_CA_CERT', 'ca.pem'), cert: material('ENGINE_CLIENT_CERT', 'gateway.pem'), key: material('ENGINE_CLIENT_KEY', 'gateway.key') };
}

/** PYTHON_API_URL, or the local engine: https when this machine holds certificates, else http. */
export function engineBaseUrl(): string {
  const configured = process.env.PYTHON_API_URL?.replace(/\/$/, '');
  if (configured) return configured;
  const tls = engineTls();
  return tls.ca && tls.cert && tls.key ? 'https://127.0.0.1:8000' : 'http://127.0.0.1:8000';
}

export function describeEngineLink(): string {
  const url = new URL(engineBaseUrl());
  if (url.protocol === 'http:') return `${url.origin} (plain HTTP, loopback only)`;
  const tls = engineTls();
  return `${url.origin} (TLS${tls.ca ? ', private CA' : ', public CA'}${tls.cert && tls.key ? ', client certificate presented' : ', NO client certificate'})`;
}

let agent: https.Agent | null = null;
let agentKey = '';

function httpsAgent(): https.Agent {
  const tls = engineTls();
  const key = `${tls.ca?.length}|${tls.cert?.length}|${tls.key?.length}`;
  if (!agent || key !== agentKey) {
    agent = new https.Agent({ ca: tls.ca, cert: tls.cert, key: tls.key, minVersion: 'TLSv1.2', keepAlive: true });
    agentKey = key;
  }
  return agent;
}

export interface EngineResponse {
  status: number;
  ok: boolean;
  text: () => string;
  json: () => any;
}

export async function engineRequest(
  pathname: string,
  opts: { method?: string; headers?: Record<string, string>; form?: FormData; timeoutMs?: number } = {},
): Promise<EngineResponse> {
  const url = new URL(engineBaseUrl() + pathname);
  const secure = url.protocol === 'https:';
  if (!secure && !LOOPBACK.has(url.hostname) && process.env.ENGINE_ALLOW_PLAINTEXT !== 'true') {
    throw new Error(`Refusing to send documents to ${url.host} over plain HTTP. Use an https:// PYTHON_API_URL.`);
  }

  const headers: Record<string, string> = { ...(opts.headers || {}) };
  let body: Buffer | undefined;
  if (opts.form) {
    const encoded = new Response(opts.form); // lets the runtime build the multipart body and its boundary
    body = Buffer.from(await encoded.arrayBuffer());
    headers['content-type'] = encoded.headers.get('content-type') as string;
    headers['content-length'] = String(body.length);
  }

  return new Promise<EngineResponse>((resolve, reject) => {
    const req = (secure ? https : http).request(
      url,
      { method: opts.method || (body ? 'POST' : 'GET'), headers, agent: secure ? httpsAgent() : undefined, timeout: opts.timeoutMs ?? 15_000 },
      (res) => {
        const chunks: Buffer[] = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => {
          const text = Buffer.concat(chunks).toString('utf8');
          const status = res.statusCode || 0;
          resolve({ status, ok: status >= 200 && status < 300, text: () => text, json: () => JSON.parse(text) });
        });
      },
    );
    req.on('timeout', () => req.destroy(new Error('timed out')));
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}
