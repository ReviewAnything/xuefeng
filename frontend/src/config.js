// 前端环境配置：开发 / 生产 统一出口，避免把服务器地址、端口、超时散落各处。
//
// 取值优先级（从高到低）：
//   1. 运行时覆盖（仅 H5）：window.__XUEFENG_API__  —— 部署后改静态页即可，无需重新构建
//   2. .env.* 注入的 VITE_* 变量（见 frontend/.env.development / .env.production）
//   3. 本文件内置兜底
//
// uni-app(vue3+vite) 会在 dev 时加载 .env.development、build 时加载 .env.production，
// 并以 import.meta.env.VITE_* 暴露。Node 测试/模板编译环境下 import.meta.env 不存在，
// 这里做降级，保证模块可被静态分析工具安全解析。

const env = (typeof import.meta !== "undefined" && import.meta.env) || {};

export const MODE = env.MODE || (env.PROD ? "production" : "development");
export const IS_DEV = !!env.DEV || MODE === "development";
export const IS_PROD = !!env.PROD || MODE === "production";

// 对外品牌名（产品名），与 .env 的 VITE_APP_NAME 保持一致
export const APP_NAME = env.VITE_APP_NAME || "懂分帝";

// 后端 API 基地址（含端口）。生产环境必须是 https 域名且已在微信公众平台配置合法域名。
const API_BASE_DEFAULT = IS_DEV ? "http://localhost:8000" : "https://api.dongfendi.com";
export const API_BASE = (env.VITE_API_BASE && String(env.VITE_API_BASE).trim()) || API_BASE_DEFAULT;

export const API_TIMEOUT = Number(env.VITE_API_TIMEOUT) || (IS_DEV ? 15000 : 20000);
