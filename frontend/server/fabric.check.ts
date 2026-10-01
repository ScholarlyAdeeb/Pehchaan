// Check against a running Fabric network (fabric/network.sh up):
//   npx tsx server/fabric.check.ts
// Writes one throwaway batch under the source "selfcheck", so real anchors
// (source "pehchaan") are untouched.
import assert from 'node:assert/strict';
import crypto from 'node:crypto';

process.env.FABRIC_SOURCE = 'selfcheck';
const { anchorBatch, closeFabric, fabricConfig, fabricStatus, getAnchor, listAnchors } = await import('./fabric.ts');

const config = fabricConfig();
assert.ok(config, 'no Fabric network configured: run `bash fabric/network.sh up`');

const id = `t${Date.now()}`;
const root = crypto.randomBytes(32).toString('hex');
const batch = { id, merkle_root: root, leaf_count: 3, first_scan: 'SCN-A', last_scan: 'SCN-C', signature: 'c2lnbmF0dXJl' };

assert.equal(await getAnchor(id), null);
console.log('ok - an unknown batch is reported as not anchored');

const t = Date.now();
const anchor = await anchorBatch(batch);
assert.equal(anchor.merkleRoot, root);
assert.equal(anchor.submittedBy, config.mspId);
assert.match(anchor.txId, /^[0-9a-f]{64}$/);
console.log(`ok - batch anchored and committed in ${Date.now() - t} ms (tx ${anchor.txId.slice(0, 16)}…, by ${anchor.submittedBy}, at ${anchor.anchoredAt})`);

const read = await getAnchor(id);
assert.deepEqual(read, anchor);
console.log('ok - the ledger returns the same anchor');

const again = await anchorBatch(batch);
assert.equal(again.txId, anchor.txId);
console.log('ok - re-submitting the same batch returns the original anchor (no second write)');

await assert.rejects(
  anchorBatch({ ...batch, merkle_root: crypto.randomBytes(32).toString('hex') }),
  /already on the ledger with a different root/,
);
console.log('ok - the same batch id with a different root is rejected: an anchor cannot be rewritten');

await assert.rejects(anchorBatch({ ...batch, id: `${id}x`, merkle_root: 'not-a-hash' }), /merkle root must be 64 lowercase hex/);
console.log('ok - malformed input is rejected by the chaincode');

assert.ok((await listAnchors()).some((a) => a.batchId === id));
const status = await fabricStatus();
assert.ok(status.reachable);
console.log(`ok - status: ${status.endpoint}, channel ${status.channel}, chaincode ${status.chaincode}, ${status.anchors} anchor(s) under "${status.source}" (${status.origin})`);

closeFabric();
console.log('\nFabric anchoring verified');
process.exit(0);
