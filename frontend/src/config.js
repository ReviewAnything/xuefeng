// 前端环境配置：开发 / 生产 统一出口，避免把服务器地址、端口散落各处。
//
// ⚠️ 小程序（mp-weixin）两条铁律（官方：非 H5 平台不支持 Node.js 模块系统）：
//   1. 不能用 import.meta / import.meta.env —— uni-app 会把 import.meta 转成 require('url')，
//      小程序运行时没有该模块，app.js 启动即崩（module 'url.js' is not defined）。
//   2. 不能依赖 process / process.env —— 小程序运行时 process 未定义。
//      即便加 typeof process !== "undefined" 保护，也只会让判断恒为 false（永远走开发态），
//      导致小程序去请求 http://localhost:8000，真机必然失败。
// 因此这里用 uni-app 官方的【平台条件编译】按平台写死常量，只在 H5 分支用 import.meta.env；
// 小程序端另留端侧覆盖键 xf_api_base 供本地联调。
// 条件编译在 .js 中同样生效（官方 Supported files: .vue .js .css pages.json），js 用 // 注释。

// 兜底（App 等其他端）
let API_BASE = "http://localhost:8000";

// 微信小程序：真机 / 体验版只能用 https 且已在微信公众平台配置为合法域名的地址。
// 本地联调可临时覆盖：uni.setStorageSync('xf_api_base', 'http://localhost:8000')
// #ifdef MP-WEIXIN
API_BASE = "https://api.dongfendi.com";
// #endif

// H5：原生支持 import.meta.env，读 .env.* 注入的 VITE_API_BASE。
// （H5 分支刻意放在最后：纯 Node 测试不处理条件编译，所有分支都会执行，
//   让 H5 分支最后赋值可保证 Node 下结果确定为 localhost。）
// #ifdef H5
API_BASE = (
  (typeof import.meta !== "undefined" && import.meta.env && import.meta.env.VITE_API_BASE)
    ? String(import.meta.env.VITE_API_BASE).trim()
    : "http://localhost:8000"
);
// #endif

// 端侧覆盖：所有平台通用（小程序本地联调；H5 另有 window.__XUEFENG_API__，见 api.resolveBase）
try {
  const ov = (typeof uni !== "undefined" && uni.getStorageSync) ? uni.getStorageSync("xf_api_base") : "";
  if (ov && String(ov).trim()) API_BASE = String(ov).trim();
} catch (e) { /* 端侧覆盖失败时维持平台常量 */ }

export { API_BASE };

// 对外品牌名（产品名），与 .env 的 VITE_APP_NAME 保持一致
export const APP_NAME = "懂分帝";
export const API_TIMEOUT = 20000;

// 运行模式由最终地址推导，不再依赖 process / import.meta
export const IS_DEV = API_BASE.indexOf("localhost") >= 0 || API_BASE.indexOf("127.0.0.1") >= 0;
export const IS_PROD = !IS_DEV;
export const MODE = IS_DEV ? "development" : "production";
