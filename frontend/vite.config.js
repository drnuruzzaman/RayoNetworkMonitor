import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server only: proxies API calls to the backend (port is whatever you set in Settings).
const backend = process.env.HOMENET_BACKEND || 'http://127.0.0.1:8090'

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': backend } },
  build: { outDir: 'dist', chunkSizeWarningLimit: 1200 },
})
