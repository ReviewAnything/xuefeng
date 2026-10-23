// 核心领域类型（渐进式 TS 第一阶段）
// ---------------------------------------------------------------------------
// 纯类型文件：无运行时依赖、无 Node 语义（无 import.meta / process / require），
// 可在 H5 与小程序两端安全使用。后续各模块（profile / theme / api / content）
// 将逐步从这里引入类型，做到「渐进式」而非一次性全量重写。

/** 高考省份（31 个，与 profile.PROFILE_OPTIONS.provinces 保持一致） */
export type Province = string;

/** 科类：新高考 3+1+2 用物理类/历史类，未改革地区用综合 */
export type Subject = "物理类" | "历史类" | "综合/未改革";

/** 志愿档位：冲 / 稳 / 保 */
export type Level = "冲" | "稳" | "保";

/** 主题标识（与 theme.THEMES[].id 对齐） */
export type ThemeId = "dark" | "light" | "teal";

/** 数据来源口径（演示 / 官方 / 真实抓取 / 估算） */
export type DataSource =
  | "demo"
  | "official"
  | "official_overlay"
  | "official_table"
  | "real"
  | "third_party_text"
  | "estimated"
  | "est"
  | (string & {});

/** 用户全局档案：一次输入，跨页复用 */
export interface Profile {
  province: Province;
  subject: Subject;
  rank: string | number;
  major: string;
}

/** 主题变量映射（--xf-* 自定义属性或 wot 组件变量） */
export interface ThemeVars {
  [key: string]: string;
}

/** 统一的后端响应结构 */
export interface ApiResult<T = unknown> {
  code: number;
  message?: string;
  data?: T;
}

/** 省控线 / 一分一段等年度数据常用的年份键 */
export type Year = number | string;
