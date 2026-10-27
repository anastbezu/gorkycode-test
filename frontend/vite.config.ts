import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Куда dev-сервер проксирует /api: по умолчанию — локальный бэкенд из docker compose.
// Против стенда: API_TARGET=https://gorky.bond npm run dev
const apiTarget = process.env.API_TARGET ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
    },
  },
});
