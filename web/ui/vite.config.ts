import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发期把后端接口代理到 Flask(127.0.0.1:8898)，生产构建输出 dist 由 Flask 托管
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8898',
      '/qrcodes': 'http://127.0.0.1:8898',
      '/package': 'http://127.0.0.1:8898',
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1500,
  },
})
