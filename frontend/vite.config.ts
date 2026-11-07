import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The backend (FastAPI) runs on :8000. In dev, Vite forwards these paths to
// it, so the browser sees one origin: no CORS setup needed locally and the
// frontend can call relative URLs like fetch('/api/shops').
const BACKEND = 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': BACKEND,
      '/mcp': BACKEND,
      '/paypal': BACKEND, // PayPal return/cancel redirects
      '/uploads': BACKEND, // product photos
    },
  },
})
