/** 开发管线：React 编译后代理本地 Python API；所有研究数值由后端生成。 */
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
});
