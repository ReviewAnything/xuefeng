// 设计令牌（P3-A）：一处定义，全站引用。
//
// 分两层：
//   1. themeVars —— 交给 wot-design-uni 的主题变量（组件库内部消费）
//   2. tokens    —— 我们自己页面的语义令牌（颜色/字阶/间距/圆角/动效）
//
// 页面里不要再用魔法值写 `#ffd24d`、`20rpx` 这类硬编码；改用 tokens 或
// App.vue 里注入的同名 CSS 变量（--xf-*），这样换肤/调字号只改这一个文件。

// ---- wot-design-uni 主题变量（深色品牌主题：金 + 深灰）----
export const themeVars = {
  // 主色 / 状态色
  colorTheme: "#ffd24d",
  colorSuccess: "#5fd87f",
  colorWarning: "#f0ad4e",
  colorDanger: "#ff6b6b",
  colorInfo: "#6db3f2",
  colorPurple: "#b48ef0",
  colorYellow: "#ffd24d",
  colorBlue: "#6db3f2",

  // 深色背景层级
  darkBackground: "#16191f",
  darkBackground2: "#1c1f26",
  darkBackground3: "#23262e",
  darkBackground4: "#2a2e37",
  darkBackground5: "#0f1115",
  darkBackground6: "#12151a",
  darkBackground7: "#0b0d10",

  // 深色文字
  darkColor: "#e6e8ec",
  darkColor2: "#c7ccd4",
  darkColor3: "#8a909c",
  darkColorGray: "#6b7280",
  darkBorderColor: "#23262e",

  // 浅色兜底（部分组件在 light 模式下使用）
  colorTitle: "#e6e8ec",
  colorContent: "#c7ccd4",
  colorSecondary: "#8a909c",
  colorAid: "#6b7280",
  colorTip: "#6b7280",
  colorBorder: "#2a2e37",
  colorBorderLight: "#23262e",
  colorBg: "#0f1115",
  colorWhite: "#ffffff",
  colorBlack: "#000000",

  // 圆角
  radiusBig: "20rpx",
  radiusNormal: "12rpx",
};

// ---- 语义令牌 ----
export const tokens = {
  color: {
    // 面：越往前越亮，靠「面」而不是靠字号分层
    bg: "#0f1115",
    surface: "#16191f",
    surface2: "#1c2026",
    surface3: "#23262e",
    line: "#23262e",
    lineSoft: "#1c2027",

    // 字：4 级足够，最暗一级仍要可读（对比度 ≥ 4.5:1 目标）
    text: "#e9ebef",
    text2: "#c2c8d0",
    text3: "#8f96a2",
    text4: "#6f7683",

    // 品牌
    gold: "#ffd24d",
    goldDim: "#c9a53a",

    // 冲稳保 + 危险
    reach: "#f0ad4e",
    match: "#6db3f2",
    safe: "#5fd87f",
    danger: "#e5484d",
    dangerText: "#ff8787",

    // 数据可信度
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

// 档位 → 语义色（冲/稳/保 全站统一，不再各页各写一套）
export function levelColor(level) {
  if (level === "冲") return tokens.color.reach;
  if (level === "稳") return tokens.color.match;
  if (level === "保") return tokens.color.safe;
  return tokens.color.text3;
}

// 档位 → 图标名（icons.js 语义别名）
export function levelIcon(level) {
  if (level === "冲") return "reach";
  if (level === "稳") return "match";
  if (level === "保") return "safe";
  return "unknown";
}

// 数据来源 → 可信度展示（徽章文案 + 色 + 图标），各页共用同一套口径，避免
// 「同一份数据在结论页叫官方、在推荐页叫真实抓取」这种自相矛盾。
export function credMeta(dataSource) {
  const ds = String(dataSource || "");
  if (ds === "demo") {
    return { label: "演示数据", cls: "demo", color: tokens.color.demo, icon: "sparkle" };
  }
  if (ds === "official" || ds === "official_overlay" || ds === "official_table") {
    return { label: "官方数据", cls: "official", color: tokens.color.official, icon: "check" };
  }
  if (ds === "real" || ds === "third_party_text") {
    return { label: "真实抓取", cls: "real", color: tokens.color.real, icon: "info" };
  }
  return { label: "估算数据", cls: "est", color: tokens.color.est, icon: "info" };
}

export default themeVars;
