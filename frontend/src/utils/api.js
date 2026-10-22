import { resolveDemo } from "./demoData.js";
import { API_BASE as CONFIG_API_BASE } from "../config.js";

// 后端 API 封装：调用 Python FastAPI 后端（P2 数据层）。
//
// 地址来源（优先级从高到低）：
//   1. 运行时覆盖（仅 H5）：window.__XUEFENG_API__ —— 部署后改静态页即可，无需重新构建
//   2. .env.* 注入的 VITE_API_BASE（开发/生产各一套，见 frontend/.env.*，含端口）
//   3. config.js 内置兜底
// 生产/小程序请改 .env.production 的 VITE_API_BASE 为你的 https 域名（并配置小程序合法域名）。
// 解析后端基地址（含端口）。每次调用实时读取，优先级从高到低：
//   1. 运行时覆盖（仅 H5）：window.__XUEFENG_API__ —— 部署后改静态页即可，无需重新构建
//   2. 端侧覆盖（全平台，含小程序联调）：uni.getStorageSync('xf_api_base')
//   3. config.js 已解析好的 API_BASE（来自 .env.* 的 VITE_API_BASE，经 vite define 注入）
// 注意：这里【不能】使用 import.meta.env —— 小程序平台会把 import.meta 转译成 require('url')，
// 导致 app.js 启动崩溃（module 'url.js' is not defined）。
// 实时读取（而非模块加载时固化）是为了让「改静态页 / 改端侧缓存」即时生效。
export function resolveBase() {
  if (typeof window !== "undefined" && window.__XUEFENG_API__) return window.__XUEFENG_API__;
  try {
    const ov = (typeof uni !== "undefined" && uni.getStorageSync) ? uni.getStorageSync("xf_api_base") : "";
    if (ov && String(ov).trim()) return String(ov).trim();
  } catch (e) { /* 端侧不可用时继续走配置值 */ }
  return CONFIG_API_BASE;
}

// 演示模式开关（存端侧）。开启后优先走离线样例数据，无需后端。
const DEMO_KEY = "zhiyuan_demo_on";
export function isDemo() {
  try { return !!uni.getStorageSync(DEMO_KEY); } catch (e) { return false; }
}
export function setDemo(on) {
  try { uni.setStorageSync(DEMO_KEY, on ? 1 : 0); } catch (e) { /* ignore */ }
}

// 用户友好的「服务未连接」提示，替换原先泄漏的 uvicorn 开发报错。
const OFFLINE_MSG = "数据服务未连接，可在「我的」开启演示模式先体验完整流程";

// 低层网络请求：成功解析、HTTP 错误抛 detail、网络不可达抛 OFFLINE_MSG。
function rawRequest(method, path, data) {
  return new Promise((resolve, reject) => {
    uni.request({
      url: resolveBase() + path,
      method,
      data,
      header: { "Content-Type": "application/json" },
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) resolve(res.data);
        else reject(new Error((res.data && res.data.detail) || "服务返回错误（" + res.statusCode + "）"));
      },
      fail: () => reject(new Error(OFFLINE_MSG)),
    });
  });
}

// 统一入口：演示模式优先；否则走真实后端；任何失败都返回友好报错。
async function request(method, path, data) {
  if (isDemo()) {
    const d = resolveDemo(method, path, data);
    if (d !== undefined) return d;
    throw new Error("演示模式暂未覆盖该功能，请连接后端后使用");
  }
  return rawRequest(method, path, data);
}

export const api = {
  get base() { return resolveBase(); },
  isDemo,
  setDemo,
  health: () => request("GET", "/api/health"),
  search: (province, subject, user_rank, limit = 20) =>
    request("GET", `/api/admission/search`, { province, subject, user_rank, limit }),
  verify: (payload) => request("POST", "/api/verify", payload),
  // P1→P2 打通：一次核验多个专业（画布推荐方向 / 冲稳保列表）
  verifyBatch: (province, subject, user_rank, major_names) =>
    request("POST", "/api/verify/batch", { province, subject, user_rank, major_names }),
  // C2 等位分换算：跨年换算分数/位次
  equivYears: (province, subject) =>
    request("GET", "/api/equiv/years", { province, subject }),
  equivCurve: (province, subject, year) =>
    request("GET", "/api/equiv/curve", { province, subject, year }),
  equivConvert: (params) => request("GET", "/api/equiv/convert", params),
  // 结论页：位次 → 一句判断 + 三个动作（决策入口，先于推荐池）
  verdict: (province, subject, user_rank) =>
    request("GET", "/api/verdict", { province, subject, user_rank }),
  // A3 院校推荐：按位次给 冲/稳/保 院校池
  recommendSchools: (params) => request("GET", "/api/recommend/schools", params),
  // P4 院校专业组：按选科要求推导专业组
  majorGroupUniversities: (params) => request("GET", "/api/major-groups/universities", params),
  majorGroups: (university, subject) =>
    request("GET", "/api/major-groups", { university, subject }),
  // S10-A 年度罗盘：近五年官方省控线（按年浏览 / 跨省对比）
  controlLineYears: () => request("GET", "/api/admission/control-line-years"),
  controlLines: (year, province) =>
    request("GET", "/api/admission/control-lines", { year, province }),
  // S10-B 志愿个数上限：各省本科批/专科批配额 + 建议 冲/稳/保 分布
  volunteerLimit: (province) =>
    request("GET", "/api/admission/volunteer-limit", { province }),
};
