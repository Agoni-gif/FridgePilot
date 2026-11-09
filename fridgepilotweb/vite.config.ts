import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 7093,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8903',
        changeOrigin: true,
        // Keep SSE thinking events unbuffered during long chat runs.
        timeout: 0,
        proxyTimeout: 0,
      },
    },
  },
})
