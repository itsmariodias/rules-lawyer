/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Everything under /api is the FastAPI server.  Proxying in dev keeps the
// browser on one origin, so the SSE stream and the page share it and the
// CORS allowance in api.py is only a fallback.
//
// The target is overridable so the end-to-end run can start a server of its
// own on another port, against its own data directory, without disturbing —
// or being disturbed by — a dev session already running on 8000.
const api = process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: api,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  // Tests sit beside the file they cover — `src/api.test.ts` for `src/api.ts`
  // — so a module and its coverage move together.
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    // A test mounting the book's 364 pages takes 0.2s on an idle machine and
    // over 5s, the default, on a loaded one.
    testTimeout: 15_000,
    coverage: { provider: 'v8', include: ['src/**/*.{ts,tsx}'] },
  },
})
