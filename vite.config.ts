import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  server: { host: "0.0.0.0", proxy: { "/api": { target: process.env.API_PROXY_TARGET || "http://127.0.0.1:8000", changeOrigin: true } } },
  plugins: [react(), tailwindcss()],
})
