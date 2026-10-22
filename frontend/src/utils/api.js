// 后端 API 封装：调用 Python FastAPI 后端（P2 数据层）。
//
// 后端地址三处来源，优先级从高到低：
//   1. window.__XUEFENG_API__ —— 部署后可在静态页里改（不用重新构建）
//   2. import.meta.env.VITE_API_BASE —— 构建期注入（GitHub Pages / 各环境 CI 用）
//   3. http://localhost:8000 —— 本地开发默认
// 生产/小程序请改为你的后端域名（需 https + 小程序后台配置域名）。
export function resolveBase() {
  if (typeof window !== "undefined" && window.__XUEFENG_API__) return window.__XUEFENG_API__;
  const env = typeof import.meta !== "undefined" && import.meta.env ? import.meta.env.VITE_API_BASE : "";
  return env || "http://localhost:8000";
}

const API_BASE = resolveBase();

function request(method, path, data) {
  return new Promise((resolve, reject) => {
    uni.request({
      url: API_BASE + path,
      method,
      data,
      header: { "Content-Type": "application/json" },
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) resolve(res.data);
        else reject(new Error((res.data && res.data.detail) || "请求失败"));
      },
      fail: (err) => reject(err),
    });
  });
}

export const api = {
  base: API_BASE,
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
