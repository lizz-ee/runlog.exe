import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiPort = process.env.RUNLOG_API_PORT || '8000'
const apiTarget = `http://localhost:${apiPort}`

export default defineConfig({
  base: './',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': apiTarget,
      '/media': apiTarget,
    },
  },
})
