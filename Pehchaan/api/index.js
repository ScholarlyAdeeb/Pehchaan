// Vercel serverless entry for the PEHCHAAN gateway.
//
// `npm run build` bundles server.ts into dist-server/app.cjs; this file only
// hands each request to that Express app. One app is built per function
// instance and reused while the instance stays warm.
import bundle from '../dist-server/app.cjs';

let app;

export default async function handler(req, res) {
  app ??= bundle.createApp();
  (await app)(req, res);
}
