// 零依赖图标系统（P3-A）
// ---------------------------------------------------------------------------
// 为什么不引图标字体 / 第三方 svg 库：
//  1. 本项目要同时跑 H5 与小程序，字体图标需额外 @font-face 与跨域配置，容易在
//     GitHub Pages 之外的环境失配；离线演示（无网络）时更要零外部请求。
//  2. 线性图标的可调性（颜色/字号/线宽）用 SVG 参数生成即可，不必打包整套资产。
//
// 做法：每个图标只存 24×24 viewBox 内的<b>内部图元</b>，运行时按需拼成完整 SVG，
// 再 base64 成 data URI 交给 <image> —— H5 / 小程序都认 data URI，且不留外链。
//
// 用法：
//   import { iconSrc, hasIcon } from "@/utils/icons";
//   iconSrc("target", "#ffd24d")            // → "data:image/svg+xml;base64,..."
//   <app-icon name="target" color="#ffd24d" :size="36" />

// 图标表：键名即语义名，值是 24×24 内的 SVG 图元串。
// 约定：只用 stroke 描边（fill="none"），需要实心点的地方显式写 fill="__C__"。
const PATHS: Record<string, string> = {
  // —— 导航/任务 ——
  target:
    '<circle cx="12" cy="12" r="8.2"/><circle cx="12" cy="12" r="3.6"/>' +
    '<circle cx="12" cy="12" r="0.9" fill="__C__" stroke="none"/>',
  school:
    '<path d="M12 3.2 20.5 8H3.5L12 3.2Z"/><path d="M6 10.6v6M10 10.6v6M14 10.6v6M18 10.6v6"/>' +
    '<path d="M3.8 20.4h16.4"/>',
  list:
    '<path d="M8.6 6.6h11M8.6 12h11M8.6 17.4h11"/>' +
    '<path d="M4.7 6.6h.01M4.7 12h.01M4.7 17.4h.01"/>',
  search: '<circle cx="10.8" cy="10.8" r="6.4"/><path d="M15.6 15.6 20.4 20.4"/>',
  user: '<circle cx="12" cy="8.2" r="3.7"/><path d="M4.8 20.2c1.1-3.6 3.8-5.4 7.2-5.4s6.1 1.8 7.2 5.4"/>',
  compass: '<circle cx="12" cy="12" r="8.6"/><path d="M15.4 8.6 13.4 14l-5.4 2 2-5.4 5.4-2Z"/>',
  chart:
    '<path d="M4 20h16"/><rect x="6" y="12" width="3.4" height="5.8" rx="1"/>' +
    '<rect x="11.3" y="8.4" width="3.4" height="9.4" rx="1"/>' +
    '<rect x="16.6" y="5" width="3.4" height="12.8" rx="1"/>',
  graph:
    '<circle cx="6.4" cy="6.4" r="2.5"/><circle cx="17.6" cy="8" r="2.5"/><circle cx="10.4" cy="17.4" r="2.5"/>' +
    '<path d="M8.7 7.8l6.5 1.2M16.1 10.2l-4.2 4.9M8 8.9l1.6 5.9"/>',
  bulb:
    '<path d="M9.2 17.2h5.6M10.2 20.2h3.6"/>' +
    '<path d="M12 3.6a6 6 0 0 0-3.5 10.9c.5.4.8 1 .8 1.6v1.1h5.4v-1.1c0-.6.3-1.2.8-1.6A6 6 0 0 0 12 3.6Z"/>',
  // —— 语义/状态 ——
  check: '<path d="M5 12.8 9.6 17.4 19 8"/>',
  alert: '<path d="M12 4.4 21 19.6H3L12 4.4Z"/><path d="M12 9.7v4.1"/><path d="M12 16.8h.01"/>',
  info: '<circle cx="12" cy="12" r="8.6"/><path d="M12 11.1v5.3"/><path d="M12 7.9h.01"/>',
  close: '<path d="M6.4 6.4 17.6 17.6M17.6 6.4 6.4 17.6"/>',
  shield:
    '<path d="M12 3.6 19 6.3v5.4c0 4-2.9 7.1-7 8.7-4.1-1.6-7-4.7-7-8.7V6.3L12 3.6Z"/>' +
    '<path d="M9.2 12.2 11.3 14.3 15 10.4"/>',
  star: '<path d="M12 4.2l2.4 4.9 5.4.8-3.9 3.8.9 5.4-4.8-2.5-4.8 2.5.9-5.4L4.2 9.9l5.4-.8L12 4.2Z"/>',
  sparkle:
    '<path d="M11.4 3.6l1.7 4.4 4.4 1.7-4.4 1.7-1.7 4.4-1.7-4.4L5.3 9.7l4.4-1.7 1.7-4.4Z"/>' +
    '<path d="M18.2 15.6l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7.7-1.8Z"/>',
  // —— 冲稳保 ——
  "trending-up": '<path d="M3.6 16.6 9.6 10.6l3.6 3.6L20.4 6.9"/><path d="M15.6 6.9h4.8v4.8"/>',
  equals: '<path d="M5.6 9.6h12.8M5.6 14.4h12.8"/>',
  // —— 操作 ——
  "arrow-up": '<path d="M12 19.2V5"/><path d="M6.2 10.8 12 5l5.8 5.8"/>',
  "arrow-down": '<path d="M12 4.8V19"/><path d="M6.2 13.2 12 19l5.8-5.8"/>',
  "chevron-right": '<path d="M9.4 5.6 15.8 12l-6.4 6.4"/>',
  "chevron-down": '<path d="M5.6 9.4 12 15.8l6.4-6.4"/>',
  external:
    '<path d="M14 4.6h5.4V10"/><path d="M19.4 4.6 11.2 12.8"/>' +
    '<path d="M17.8 14.2v4a1.6 1.6 0 0 1-1.6 1.6H5.6A1.6 1.6 0 0 1 4 18.2V7.6A1.6 1.6 0 0 1 5.6 6h4"/>',
  copy:
    '<rect x="8.6" y="8.6" width="11" height="11.2" rx="2"/>' +
    '<path d="M15.4 5.4H6.6a2 2 0 0 0-2 2v8.8"/>',
  printer:
    '<path d="M7 9.2V4.6h10v4.6"/><rect x="4" y="9.2" width="16" height="7" rx="1.6"/>' +
    '<path d="M7 14h10v5.4H7V14Z"/>',
  refresh: '<path d="M20.2 12a8.2 8.2 0 1 1-2.7-6.1"/><path d="M20.6 4.6v4.2h-4.2"/>',
  download: '<path d="M12 4v10.4"/><path d="M7.6 10.4 12 14.8l4.4-4.4"/><path d="M4.8 18.6h14.4"/>',
  filter: '<path d="M4.4 6.4h15.2L13.8 13v5.6l-3.6 1.8V13L4.4 6.4Z"/>',
  layers:
    '<path d="M12 3.6 20.4 8 12 12.4 3.6 8 12 3.6Z"/><path d="M3.6 12.4 12 16.8l8.4-4.4"/>' +
    '<path d="M3.6 16.4 12 20.8l8.4-4.4"/>',
  calendar:
    '<rect x="3.8" y="5.6" width="16.4" height="14.6" rx="2"/><path d="M3.8 10.2h16.4"/>' +
    '<path d="M8.4 3.8v3.4M15.6 3.8v3.4"/>',
  clock: '<circle cx="12" cy="12" r="8.4"/><path d="M12 7.6V12l3 1.8"/>',
  theme:
    '<circle cx="12" cy="12" r="8.6"/>' +
    '<path d="M12 3.4a8.6 8.6 0 0 0 0 17.2Z" fill="__C__" stroke="none"/>',
  book:
    '<path d="M12 6.6C10.4 5.2 8.2 4.6 5.4 4.6V17.6C8.2 17.6 10.4 18.2 12 19.6Z"/>' +
    '<path d="M12 6.6C13.6 5.2 15.8 4.6 18.6 4.6V17.6C15.8 17.6 13.6 18.2 12 19.6Z"/>',
};

// 语义别名：让页面按「含义」取图标，而不是背图标名（换风格只改这里）
export const ICON_ALIAS: Record<string, string> = {
  home: "target",
  reach: "trending-up",
  match: "equals",
  safe: "shield",
  unknown: "info",
  plan: "list",
  recommend: "school",
  verify: "search",
  theme: "theme",
  me: "user",
  compass: "compass",
};

export function hasIcon(name: string) {
  const k = ICON_ALIAS[name] || name;
  return !!PATHS[k];
}

function b64(str: string) {
  const T = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  let out = "";
  for (let i = 0; i < str.length; i += 3) {
    const c1 = str.charCodeAt(i);
    const c2 = str.charCodeAt(i + 1);
    const c3 = str.charCodeAt(i + 2);
    const has2 = !Number.isNaN(c2);
    const has3 = !Number.isNaN(c3);
    out += T[c1 >> 2];
    out += T[((c1 & 3) << 4) | (has2 ? c2 >> 4 : 0)];
    out += has2 ? T[((c2 & 15) << 2) | (has3 ? c3 >> 6 : 0)] : "=";
    out += has3 ? T[c3 & 63] : "=";
  }
  return out;
}

const CACHE = new Map<string, string>();

/**
 * 生成可直接喂给 <image :src> 的 data URI。
 * @param {string} name  图标名（可用 ICON_ALIAS 里的语义名）
 * @param {string} color 描边色（#rrggbb 或 rgba()）
 * @param {number} width 线宽（默认 1.7，24×24 坐标系内）
 */
export function iconSvg(name: string, color?: string, width?: number) {
  const key = ICON_ALIAS[name] || name;
  const inner = PATHS[key];
  if (!inner) return "";
  const c = color || "#e6e8ec";
  const sw = width || 1.7;
  const inner2 = inner.replace(/__C__/g, c);
  return (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" ' +
    'fill="none" stroke="' + c + '" stroke-width="' + sw + '" ' +
    'stroke-linecap="round" stroke-linejoin="round">' + inner2 + "</svg>"
  );
}

export function iconSrc(name: string, color?: string, width?: number) {
  const key = (ICON_ALIAS[name] || name) + "|" + (color || "#e6e8ec") + "|" + (width || 1.7);
  const hit = CACHE.get(key);
  if (hit) return hit;
  const svg = iconSvg(name, color, width);
  if (!svg) return "";
  const uri = "data:image/svg+xml;base64," + b64(svg);
  CACHE.set(key, uri);
  return uri;
}

/** 图标清单（供「我的 → 关于」或测试枚举，避免有名字写错却静默空白） */
export function iconNames() {
  return Object.keys(PATHS);
}
