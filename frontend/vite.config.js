// 跨端构建配置（对齐伯乐 Bole 的工程化做法）
//
// ⚠️ 核心原则：环境变量只在【本文件 / Node 侧】读取，再通过 Vite `define` 以【字面量】
//    注入应用代码（__APP_ENV__）。应用代码里因此【不存在任何 import.meta / process】，
//    从根上消除 uni-app 小程序平台把 import.meta 转译成 require('url') 导致的
//    「module 'url.js' is not defined」启动崩溃。
//    参考：github.com/javaeer/bole 的 app/vite.config.ts（define: { __VITE_ENV__: ... }）
import { defineConfig, loadEnv } from 'vite'
import uniRaw from '@dcloudio/vite-plugin-uni'
import path from 'node:path'

// 兼容不同模块解析下的默认导出形态
const uni = typeof uniRaw === 'function' ? uniRaw : uniRaw.default

const ROOT = process.cwd()

// uni CLI 在 build 时 mode=production、dev 时 mode=development；
// HBuilderX 直接点「运行」时 mode 可能为空，这里按 NODE_ENV 兜底（与伯乐一致）
function resolveMode(mode) {
  if (mode) return mode
  return process.env.NODE_ENV === 'production' ? 'production' : 'development'
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(resolveMode(mode), ROOT)

  return {
    plugins: [uni()],
    resolve: {
      alias: {
        // 单一数据源：shared/ 与 Python 后端共用同一份内容
        // 用 path.resolve 而非 import.meta.url，避免配置文件自身出现 import.meta
        '@shared': path.resolve(ROOT, '../shared'),
        '@': path.resolve(ROOT, 'src'),
      },
    },
    define: {
      // 编译期静态替换为普通对象字面量 —— 小程序端可读，无需任何 Node 垫片
      __APP_ENV__: JSON.stringify(env),
    },
    server: {
      host: '0.0.0.0',
      port: 5173,
      fs: { allow: ['..', '../..'] },
    },
  }
})
