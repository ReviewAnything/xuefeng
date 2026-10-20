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

/**
 * 保底档「失守」(breach) 判定（S4 验收点：志愿表红灯数可见）。
 *
 * 语义：位次数字越小越靠前。落到「保底」档的院校，其最低投档位次为 `line_rank`；
 * 若用户位次 `user_rank` > `line_rank`，说明用户比该校最低录取位次还靠后，
 * 这所"保底"实际够不上 → 失守（红灯）。
 *
 * 只有带真实投档位次（`line_rank`）的保底行才有判定意义；缺数据一律视为
 * `unknown`，**绝不**把"没数据"误判成"安全"。
 *
 * @param {number|string} userRank 用户位次
 * @param {object} row 拍平后的行（含 level、line_rank）
 * @returns {'breach'|'safe'|'unknown'}
 */
export function breachStatus(userRank, row) {
  if (!row || row.level !== "保") return "unknown";
  const lr = Number(row.line_rank);
  const ur = Number(userRank);
  if (!(lr > 0) || !(ur > 0)) return "unknown";
  return ur > lr ? "breach" : "safe";
}

/**
 * 保底档失守统计。
 * @param {object} plan 志愿表（取 plan.user_rank）
 * @param {Array} rows 拍平后的行
 * @returns {{breach:number, covered:number, total:number}}
 *   breach   —— 已失守（红灯）的保底院校数
 *   covered  —— 有真实投档位次、可判定的保底院校数
 *   total    —— 保底院校总数（含无投档线数据的）
 */
export function breachStats(plan, rows) {
  const safeRows = (Array.isArray(rows) ? rows : []).filter((r) => r && r.level === "保");
  let breach = 0, covered = 0;
  safeRows.forEach((r) => {
    const st = breachStatus(plan && plan.user_rank, r);
    if (st !== "unknown") covered++;
    if (st === "breach") breach++;
  });
  return { breach, covered, total: safeRows.length };
}

/**
 * 保底失守补位（S5-C）：把更低层次、用户位次可稳够的兜底院校并入「保」档，形成闭环。
 *
 * 调用方先用 plan 的省份/科类/位次拉取 recommend 结果，再从中筛出「用户位次优于其最低
 * 投档位次、且当前志愿表里没有」的院校传入本函数。被并入的院校 min_rank 必然 < user_rank，
 * 因此是真正更安全的兜底（不会再次失守）。
 *
 * 直接在原 plan 上改并返回；若原本没有「保」档，则新建一个「专科兜底」保底组。
 *
 * @param {object} plan 现有志愿表（含 tiers）
 * @param {Array} schools 候选兜底院校（来自 recommend，取 {name,province,nature,min_score,min_rank,line_year,data_source}）
 * @returns {object} 并入新院校后的 plan
 */
export function appendSafeSchools(plan, schools) {
  if (!plan || !Array.isArray(plan.tiers)) return plan;
  const existing = new Set();
  plan.tiers.forEach((t) => (t.schools || []).forEach((s) => s && s.name && existing.add(s.name)));
  const add = (Array.isArray(schools) ? schools : []).filter((s) => s && s.name && !existing.has(s.name));
  if (!add.length) return plan;
  let safeTier = plan.tiers.find((t) => t.level === "保");
  if (!safeTier) {
    safeTier = {
      tier: "专科兜底", level: "保", min_score: null, min_rank: null,
      data_source: "school_line", source_year: null, carried: false,
      pool_shared_with: null, schools: [],
    };
    plan.tiers.push(safeTier);
  }
  add.forEach((s) => safeTier.schools.push({
    name: s.name,
    province: s.province || "",
    nature: s.nature || "",
    min_score: s.min_score || null,
    min_rank: s.min_rank || null,
    line_year: s.line_year || null,
    data_source: s.data_source || "",
  }));
  return plan;
}

/**
 * 从 recommend 结果里筛选兜底候选（S5-C，纯函数便于单测，由一键补位调用）。
 *
 * 只挑「用户位次优于其最低投档位次」的院校（``min_rank`` 存在且 < ``userRank``），
 * 因此并入后不会再失守；最易够到的（``min_rank`` 最大）排前面，最多 ``maxN`` 所。
 * 注意：本函数不负责按名字去重（那是 ``appendSafeSchools`` 的职责）。
 *
 * @param {object} rec recommend 接口返回（含 tiers[].schools[]）
 * @param {number} userRank 用户位次
 * @param {number} maxN 上限
 * @returns {Array} 候选院校（保留 min_rank 等字段）
 */
export function selectBackstops(rec, userRank, maxN = 6) {
  const ur = Number(userRank);
  if (!(ur > 0) || !rec || !Array.isArray(rec.tiers)) return [];
  const out = [];
  rec.tiers.forEach((t) => (t.schools || []).forEach((s) => {
    const mr = Number(s.min_rank);
    if (mr > 0 && mr < ur) out.push(s);
  }));
  out.sort((a, b) => (b.min_rank || 0) - (a.min_rank || 0)); // 最易够到的排前
  return out.slice(0, maxN);
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
