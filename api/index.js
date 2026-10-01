// Vercel serverless entry for the PEHCHAAN gateway.
//
// The build (see vercel.json) bundles frontend/server.ts into
// frontend/dist-server/app.cjs; this file only hands each request to that
// Express app. One app is built per function instance and reused while the
// instance stays warm.
const bundle = require('../frontend/dist-server/app.cjs');

let app;

module.exports = async function handler(req, res) {
  app ??= bundle.createApp();
  (await app)(req, res);
};
