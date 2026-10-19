// 后端 API 封装：调用 Python FastAPI 后端（P2 数据层）。
// 本地 H5 调试默认 http://localhost:8000；生产/小程序请改为你的后端域名（需 https + 小程序后台配置域名）。
const API_BASE = "http://localhost:8000";

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
};
