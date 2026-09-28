import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Same origin for the web and the API (BFF): the session cookie and the Origin check work without CORS.
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8100',
      '/auth': 'http://127.0.0.1:8100',
    },
  },
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
})
