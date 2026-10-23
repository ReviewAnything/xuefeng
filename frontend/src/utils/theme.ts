// 设计令牌与主题系统（P4）
// ---------------------------------------------------------------------------
// 一处定义，全站引用。本文件既是「设计令牌源」，也是「主题注册表」：
//   · THEMES         —— 全部可选主题（暗夜金 / 晨曦白 / 墨青），每套含
//                       vars(--xf-*) + 语义色 + wot themeVars 覆盖。
//   · themeState     —— 响应式当前主题（id / mode / style 字符串），供页面绑定。
//   · themeVars      —— 响应式 wot-design-uni 变量，随主题切换自动重渲染组件库。
//   · applyTheme / initTheme / setTheme —— 运行时切换与持久化。
//   · levelColor / credMeta —— 语义取色，跟随当前主题（不再写死深色值）。
//
// 页面里不要再用魔法值写 `#ffd24d`、`20rpx` 这类硬编码；改用 tokens 或
// App.vue 里注入的同名 CSS 变量（--xf-*），换肤只改这一个文件。

import { reactive } from "vue";

// ---- 主题注册表 ----
// 每套主题：
//   id / name / desc / mode(dark|light，喂给 wot) / swatch(选择器预览色)
//   vars   —— 全部 --xf-* 自定义属性（经 config-provider 的 :style 注入到页面根）
//   color  —— 语义色（冲稳保 / 危险 / 可信度 / 品牌），levelColor/credMeta 取这里
//   wot    —— 该主题下 wot-design-uni 的 themeVars 覆盖
export const THEMES = [
  {
    id: "dark",
    name: "暗夜金",
    desc: "深色底 + 暖金，护眼且对比强",
    mode: "dark",
    swatch: { bg: "#0f1115", surface: "#16191f", accent: "#ffd24d" },
    vars: {
      "--xf-bg": "#0f1115",
      "--xf-surface": "#16191f",
      "--xf-surface-2": "#1c2026",
      "--xf-surface-3": "#23262e",
      "--xf-line": "#23262e",
      "--xf-line-soft": "#1c2027",
      "--xf-text": "#e9ebef",
      "--xf-text-2": "#c2c8d0",
      "--xf-text-3": "#8f96a2",
      "--xf-text-4": "#6f7683",
      "--xf-gold": "#ffd24d",
      "--xf-gold-dim": "#c9a53a",
      "--xf-reach": "#f0ad4e",
      "--xf-match": "#6db3f2",
      "--xf-safe": "#5fd87f",
      "--xf-danger": "#e5484d",
      "--xf-danger-text": "#ff8787",
      "--xf-official": "#5fd87f",
      "--xf-real": "#6db3f2",
      "--xf-est": "#9aa0aa",
      "--xf-demo": "#f0ad4e",
      "--xf-fill": "rgba(255,255,255,0.05)",
      "--xf-shimmer-1": "#1a1e25",
      "--xf-shimmer-2": "#232833",
    },
  },
  {
    id: "light",
    name: "晨曦白",
    desc: "浅色底 + 沉金，白天户外更清晰",
    mode: "light",
    swatch: { bg: "#f4f6f8", surface: "#ffffff", accent: "#c8910a" },
    vars: {
      "--xf-bg": "#f4f6f8",
      "--xf-surface": "#ffffff",
      "--xf-surface-2": "#eef1f4",
      "--xf-surface-3": "#e6eaef",
      "--xf-line": "#e3e7ec",
      "--xf-line-soft": "#eef1f4",
      "--xf-text": "#1f2329",
      "--xf-text-2": "#4b525b",
      "--xf-text-3": "#828a93",
      "--xf-text-4": "#aab0b8",
      "--xf-gold": "#c8910a",
      "--xf-gold-dim": "#a8770a",
      "--xf-reach": "#d9821a",
      "--xf-match": "#2f7ad1",
      "--xf-safe": "#1f9d57",
      "--xf-danger": "#d23b3b",
      "--xf-danger-text": "#d23b3b",
      "--xf-official": "#1f9d57",
      "--xf-real": "#2f7ad1",
      "--xf-est": "#9aa0aa",
      "--xf-demo": "#d9821a",
      "--xf-fill": "rgba(0,0,0,0.045)",
      "--xf-shimmer-1": "#e9edf1",
      "--xf-shimmer-2": "#f3f5f8",
    },
  },
  {
    id: "teal",
    name: "墨青",
    desc: "青黑底 + 青碧，沉静不刺眼",
    mode: "dark",
    swatch: { bg: "#0c1416", surface: "#122021", accent: "#46c8b8" },
    vars: {
      "--xf-bg": "#0c1416",
      "--xf-surface": "#122021",
      "--xf-surface-2": "#182a2a",
      "--xf-surface-3": "#1f3433",
      "--xf-line": "#1f3433",
      "--xf-line-soft": "#162827",
      "--xf-text": "#e2eeec",
      "--xf-text-2": "#b6c5c2",
      "--xf-text-3": "#7e928e",
      "--xf-text-4": "#5e726e",
      "--xf-gold": "#46c8b8",
      "--xf-gold-dim": "#2f9488",
      "--xf-reach": "#e0a23e",
      "--xf-match": "#4fb3d1",
      "--xf-safe": "#4fd18a",
      "--xf-danger": "#e5686a",
      "--xf-danger-text": "#f0a0a2",
      "--xf-official": "#4fd18a",
      "--xf-real": "#4fb3d1",
      "--xf-est": "#8fa39f",
      "--xf-demo": "#e0a23e",
      "--xf-fill": "rgba(255,255,255,0.045)",
      "--xf-shimmer-1": "#142322",
      "--xf-shimmer-2": "#1c2e2d",
    },
  },
];

export const THEME_IDS = THEMES.map((t) => t.id);
export const DEFAULT_THEME = "dark";
const STORAGE_KEY = "zhiyuan_theme";

function themeById(id: string) {
  return THEMES.find((t) => t.id === id) || THEMES[0];
}

// wot-design-uni 组件库变量：随主题切换，保证 picker/button/switch/collapse 等
// 原生组件也跟着换肤。状态色各主题一致，文字/背景色按 mode 取。
const STATUS = {
  colorSuccess: "#5fd87f",
  colorWarning: "#f0ad4e",
  colorDanger: "#ff6b6b",
  colorInfo: "#6db3f2",
  colorPurple: "#b48ef0",
  colorYellow: "#ffd24d",
  colorBlue: "#6db3f2",
  radiusBig: "20rpx",
  radiusNormal: "12rpx",
};

function buildWotVars(t: any) {
  const accent = t.vars["--xf-gold"];
  const base = { colorTheme: accent, ...STATUS };
  if (t.mode === "light") {
    return {
      ...base,
      colorTitle: "#1f2329",
      colorContent: "#4b525b",
      colorSecondary: "#828a93",
      colorAid: "#aab0b8",
      colorTip: "#aab0b8",
      colorBorder: "#e3e7ec",
      colorBorderLight: "#eef1f4",
      colorBg: "#ffffff",
      colorWhite: "#ffffff",
      colorBlack: "#000000",
      darkBackground: "#ffffff",
      darkBackground2: "#f6f8fa",
      darkBackground3: "#eef1f4",
      darkBackground4: "#e6eaef",
      darkBackground5: "#ffffff",
      darkBackground6: "#f6f8fa",
      darkBackground7: "#ffffff",
      darkColor: "#1f2329",
      darkColor2: "#4b525b",
      darkColor3: "#828a93",
      darkColorGray: "#aab0b8",
      darkBorderColor: "#e3e7ec",
    };
  }
  // dark / teal：文字与背景取自本主题变量
  return {
    ...base,
    colorTitle: t.vars["--xf-text"],
    colorContent: t.vars["--xf-text-2"],
    colorSecondary: t.vars["--xf-text-3"],
    colorAid: t.vars["--xf-text-4"],
    colorTip: t.vars["--xf-text-4"],
    colorBorder: t.vars["--xf-line"],
    colorBorderLight: t.vars["--xf-line-soft"],
    colorBg: t.vars["--xf-bg"],
    colorWhite: "#ffffff",
    colorBlack: "#000000",
    darkBackground: t.vars["--xf-surface"],
    darkBackground2: t.vars["--xf-surface-2"],
    darkBackground3: t.vars["--xf-surface-3"],
    darkBackground4: t.vars["--xf-surface-3"],
    darkBackground5: t.vars["--xf-bg"],
    darkBackground6: t.vars["--xf-bg"],
    darkBackground7: t.vars["--xf-bg"],
    darkColor: t.vars["--xf-text"],
    darkColor2: t.vars["--xf-text-2"],
    darkColor3: t.vars["--xf-text-3"],
    darkColorGray: t.vars["--xf-text-4"],
    darkBorderColor: t.vars["--xf-line"],
  };
}

// 当前主题的状态（响应式，供页面模板绑定 $theme.mode / $theme.style）
export const themeState = reactive({ id: DEFAULT_THEME, mode: "dark", style: "" });

// wot 组件库变量（响应式，config-provider 自动重渲染）
export const themeVars = reactive(buildWotVars(THEMES[0]));

let _active = DEFAULT_THEME;

function buildStyle(t: any) {
  return Object.entries(t.vars)
    .map(([k, v]) => `${k}:${v}`)
    .join(";");
}

export function applyTheme(id: string) {
  const t = themeById(id);
  _active = id;
  themeState.id = id;
  themeState.mode = t.mode;
  themeState.style = buildStyle(t);
  // 组件库变量：原地赋值，保持响应式引用，config-provider 自动重渲染
  Object.assign(themeVars, buildWotVars(t));
  // H5：同步到 <html>，覆盖页面最外层背景，避免切换瞬间闪白/闪黑
  // #ifdef H5
  try {
    const root = document.documentElement;
    Object.entries(t.vars).forEach(([k, v]) => root.style.setProperty(k, v as string));
    root.setAttribute("data-theme", id);
  } catch (e) {}
  // #endif
  // 持久化到端侧
  try {
    uni.setStorageSync(STORAGE_KEY, id);
  } catch (e) {}
}

export function initTheme() {
  let id = DEFAULT_THEME;
  try {
    id = uni.getStorageSync(STORAGE_KEY) || DEFAULT_THEME;
  } catch (e) {}
  applyTheme(themeById(id).id);
}

export function setTheme(id: string) {
  if (!THEME_IDS.includes(id)) return;
  applyTheme(id);
}

// ---- 语义令牌（保留，供个别脚本/测试引用）----
export const tokens = {
  color: {
    bg: "#0f1115",
    surface: "#16191f",
    surface2: "#1c2026",
    surface3: "#23262e",
    line: "#23262e",
    lineSoft: "#1c2027",
    text: "#e9ebef",
    text2: "#c2c8d0",
    text3: "#8f96a2",
    text4: "#6f7683",
    gold: "#ffd24d",
    goldDim: "#c9a53a",
    reach: "#f0ad4e",
    match: "#6db3f2",
    safe: "#5fd87f",
    danger: "#e5484d",
    dangerText: "#ff8787",
    official: "#5fd87f",
    real: "#6db3f2",
    est: "#9aa0aa",
    demo: "#f0ad4e",
  },
  font: {
    h1: "44rpx",
    h2: "34rpx",
    h3: "28rpx",
    body: "26rpx",
    sub: "24rpx",
    tiny: "22rpx",
    micro: "20rpx",
  },
  radius: { sm: "10rpx", md: "16rpx", lg: "22rpx", pill: "999rpx" },
  space: { xs: "8rpx", sm: "12rpx", md: "18rpx", lg: "24rpx", xl: "36rpx" },
  motion: { fast: "140ms", base: "180ms" },
};

// 档位 → 语义色（冲/稳/保 全站统一，跟随当前主题）
export function levelColor(level: string) {
  const c = themeById(_active).vars;
  if (level === "冲") return c["--xf-reach"];
  if (level === "稳") return c["--xf-match"];
  if (level === "保") return c["--xf-safe"];
  return c["--xf-text-3"];
}

// 档位 → 图标名（icons.js 语义别名）
export function levelIcon(level: string) {
  if (level === "冲") return "reach";
  if (level === "稳") return "match";
  if (level === "保") return "safe";
  return "unknown";
}

// 数据来源 → 可信度展示（徽章文案 + 色 + 图标），跟随当前主题
export function credMeta(dataSource: string) {
  const c = themeById(_active).vars;
  const ds = String(dataSource || "");
  if (ds === "demo") {
    return { label: "演示数据", cls: "demo", color: c["--xf-demo"], icon: "sparkle" };
  }
  if (ds === "official" || ds === "official_overlay" || ds === "official_table") {
    return { label: "官方数据", cls: "official", color: c["--xf-official"], icon: "check" };
  }
  if (ds === "real" || ds === "third_party_text") {
    return { label: "真实抓取", cls: "real", color: c["--xf-real"], icon: "info" };
  }
  return { label: "估算数据", cls: "est", color: c["--xf-est"], icon: "info" };
}

export default themeVars;
