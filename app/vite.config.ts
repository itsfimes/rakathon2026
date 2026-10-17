import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'
import { backendProxy } from './backend-proxy.ts'

const proxy = backendProxy(process.env.RAKATHON_BACKEND_PROXY_KEY_FILE, import.meta.dirname, process.env.RAKATHON_BACKEND_PROXY_TARGET, {
  allowedOrigins: process.env.RAKATHON_BACKEND_PROXY_ALLOWED_ORIGINS,
  canonicalOrigin: process.env.RAKATHON_BACKEND_PROXY_CANONICAL_ORIGIN,
})
export default defineConfig({
  plugins: [react()],
  server: { host: '0.0.0.0', port: 5173, strictPort: true,
    fs: { strict: true, allow: [import.meta.dirname], deny: ['**/.env', '**/.env.*', '**/*.{crt,pem,key}', '**/.git/**'] },
    ...(proxy ? { proxy } : {}) },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true, proxy: {} },
  build: { sourcemap: true, manifest: true },
  test: { environment: 'jsdom', setupFiles: ['./tests/setup.ts'], clearMocks: true },
})
