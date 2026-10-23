// 前端环境配置：开发 / 生产 统一出口，避免把服务器地址、端口散落各处。
//
// ⚠️ 跨端铁律（官方：非 H5 平台不支持 Node.js 模块系统）：
//   1. 不得使用 import.meta / import.meta.env —— 小程序平台会将其转译为 require('url')，
//      而小程序运行时没有该模块，app.js 启动即崩（module 'url.js' is not defined）。
//   2. 不得依赖 process / process.env —— 小程序运行时 process 未定义；即便加
//      typeof process !== "undefined" 保护，也只会让判断恒为 false（永远走开发态）。
//
// ✅ 正确做法（对齐伯乐 Bole）：环境变量在 vite.config.ts（Node 侧）用 loadEnv 读取，
//    再通过 define 以【字面量】注入，此处只读 __APP_ENV__ 这个普通对象。
//    构建后它是形如 {"VITE_API_BASE":"https://..."} 的字面量，H5 / 小程序 / App 通用。
//
// 纯 Node / tsx 环境（如 tests/*.test.mjs 经 tsx 运行）下 __APP_ENV__ 未定义，
// typeof 对未声明变量是安全的，会走内置兜底值。

const ENV: Record<string, string> = (typeof __APP_ENV__ === "object" && __APP_ENV__) ? __APP_ENV__ : {};

function pick(key: string, fallback: string): string {
  const v = ENV && ENV[key];
  return v && String(v).trim() ? String(v).trim() : fallback;
}

// 后端基地址（含端口）。改地址只改 frontend/.env.development / .env.production
export const API_BASE = pick("VITE_API_BASE", "http://localhost:8000");

// 对外品牌名（产品名），与 .env 的 VITE_APP_NAME 保持一致
export const APP_NAME = pick("VITE_APP_NAME", "懂分帝");
export const API_TIMEOUT = 20000;

// 运行模式由最终地址推导，不再依赖 process / import.meta
export const IS_DEV = API_BASE.indexOf("localhost") >= 0 || API_BASE.indexOf("127.0.0.1") >= 0;
export const IS_PROD = !IS_DEV;
export const MODE = IS_DEV ? "development" : "production";
