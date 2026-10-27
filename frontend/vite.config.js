import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        // 指向后端容器的宿主机端口。compose 里映射的是 8001，
        // 但这里历史上写的是 8000 —— 本地起 vite 时代理全挂，
        // 页面报错长得像「后端挂了」，很容易误判成代码问题。
        // 需要指向别的地址时用 VITE_API_TARGET 覆盖：
        //   VITE_API_TARGET=http://127.0.0.1:8001 npx vite --port 5174
        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})