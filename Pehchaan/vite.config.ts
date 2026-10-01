import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig} from 'vite';

export default defineConfig(() => {
  return {
    plugins: [
      react(),
      tailwindcss(),
    ],
    resolve: {
      alias: {
        '@': path.resolve(process.cwd(), '.'),
      },
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (id.includes('node_modules/recharts') || id.includes('node_modules/d3')) {
              return 'vendor-charts';
            }
          },
        },
      },
    },
    server: {
      // HMR can be switched off with the DISABLE_HMR env var.
      hmr: process.env.DISABLE_HMR !== 'true',
      // File watching is switched off together with HMR.
      watch: process.env.DISABLE_HMR === 'true' ? null : {},
    },
  };
});
