import { defineConfig } from 'vitest/config'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      '@nexti/ds': fileURLToPath(new URL('../../packages/ds/src', import.meta.url)),
    },
    dedupe: ['react', 'react-dom'],
  },
  test: { include: ['src/**/*.test.ts', '../../packages/ds/src/**/*.test.ts'] },
})
