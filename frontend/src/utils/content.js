// 单一数据源：通过 @shared 别名引入 shared/*.json，与 Python 后端共用同一份内容。
//
// ⚠️ 分包瘦身（P1 核心）：content 172KB + school_graph 48KB + glossary 13KB ≈ 234KB。
// 这三个 JSON 若【静态 import】，会被打进小程序【主包】初始体积，逼近 2MB 上限
// （tabBar 页能引入 content.js，而 tabBar 页不能进分包，所以静态引入必然堆在主包）。
//
// 改为按需【动态 import()】：首次访问时由页面 onLoad 调用 ensureContent() 拉取并填入
// 模块级缓存；各导出用 `export let` 声明，ensureContent() 拉取后原地赋值——利用 ESM
// 实时绑定，页面 `await ensureContent()` 后即可读到最新值，且主包初始体积不再包含这 234KB。
//
// 重要约定（避免拿到空数据）：
//   页面【不得】在 <script setup> 顶层直接解构/读取这些导出（顶层执行早于异步加载）。
//   必须在 onLoad / onShow 里先 `await ensureContent()`，再读取（并赋给 ref / 触发 computed）。

let _cache = null;
let _loading = null;

function pick(mod) {
  return mod && mod.default !== undefined ? mod.default : mod;
}

function buildData(content, graph, glossary) {
  const c = pick(content);
  const g = pick(graph);
  const gl = pick(glossary);
  return {
    APP_VERSION: c.APP_VERSION,
    DATA_DATE: c.DATA_DATE,
    QUESTIONS: c.QUESTIONS || [],
    MAJORS: c.MAJORS || [],
    RESOURCES: c.RESOURCES || [],
    SCHOOL_GRAPH: g || null,
    SCHOOL_TIERS: (g && g.tiers) || null,
    SCHOOL_LEAGUES: (g && g.leagues) || null,
    SCHOOLS: (g && g.schools) || null,
    GLOSSARY: gl || null,
    CONTENT_SOURCE: c.CONTENT_SOURCE || {},
  };
}

export async function ensureContent() {
  if (_cache) return _cache;
  if (_loading) return _loading;
  _loading = (async () => {
    const [content, graph, glossary] = await Promise.all([
      import("@shared/content.json"),
      import("@shared/school_graph.json"),
      import("@shared/domain_glossary.json"),
    ]);
    _cache = buildData(content, graph, glossary);
    // 原地赋值，利用 ESM 实时绑定让既有导入方拿到新值
    APP_VERSION = _cache.APP_VERSION;
    DATA_DATE = _cache.DATA_DATE;
    QUESTIONS = _cache.QUESTIONS;
    MAJORS = _cache.MAJORS;
    RESOURCES = _cache.RESOURCES;
    SCHOOL_GRAPH = _cache.SCHOOL_GRAPH;
    SCHOOL_TIERS = _cache.SCHOOL_TIERS;
    SCHOOL_LEAGUES = _cache.SCHOOL_LEAGUES;
    SCHOOLS = _cache.SCHOOLS;
    GLOSSARY = _cache.GLOSSARY;
    CONTENT_SOURCE = _cache.CONTENT_SOURCE;
    return _cache;
  })();
  return _loading;
}

// 静态字面量（不依赖 JSON，可直接使用，无需 ensureContent）
export const VIEW_LABEL = { recommend: "推荐", caution: "慎选", avoid: "避坑" };
export const CATS = ["理工硬核", "医学类", "文科保底", "体制内", "避坑天坑"];
export const RES_CATS = [
  { key: "all", label: "全部" },
  { key: "mind", label: "思想/语料" },
  { key: "tool", label: "数据/工具" },
];

// JSON 派生导出（初始为空，ensureContent() 后填充）
export let APP_VERSION = "";
export let DATA_DATE = "";
export let QUESTIONS = [];
export let MAJORS = [];
export let RESOURCES = [];
export let SCHOOL_GRAPH = null;
export let SCHOOL_TIERS = null;
export let SCHOOL_LEAGUES = null;
export let SCHOOLS = null;
export let GLOSSARY = null;
export let CONTENT_SOURCE = {};
