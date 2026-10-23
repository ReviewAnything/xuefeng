// 演示模式离线数据：无后端时也能跑通「我能上哪 → 院校池 → 志愿表 → 历年省控线」全流程。
// 数据为按位次生成的示意值，仅用于体验界面，不代表真实录取信息。

interface DemoSchool {
  name: string;
  province: string;
  city: string;
  category: string;
  nature: string;
  min_score: number;
  min_rank: number;
  line_year: number;
}

function rankTiers(rank: number): Array<{ tier: string; label: string; min_rank: number }> {
  // 示意档位门槛（按百万级考生省份的大致量级，非真实数据）。
  // 位次越小越靠前：rank ≤ min_rank 即「够得着」该档。
  return [
    { tier: "985", label: "985", min_rank: 12000 },
    { tier: "211", label: "211", min_rank: 45000 },
    { tier: "普通一本", label: "普通一本", min_rank: 130000 },
    { tier: "普通二本", label: "普通二本", min_rank: 280000 },
    { tier: "专科", label: "专科", min_rank: 450000 },
  ];
}

function gateState(rank: number, min_rank: number): "open" | "closed" {
  return rank <= min_rank ? "open" : "closed";
}

function demoVerdict(province: string, subject: string, rank: number) {
  const tiers = rankTiers(rank);
  const gates = tiers.map((t) => {
    const state = gateState(rank, t.min_rank);
    const gap = t.min_rank - rank;
    return {
      tier: t.tier,
      label: t.label,
      min_rank: t.min_rank,
      state,
      gap,
    };
  });
  const reachable = tiers.filter((t) => gateState(rank, t.min_rank) === "open").map((t) => t.label);
  const top = reachable[0] || "专科";
  const headline = reachable.length
    ? `按位次，你落在「${top}」区间附近；用下面的区间去筛学校，再看冲稳保。`
    : `你的位次偏后，重点看「专科」与保底院校；同时关注专升本等路径。`;

  const bands = [
    { key: "reach", label: "冲", from: Math.round(rank * 0.5), to: Math.round(rank * 0.85) },
    { key: "match", label: "稳", from: Math.round(rank * 0.85), to: Math.round(rank * 1.2) },
    { key: "safe", label: "保", from: Math.round(rank * 1.2), to: Math.round(rank * 1.8) },
  ];

  const stance = [
    { k: "冲", t: "用排名更靠前的学校试一试，录不上也不亏。" },
    { k: "稳", t: "和你位次最匹配的一档，重点填满。" },
    { k: "保", t: "一定留足保底，避免滑档。" },
  ];

  return {
    province,
    subject,
    user_rank: rank,
    headline,
    stance,
    guard: "演示数据：本结果为示意生成，正式填报请以各省教育考试院官方数据为准。",
    bands,
    facts: [
      `当前为演示模式：未连接后端，以下为按位次生成的示意图。`,
      `在「我的」页可关闭演示模式，或连接后端获取真实录取数据。`,
    ],
    gates,
    basis: "演示模式数据 · 仅供界面体验（非真实录取信息）",
    data_source: "demo",
  };
}

const SAMPLE_SCHOOLS: Record<string, string[]> = {
  985: ["示例大学（985）", "示例理工（985）"],
  211: ["示例大学（211）", "示例师范（211）"],
  普通一本: ["示例财经大学", "示例工业大学"],
  普通二本: ["示例文理学院", "示例工程学院"],
  专科: ["示例职业技术学院", "示例高等专科学校"],
};

function demoRecommend(province: string, subject: string, rank: number, _major: unknown) {
  const tiers = rankTiers(rank);
  const outTiers: any[] = [];
  let reach = 0, match = 0, safe = 0, unreachable = 0;
  tiers.forEach((t, i) => {
    const state = gateState(rank, t.min_rank);
    const level = i === 0 ? "冲" : i <= 2 ? "稳" : "保";
    const open = state === "open";
    if (!open && i < 3) unreachable++;
    if (open && level === "冲") reach++;
    if (open && level === "稳") match++;
    if (open && level === "保") safe++;
    const names = SAMPLE_SCHOOLS[t.tier] || [];
    const schools: DemoSchool[] = names.map((n, j) => ({
      name: n,
      province,
      city: "示例市",
      category: t.tier,
      nature: t.tier.includes("985") ? "公办" : "公办",
      min_score: 500 + (5 - i) * 20 + j * 5,
      min_rank: t.min_rank + j * 50,
      line_year: 2025,
    }));
    outTiers.push({
      tier: t.tier,
      level,
      data_source: "demo",
      carried: false,
      source_year: 2025,
      min_score: 500 + (5 - i) * 20,
      min_rank: t.min_rank,
      pool_label: t.label,
      pool_total: schools.length,
      schools,
      basis: "演示模式：示意院校，非真实投档线。",
      school_line_hits: schools.length,
      pool_shared_with: "",
    });
  });

  return {
    province,
    subject,
    user_rank: rank,
    summary: { reach, match, safe, unreachable },
    school_line_hits: outTiers.reduce((a, t) => a + t.schools.length, 0),
    data_source: "demo",
    tiers: outTiers,
    notes: ["演示模式：院校与分数线为示意，仅用于体验界面。连接后端查看真实数据。"],
  };
}

function demoVolunteerLimit(province: string) {
  // 通用示意配额（真实值见后端 volunteer_limits.json）。
  const map: Record<string, { undergrad: number; junior: number; mode: string }> = {
    河南: { undergrad: 48, junior: 48, mode: "院校专业组" },
    辽宁: { undergrad: 112, junior: 60, mode: "专业+院校" },
    广东: { undergrad: 45, junior: 45, mode: "院校专业组" },
    河北: { undergrad: 96, junior: 96, mode: "专业+院校" },
    山东: { undergrad: 96, junior: 96, mode: "专业+院校" },
  };
  const base = map[province] || { undergrad: 40, junior: 40, mode: "专业+院校" };
  const reach = Math.max(6, Math.round(base.undergrad * 0.3));
  const match = Math.max(6, Math.round(base.undergrad * 0.45));
  const safeN = Math.max(6, base.undergrad - reach - match);
  return {
    province,
    mode: base.mode,
    undergrad: base.undergrad,
    junior: base.junior,
    split: { reach, match, safe: safeN },
    note: "演示模式：配额为示意值，正式以本省考试院公布为准。",
  };
}

function demoControlLineYears() {
  return [
    { year: 2026, data_source: "demo", anchors: 4 },
    { year: 2025, data_source: "demo", anchors: 4 },
    { year: 2024, data_source: "demo", anchors: 4 },
    { year: 2023, data_source: "demo", anchors: 4 },
    { year: 2022, data_source: "demo", anchors: 4 },
  ];
}

function demoControlLines(year: number, province: string) {
  // 示意省控线（物理类 / 历史类 双档）。
  const lines: Record<string, Record<string, number>> = {
    物理类: { 普通一本: 510, 普通二本: 430, 专科: 200 },
    历史类: { 普通一本: 530, 普通二本: 450, 专科: 200 },
    综合: { 普通一本: 520, 普通二本: 440, 专科: 200 },
  };
  const subject = lines[province] ? "物理类" : "物理类";
  const base = lines[subject] || lines["物理类"];
  const tiers = ["普通一本", "普通二本", "专科"];
  const rows = tiers.map((t, i) => ({
    tier: t,
    score: base[t],
    subject,
    year,
    source_url: "",
  }));
  return {
    province,
    year,
    subject_scheme: "物理类/历史类",
    tiers,
    rows,
    note: "演示模式：省控线为示意值，非真实数据。",
  };
}

export function resolveDemo(method: string, path: string, data?: unknown): unknown {
  const d = (data || {}) as Record<string, any>;
  if (method === "GET" && path === "/api/verdict") {
    return demoVerdict(d.province, d.subject, Number(d.user_rank));
  }
  if (method === "GET" && path === "/api/recommend/schools") {
    return demoRecommend(d.province, d.subject, Number(d.user_rank), d.major_name);
  }
  if (method === "GET" && path === "/api/admission/volunteer-limit") {
    return demoVolunteerLimit(d.province);
  }
  if (method === "GET" && path === "/api/admission/control-line-years") {
    return demoControlLineYears();
  }
  if (method === "GET" && path === "/api/admission/control-lines") {
    return demoControlLines(d.year, d.province);
  }
  // 其余接口（核验 / 等位分等）演示模式暂不覆盖。
  return undefined;
}
