// 志愿表草稿的纯函数层：与页面解耦，便于零依赖单测（Node / tsx 内直接跑）。
// 页面只负责渲染与交互，数据变换都在这里。

export const PLAN_KEY = "zhiyuan_plan_v1";

export const LEVELS = [
  { key: "冲", title: "冲（够一够）" },
  { key: "稳", title: "稳（大概率）" },
  { key: "保", title: "保（兜底）" },
];

interface PlanTier {
  tier: string;
  level: string;
  min_score?: number | null;
  min_rank?: number | null;
  data_source?: string;
  source_year?: number | null;
  carried?: boolean;
  pool_shared_with?: string | null;
  schools?: any[];
  [k: string]: any;
}

interface RecInput {
  province: string;
  subject: string;
  user_rank: number | string;
  major?: string;
  tiers?: PlanTier[];
  [k: string]: any;
}

interface PlanRow {
  key: string;
  level: string;
  tier: string;
  name: string;
  province: string;
  major: string;
  line: number | null;
  line_rank: number | null;
  line_year: number | null;
  batch: string;
  data_source: string;
  [k: string]: any;
}

/**
 * 院校推荐接口返回 → 落盘的志愿表结构（推荐页与结论页共用）。
 * 校线字段必须原样带过来，否则志愿表里的「去年最低」永远是空的。
 */
export function buildPlan(rec: RecInput): any {
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
      schools: (t.schools || []).map((s: any) => ({
        name: s.name, province: s.province, nature: s.nature,
        min_score: s.min_score || null,
        min_rank: s.min_rank || null,
        line_year: s.line_year || null,
        batch: s.batch || "",
        data_source: s.data_source || "",
      })),
    })),
  };
}

/** 把院校推荐接口返回的 plan 拍平成表格行；「不可及」档直接丢弃。 */
export function flattenPlan(plan: any): PlanRow[] {
  if (!plan || !Array.isArray(plan.tiers)) return [];
  const out: PlanRow[] = [];
  plan.tiers.forEach((t: PlanTier) => {
    if (!t || t.level === "不可及") return;
    (t.schools || []).forEach((s: any) => {
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
        batch: s.batch || "",
        data_source: s.data_source || "",
      });
    });
  });
  return out;
}

/** 收集用户手填的「拟报专业」：{行 key: 专业名}，用于落盘后续填。 */
export function collectMajors(rows: any[]): Record<string, string> {
  const out: Record<string, string> = {};
  (Array.isArray(rows) ? rows : []).forEach((r) => {
    const v = (r.major || "").trim();
    if (v) out[r.key] = v;
  });
  return out;
}

/** 把上次填写的拟报专业回填到行上（原地修改 rows）。 */
export function applyMajors(rows: any[], majors: Record<string, string> | null): any[] {
  if (!majors || typeof majors !== "object") return rows;
  (Array.isArray(rows) ? rows : []).forEach((r) => {
    if (majors[r.key]) r.major = majors[r.key];
  });
  return rows;
}

/** 按 冲/稳/保 分组，保持固定顺序（缺失的档也保留空组，便于页面提示）。 */
export function groupRows(rows: any[]): Array<{ level: string; title: string; rows: any[] }> {
  const list = Array.isArray(rows) ? rows : [];
  return LEVELS.map((l) => ({
    level: l.key,
    title: l.title,
    rows: list.filter((r) => r.level === l.key),
  }));
}

/** ISO 时间 → YYYY-MM-DD HH:mm（本地时区）；非法值返回 "-"。 */
export function formatTime(iso: string | number | Date | null): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  const pad = (n: number) => (n < 10 ? "0" + n : "" + n);
  return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
    " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
}

/** 已填写的拟报专业数量 / 总行数，用于进度提示。 */
export function fillStats(rows: any[]): { filled: number; total: number } {
  const list = Array.isArray(rows) ? rows : [];
  const filled = list.filter((r) => (r.major || "").trim()).length;
  return { filled, total: list.length };
}

/**
 * 保底档「失守」(breach) 判定（S4 验收点：志愿表红灯数可见）。
 *
 * 语义：位次数字越小越靠前。落到「保底」档的院校，其最低投档位次为 `line_rank`；
 * 若用户位次 `user_rank` > `line_rank`，说明用户位次比该校最低录取位次还靠后，
 * 这所"保底"实际够不上 → 失守（红灯）。
 *
 * 只有带真实投档位次（`line_rank`）的保底行才有判定意义；缺数据一律视为
 * `unknown`，**绝不**把"没数据"误判成"安全"。
 */
export function breachStatus(userRank: number | string | null, row: any): "breach" | "safe" | "unknown" {
  if (!row || row.level !== "保") return "unknown";
  const lr = Number(row.line_rank);
  const ur = Number(userRank);
  if (!(lr > 0) || !(ur > 0)) return "unknown";
  return ur > lr ? "breach" : "safe";
}

/**
 * 保底档失守统计。
 */
export function breachStats(plan: any, rows: any[]): { breach: number; covered: number; total: number } {
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
 * 直接在原 plan 上改并返回；若原本没有「保」档，则新建一个「专科兜底」保底组。
 */
export function appendSafeSchools(plan: any, schools: any[]): any {
  if (!plan || !Array.isArray(plan.tiers)) return plan;
  const existing = new Set<string>();
  plan.tiers.forEach((t: PlanTier) => (t.schools || []).forEach((s: any) => s && s.name && existing.add(s.name)));
  const add = (Array.isArray(schools) ? schools : []).filter((s) => s && s.name && !existing.has(s.name));
  if (!add.length) return plan;
  let safeTier = plan.tiers.find((t: PlanTier) => t.level === "保");
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
 * 位次口径（S7-E 修正）：``min_rank`` 是该校**最低投档位次**＝录取末位考生的位次，
 * 数字越大门槛越低。因此「用户稳够」的条件是 **用户位次比它更靠前（数字更小）**：
 * ``min_rank > userRank``。此前写成 ``min_rank < userRank``，方向反了——补进来的
 * 全是够不上的学校，安全网看起来被补上了，实际没有（S7-E 的补位前后对比才发现）。
 */
export function selectBackstops(rec: any, userRank: number, maxN = 6): any[] {
  const ur = Number(userRank);
  if (!(ur > 0) || !rec || !Array.isArray(rec.tiers)) return [];
  const out: any[] = [];
  rec.tiers.forEach((t: PlanTier) => (t.schools || []).forEach((s: any) => {
    const mr = Number(s.min_rank);
    if (mr > ur) out.push(s);   // 院校门槛位次比用户更靠后 → 用户稳够
  }));
  out.sort((a, b) => (b.min_rank || 0) - (a.min_rank || 0)); // 门槛越宽越稳，排最前
  return out.slice(0, maxN);
}

/**
 * 补位前后对比（S7-E，纯函数）：一键补位不只是「加了几所」，用户真正想知道的是
 * **失守有没有被填平**——补位前几所够不上、补位后还剩几所、新兜底替谁接住了。
 * 本函数在**副本**上执行 appendSafeSchools，因此不改变传入的 plan（可先预览再决定是否落盘）。
 */
export function diffSafePatch(plan: any, schools: any[]): any {
  const empty = { breach: 0, covered: 0, total: 0 };
  if (!plan || !Array.isArray(plan.tiers)) {
    return { next: plan, added: [], skipped: 0, before: empty, after: empty,
             still_breach: [], text: "暂无志愿表，无法对比" };
  }
  const before = breachStats(plan, flattenPlan(plan));
  const next = appendSafeSchools(JSON.parse(JSON.stringify(plan)), schools);
  const after = breachStats(next, flattenPlan(next));

  const beforeNames = new Set<string>();
  plan.tiers.forEach((t: PlanTier) => (t.schools || []).forEach((s: any) => s && s.name && beforeNames.add(s.name)));
  const candidates = (Array.isArray(schools) ? schools : []).filter((s) => s && s.name);
  const added = candidates.filter((s) => !beforeNames.has(s.name));
  const skipped = candidates.length - added.length;

  const still_breach = flattenPlan(next)
    .filter((r) => breachStatus(next.user_rank, r) === "breach")
    .map((r) => r.name);

  const safe_before = Math.max(0, before.total - before.breach);
  const safe_after = Math.max(0, after.total - after.breach);
  const text = added.length
    ? `补位 ${added.length} 所兜底院校${skipped ? `（${skipped} 所已在表中）` : ""}；` +
      `保底档可稳够 ${safe_before} → ${safe_after} 所，失守 ${before.breach} → ${after.breach} 所`
    : "没有新的兜底院校可补（候选都已在表里）";

  return { next, added, skipped, before, after, still_breach, safe_before, safe_after, text };
}

/**
 * 填报顺序建议（S8-D 初版，S9-B 补跨年/跨批次可比性）。
 *
 * 排序规则（可解释、且刻意不承诺录取）：
 *   1. 先按档位：冲 → 稳 → 保（LEVELS 顺序）；
 *   2. 同档内按**位次余量**从大到小：余量 = 该校最低投档位次 − 用户位次。
 *      `min_rank` 是录取末位位次，数字越大门槛越低，所以余量为正 = 稳够、越大越安全；
 *      冲档余量为负，取「最接近自己位次」的排前面（冲刺性价比更高）；
 *   3. 没有投档位次的行不参与余量排序，原序附在同档末尾，并明确标注「无数据」。
 *
 * 跨年 / 跨批次可比性（S9-B 新增，关键纠正）：
 *   位次余量成立的前提是「同一年、同一批次口径」。以「有投档位次的行里的最新年份」为
 *   参考年，以「占比最高的非空批次」为参考批次；与参考年/参考批次不一致的行仍参与排序
 *   （保留相对关系），但标记 comparable=false，余量标签与导出文本都显式注明「数据年份/批次不同」。
 */
export function fillOrder(plan: any, rows: any[]): any {
  const ur = Number(plan && plan.user_rank) || 0;
  const list = (Array.isArray(rows) ? rows : []).filter((r) => r && r.name);
  const keys = LEVELS.map((l) => l.key);   // LEVELS 是 {key,title} 数组
  const rankOf = (level: string) => {
    const i = keys.indexOf(level);
    return i < 0 ? keys.length : i;   // 未知档位（如「不可及」）排在最后
  };

  // ---- S9-B：确定参考年与参考批次 ----
  const known = list.filter((r) => {
    const lr = Number(r.line_rank);
    return ur > 0 && lr > 0;
  });
  const years = known.map((r) => Number(r.line_year)).filter((y) => y > 0);
  const reference_year = years.length ? Math.max(...years) : null;
  const batchCounter: Record<string, number> = {};
  known.forEach((r) => {
    const b = (r.batch || "").trim();
    if (b) batchCounter[b] = (batchCounter[b] || 0) + 1;
  });
  let reference_batch = "";
  let best = 0;
  for (const [b, n] of Object.entries(batchCounter)) {
    if (n > best) { best = n; reference_batch = b; }
  }

  const decorated = list.map((r, idx) => {
    const lr = Number(r.line_rank);
    const yr = Number(r.line_year) || 0;
    const has = ur > 0 && lr > 0;
    const cross_year = !!(has && reference_year && yr && yr !== reference_year);
    const cross_batch = !!(has && reference_batch &&
      (r.batch || "").trim() && (r.batch || "").trim() !== reference_batch);
    const comparable = has && !cross_year && !cross_batch;
    return {
      row: r, idx,
      level_rank: rankOf(r.level),
      known: has,
      comparable,
      cross_year,
      cross_batch,
      margin: has ? lr - ur : null,
    };
  });
  decorated.sort((a, b) => {
    if (a.level_rank !== b.level_rank) return a.level_rank - b.level_rank;
    if (a.known !== b.known) return a.known ? -1 : 1;          // 有数据排前
    if (a.known && b.known) {
      if (a.comparable !== b.comparable) return a.comparable ? -1 : 1;  // 同口径优先
      if (a.margin !== b.margin) return (b.margin ?? 0) - (a.margin ?? 0);
    }
    return a.idx - b.idx;                                      // 其余保持原表顺序
  });
  let seq = 0;
  const items = decorated.map((d) => {
    seq += 1;
    const r = d.row;
    let margin_label;
    if (!d.known) {
      margin_label = "无投档线数据，不参与余量排序";
    } else {
      const year_tag = d.cross_year
        ? `（数据年份 ${r.line_year}，与参考年 ${reference_year} 不同）`
        : "";
      const batch_tag = d.cross_batch
        ? `（批次「${r.batch}」与参考批次「${reference_batch}」不同）`
        : "";
      const tag = (year_tag + batch_tag) || "";
      const dm = d.margin ?? 0;
      margin_label = (dm >= 0
        ? `位次余量 +${dm}（可稳够）`
        : `位次差 ${dm}（冲刺，门槛比你的位次靠前 ${Math.abs(dm)} 名）`) +
        (tag ? `${tag}，余量仅供参考` : "");
    }
    return {
      seq, name: r.name, tier: r.tier || "", level: r.level || "",
      line_rank: d.known ? Number(r.line_rank) : null,
      line_year: d.known ? Number(r.line_year) || null : null,
      batch: r.batch || "",
      margin: d.margin, margin_label, major: r.major || "",
      has_line_data: d.known,
      comparable: d.comparable,
      cross_year: d.cross_year,
      cross_batch: d.cross_batch,
    };
  });
  const unknown_count = items.filter((it) => !it.has_line_data).length;
  const incomparable_count = items.filter((it) => it.has_line_data && !it.comparable).length;
  const cross_year = items.filter((it) => it.cross_year).length;
  const cross_batch = items.filter((it) => it.cross_batch).length;
  let basis = "先按档位（冲 → 稳 → 保）；同档内按位次余量从大到小" +
    "（余量 = 该校最低投档位次 − 你的位次，越大越安全）；" +
    "无投档线数据的行附在同档末尾，不参与余量排序。";
  if (reference_year) {
    basis += `位次余量只在同一年、同一批次口径下可比；本表参考年为 ${reference_year}` +
      (reference_batch ? `、参考批次为「${reference_batch}」` : "") +
      `，与参考口径不同的行已标注「余量仅供参考」。`;
  }
  return { items, basis, unknown_count, incomparable_count,
           reference_year, reference_batch, cross_year, cross_batch, total: items.length };
}

/** 填报顺序的纯文本清单（可直接照抄，含序号与档位）。 */
export function buildFillOrderText(plan: any, order: any, timeLabel: string, cap: any): string {
  const p = plan || {};
  const o = order || { items: [], basis: "" };
  const lines: string[] = [];
  lines.push("志愿表填报顺序建议（学习参考，不承诺录取）");
  lines.push("省份：" + (p.province || "-") + " | 科类：" + (p.subject || "-") +
    " | 位次：" + (p.user_rank || "-"));
  lines.push("生成时间：" + (timeLabel || "-"));
  if (cap && cap.volLimit) {
    lines.push("本科批志愿上限：" + cap.volLimit.undergrad + " 个（已填 " + cap.filledCount + "）· 以本省考试院为准");
  }
  if (o.reference_year) {
    lines.push("位次余量参考口径：年份 " + o.reference_year +
      (o.reference_batch ? "、批次「" + o.reference_batch + "」" : "") +
      "（与参考口径不同的行，余量仅供参考）");
  }
  lines.push("排序依据：" + (o.basis || "-"));
  lines.push("");
  if (!o.items || !o.items.length) {
    lines.push("（志愿表为空，暂无顺序建议）");
  } else {
    o.items.forEach((it: any) => {
      lines.push(it.seq + ". [" + (it.level || "-") + "] " + it.name +
        (it.tier ? "（" + it.tier + "）" : "") +
        "  " + it.margin_label +
        (it.major ? "  拟报专业：" + it.major : "  拟报专业：（待填）"));
    });
  }
  lines.push("");
  if (o.unknown_count) {
    lines.push("注：其中 " + o.unknown_count + " 所缺往年投档位次，已附在同档末尾，" +
      "顺序不代表可及性判断。");
  }
  if (o.incomparable_count) {
    lines.push("另：其中 " + o.incomparable_count + " 所投档线与参考年份/批次口径不同，" +
      "其位次余量仅供参考，不宜直接用来比较冲刺性价比。");
  }
  lines.push("说明：顺序仅反映往年投档位次的相对关系，不构成录取承诺；" +
    "正式填报请以省考试院与院校招生网公布的当年计划为准。");
  return lines.join("\n");
}

/** 导出的纯文本志愿表（复制/打印共用）。 */
export function buildPlanText(plan: any, groups: any[], timeLabel: string, cap: any): string {
  const p = plan || {};
  const lines: string[] = [];
  lines.push("志愿表草稿（学习参考，非填报依据）");
  lines.push("省份：" + (p.province || "-") + " | 科类：" + (p.subject || "-") +
    " | 位次：" + (p.user_rank || "-"));
  lines.push("生成时间：" + (timeLabel || "-"));
  if (cap && cap.volLimit) {
    lines.push("本科批志愿上限：" + cap.volLimit.undergrad + " 个（" + cap.volLimit.mode + "）· 已填 " + cap.filledCount);
    if (cap.volLimit.mode === "院校专业组" && cap.adjust) {
      lines.push("服从专业调剂：冲 " + (cap.adjust["冲"] ? "是" : "否") +
        " / 稳 " + (cap.adjust["稳"] ? "是" : "否") +
        " / 保 " + (cap.adjust["保"] ? "是" : "否"));
    }
    lines.push("（以本省教育考试院当年规定为准）");
  }
  lines.push("");
  (groups || []).forEach((g) => {
    lines.push("【" + g.title + "】");
    if (!g.rows.length) lines.push("（暂无）");
    g.rows.forEach((r: any, i: number) => {
      const yearTag = r.line_year ? "（" + r.line_year + "）" : "";
      const batchTag = r.batch ? "「" + r.batch + "」" : "";
      const lineInfo = r.line
        ? "  去年最低 " + r.line + " 分" + yearTag + batchTag +
          (r.line_rank ? " / 位次 " + r.line_rank : "")
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
