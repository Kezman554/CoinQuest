import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In the container the API serves this bundle itself, so requests are
// same-origin. In development the dev server proxies them to the API instead,
// which keeps every fetch in the app a plain relative path either way.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/health': 'http://127.0.0.1:8600',
      '/api': 'http://127.0.0.1:8600',
    },
  },
})
