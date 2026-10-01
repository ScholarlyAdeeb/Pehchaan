// Manual check of the gateway <-> engine link (needs a running engine):
//   npx tsx server/tls.check.ts https://127.0.0.1:8000
// Confirms the gateway connects with its certificate and that the engine
// turns away callers that have none, use the wrong authority, or speak HTTP.
import assert from 'node:assert/strict';
import http from 'node:http';
import https from 'node:https';
import dotenv from 'dotenv';

dotenv.config({ quiet: true } as any); // ENGINE_API_KEY: the key is still required on top of the certificate

process.env.PYTHON_API_URL = process.argv[2] || 'https://127.0.0.1:8000';
const { describeEngineLink, engineRequest, engineTls } = await import('./engine-transport.ts');
const url = new URL(process.env.PYTHON_API_URL);
const tls = engineTls();
assert.ok(tls.ca && tls.cert && tls.key, 'no certificates found: run `python -m scripts.make_tls_certs` in backend/');

const attempt = (mod: typeof https | typeof http, options: https.RequestOptions) =>
  new Promise<string>((resolve) => {
    const req = mod.request({ host: url.hostname, port: url.port, path: '/api/health', timeout: 8000, ...options }, (res) => {
      res.resume();
      res.on('end', () => resolve(`HTTP ${res.statusCode}`));
    });
    req.on('error', (err: any) => resolve(`refused (${err.code || err.message})`));
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.end();
  });

const keyHeader = process.env.ENGINE_API_KEY ? { 'x-engine-key': process.env.ENGINE_API_KEY } : {};
const health = await engineRequest('/api/health', { headers: keyHeader });
const noKey = await engineRequest('/api/health');
if (process.env.ENGINE_API_KEY) assert.equal(noKey.status, 401, 'a valid certificate alone must not be enough');
assert.equal(health.status, 200, 'gateway with its certificate must reach the engine');
if (process.env.ENGINE_API_KEY) console.log('ok - valid certificate without the API key: HTTP 401');
console.log(`ok - gateway reaches the engine over ${describeEngineLink()}: ${JSON.stringify(health.json().engines)}`);

const noClientCert = await attempt(https, { ca: tls.ca });
assert.ok(noClientCert.startsWith('refused'), `a caller without a client certificate got through: ${noClientCert}`);
console.log(`ok - caller without a client certificate: ${noClientCert}`);

const systemCas = await attempt(https, { cert: tls.cert, key: tls.key });
assert.ok(systemCas.startsWith('refused'), `engine certificate was accepted without our CA: ${systemCas}`);
console.log(`ok - caller that does not trust our CA rejects the engine: ${systemCas}`);

const plain = await attempt(http, {});
assert.ok(plain.startsWith('refused'), `plain HTTP was answered: ${plain}`);
console.log(`ok - plain HTTP: ${plain}`);

console.log('\nmutual TLS link verified');
process.exit(0);
