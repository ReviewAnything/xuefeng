// 前端环境配置：开发 / 生产 统一出口，避免把服务器地址、端口、超时散落各处。
//
// ⚠️ 关键约束（2026-10-23 修复）：微信小程序（mp-weixin）运行环境没有 Node 的 `url` 模块。
// uni-app 在小程序平台会把源码里【任何】`import.meta` 用法转译成对 `url` 的 require，
// 导致 app.js 启动即崩溃（module 'url.js' is not defined，并连带「页面未注册」二级报错）。
// 因此 `import.meta.env` 只能出现在 // #ifdef H5 内；小程序 / App 路径一律走
// process.env.NODE_ENV + 端侧覆盖，绝不在 mp 可达代码里出现 import.meta。
//
// 取值优先级（从高到低）：
//   H5        ：运行时覆盖 window.__XUEFENG_API__ > .env.* 的 VITE_API_BASE > 内置兜底
//   小程序/App：端侧覆盖 uni.getStorageSync('xf_api_base') > 内置兜底

// 模式判定：全部平台用 process.env.NODE_ENV（vite 构建期替换为字面量；Node 测试下默认 development）
const IS_PROD = (typeof process !== "undefined" && process.env && process.env.NODE_ENV === "production");
export const IS_DEV = !IS_PROD;
export const MODE = IS_PROD ? "production" : "development";

// 对外品牌名（产品名），与 .env 的 VITE_APP_NAME 保持一致
export const APP_NAME = "懂分帝";

// 后端 API 基地址（含端口）
let API_BASE;

// #ifdef H5
// H5 平台原生支持 import.meta，且其构建不会注入 url 垫片。
// 用 typeof 短路保护，避免非 vite 环境访问 import.meta.env.X 报错。
API_BASE = (
  (typeof import.meta !== "undefined" && import.meta.env && import.meta.env.VITE_API_BASE)
    ? String(import.meta.env.VITE_API_BASE).trim()
    : (IS_DEV ? "http://localhost:8000" : "https://api.dongfendi.com")
);
// #endif

// #ifndef H5
// 小程序 / App：禁用 import.meta（会触发 require('url') 崩溃），用常量 + 端侧覆盖。
API_BASE = IS_DEV ? "http://localhost:8000" : "https://api.dongfendi.com";
try {
  const ov = (typeof uni !== "undefined" && uni.getStorageSync) ? uni.getStorageSync("xf_api_base") : "";
  if (ov && String(ov).trim()) API_BASE = String(ov).trim();
} catch (e) { /* 端侧覆盖失败时维持兜底常量 */ }
// #endif

export { API_BASE };
export const API_TIMEOUT = IS_DEV ? 15000 : 20000;
