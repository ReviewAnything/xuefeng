import { defineConfig } from 'vite'
import uniRaw from '@dcloudio/vite-plugin-uni'
import { fileURLToPath } from 'node:url'

// 兼容不同模块解析下的默认导出形态
const uni = typeof uniRaw === 'function' ? uniRaw : uniRaw.default

// 单一数据源：把 shared/content.json 通过别名 @shared 引入，前后端共用同一份内容
export default defineConfig({
  plugins: [uni()],
  resolve: {
    alias: {
      '@shared': fileURLToPath(new URL('../shared', import.meta.url)),
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    fs: { allow: ['..', '../..'] },
  },
})
