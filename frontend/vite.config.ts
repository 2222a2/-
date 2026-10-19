import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 逻辑：/api 开头请求经 vite 代理转发到后端 8000，
// 前端永远用相对路径 /api/...，既避开跨域、又让前后端像同一个站点（呼应“零跳转”）。
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0', // 绑定全部网卡：本机 127.0.0.1、同局域网手机用电脑 IP 都能访问（P3 方案 B）
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
