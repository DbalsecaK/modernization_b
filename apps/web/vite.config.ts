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
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      // The NexTI design system (spec 7.4), shared with the generated prototypes (ADR-0013).
      '@nexti/ds': fileURLToPath(new URL('../../packages/ds/src', import.meta.url)),
    },
    // Code outside apps/web (the design system) uses the web's React.
    dedupe: ['react', 'react-dom'],
  },
})
