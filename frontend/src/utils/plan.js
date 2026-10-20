// 志愿表草稿的纯函数层：与页面解耦，便于零依赖单测（Node 内直接跑）。
// 页面只负责渲染与交互，数据变换都在这里。

export const PLAN_KEY = "zhiyuan_plan_v1";

export const LEVELS = [
  { key: "冲", title: "冲（够一够）" },
  { key: "稳", title: "稳（大概率）" },
  { key: "保", title: "保（兜底）" },
];

/**
 * 院校推荐接口返回 → 落盘的志愿表结构（推荐页与结论页共用）。
 * 校线字段必须原样带过来，否则志愿表里的「去年最低」永远是空的。
 */
export function buildPlan(rec) {
  if (!rec || !Array.isArray(rec.tiers)) return null;
  return {
    province: rec.province,
    subject: rec.subject,
    user_rank: rec.user_rank,
    major: rec.major || "",
    at: Date.now(),
    tiers: rec.tiers.map((t) => ({
      tier: t.tier,
      level: t.level,
      min_score: t.min_score,
      min_rank: t.min_rank,
      data_source: t.data_source,
      source_year: t.source_year,
      carried: t.carried,
      pool_shared_with: t.pool_shared_with || null,
      schools: (t.schools || []).map((s) => ({
        name: s.name, province: s.province, nature: s.nature,
        min_score: s.min_score || null,
        min_rank: s.min_rank || null,
        line_year: s.line_year || null,
        data_source: s.data_source || "",
      })),
    })),
  };
}

/** 把院校推荐接口返回的 plan 拍平成表格行；「不可及」档直接丢弃。 */
export function flattenPlan(plan) {
  if (!plan || !Array.isArray(plan.tiers)) return [];
  const out = [];
  plan.tiers.forEach((t) => {
    if (!t || t.level === "不可及") return;
    (t.schools || []).forEach((s) => {
      if (!s || !s.name) return;
      out.push({
        key: String(t.tier || "") + "-" + s.name,
        level: t.level,
        tier: t.tier || "",
        name: s.name,
        province: s.province || "",
        major: plan.major || "",
        // 院校级真实投档线（D1 导入后才有，缺省为空 → 页面回退到层次提示）
        line: s.min_score || null,
        line_rank: s.min_rank || null,
        line_year: s.line_year || null,
        data_source: s.data_source || "",
      });
    });
  });
  return out;
}

/** 收集用户手填的「拟报专业」：{行 key: 专业名}，用于落盘后续填。 */
export function collectMajors(rows) {
  const out = {};
  (Array.isArray(rows) ? rows : []).forEach((r) => {
    const v = (r.major || "").trim();
    if (v) out[r.key] = v;
  });
  return out;
}

/** 把上次填写的拟报专业回填到行上（原地修改 rows）。 */
export function applyMajors(rows, majors) {
  if (!majors || typeof majors !== "object") return rows;
  (Array.isArray(rows) ? rows : []).forEach((r) => {
    if (majors[r.key]) r.major = majors[r.key];
  });
  return rows;
}

/** 按 冲/稳/保 分组，保持固定顺序（缺失的档也保留空组，便于页面提示）。 */
export function groupRows(rows) {
  const list = Array.isArray(rows) ? rows : [];
  return LEVELS.map((l) => ({
    level: l.key,
    title: l.title,
    rows: list.filter((r) => r.level === l.key),
  }));
}

/** ISO 时间 → YYYY-MM-DD HH:mm（本地时区）；非法值返回 "-"。 */
export function formatTime(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  const pad = (n) => (n < 10 ? "0" + n : "" + n);
  return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
    " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
}

/** 已填写的拟报专业数量 / 总行数，用于进度提示。 */
export function fillStats(rows) {
  const list = Array.isArray(rows) ? rows : [];
  const filled = list.filter((r) => (r.major || "").trim()).length;
  return { filled, total: list.length };
}

/** 导出的纯文本志愿表（复制/打印共用）。 */
export function buildPlanText(plan, groups, timeLabel) {
  const p = plan || {};
  const lines = [];
  lines.push("志愿表草稿（学习参考，非填报依据）");
  lines.push("省份：" + (p.province || "-") + " | 科类：" + (p.subject || "-") +
    " | 位次：" + (p.user_rank || "-"));
  lines.push("生成时间：" + (timeLabel || "-"));
  lines.push("");
  (groups || []).forEach((g) => {
    lines.push("【" + g.title + "】");
    if (!g.rows.length) lines.push("（暂无）");
    g.rows.forEach((r, i) => {
      const yearTag = r.line_year ? "（" + r.line_year + "）" : "";
      const lineInfo = r.line
        ? "  去年最低 " + r.line + " 分" + yearTag + (r.line_rank ? " / 位次 " + r.line_rank : "")
        : "";
      lines.push((i + 1) + ". " + r.name + "（" + r.tier + "）" + lineInfo +
        "  拟报专业：" + (r.major || "（待填）"));
    });
    lines.push("");
  });
  lines.push("说明：院校池来自教育部全国高校名单；标注「去年最低」的行来自已导入的院校投档线，" +
    "其余为层次估算。请以考试院/院校招生网为准。");
  return lines.join("\n");
}
