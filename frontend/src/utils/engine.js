// 决策引擎：纯函数，无 uni / 浏览器依赖，可在 Node 下单测（frontend/tests/engine.test.mjs）。
// 输入用户画像 d 与专业列表 majors，输出决策画布（框架，非定论）。

export const VIEW_LABEL = { recommend: "推荐", caution: "慎选", avoid: "避坑" };

export function buildStrategy(tier) {
  if (tier === "冲刺985")
    return "<b>985层面学校牌子够硬</b>：可适度追好专业；若只能进985冷门天坑，优先考虑转专业/考研换方向，而非死磕专业。";
  if (tier === "211线附近")
    return "<b>211附近：专业第一。</b>同层次学校牌子差距不大，好专业与差专业就业是天地之别。";
  if (tier === "普通一本/二本")
    return "<b>普通一二本：专业是救命稻草。</b>必须选有技术壁垒的专业，用人单位只看你能干什么。";
  return "<b>专科/高职：一技之长优先。</b>选护理、口腔医技、机电一体化、现代殡葬等能吃饭的方向。";
}

export function pickMajors(d, majors) {
  let pool = majors.filter((m) => m.view !== "avoid");
  if (d.subject === "历史类")
    pool = pool.filter(
      (m) =>
        ["文科保底", "体制内"].includes(m.cat) ||
        m.name.includes("法学") ||
        m.name.includes("汉语言")
    );
  const stable =
    d.familyBg === "寒门(容错率低)" ||
    d.riskPref === "求稳优先" ||
    d.goal === "稳定/有编有岗";
  if (stable) {
    pool = pool.filter(
      (m) =>
        ["体制内"].includes(m.cat) ||
        m.cat === "文科保底" ||
        m.tags.includes("越老越香") ||
        m.tags.includes("国网校招") ||
        m.cat === "医学类"
    );
  }
  return pool.slice(0, 8);
}

export function buildBiasWarn(d) {
  if (d.familyBg === "资源型(有人脉/可试错)")
    return "你家庭容错率较高，张雪峰的'普通家庭求稳'框架对你约束较弱，可更重视兴趣与长期主义。";
  return "你处于张雪峰框架的核心适用人群（普通/寒门），但请记住：<b>兴趣不是第一标准，但也不该被完全牺牲</b>；国家也需要基础学科人才。";
}

export function buildCanvas(d, majors) {
  const strategy = buildStrategy(d.tier || "普通一本/二本");
  const picks = pickMajors(d, majors).map((m) => ({ name: m.name, view: m.view }));
  const biasWarn = buildBiasWarn(d);
  const avoidHint = majors
    .filter((m) => m.view === "avoid")
    .slice(0, 4)
    .map((m) => m.name);
  const next = [
    "到「专业图谱」查候选专业的张雪峰观点 + 偏见校正",
    "到「核验」页用真实录取位次做 观点×数据 交叉核验",
    "去招聘网站搜岗位，看要求什么专业/技能（张雪峰原话）",
  ];
  return { strategy, picks, biasWarn, avoidHint, next };
}
