// 全局常量（P3 目录重构，对齐伯乐 constants/）
// ---------------------------------------------------------------------------
// 从 utils/profile 平滑迁移而来：profile.js 保留重导出以兼容既有 `@/utils/profile` 引用。
import type { Province, Subject, ThemeId } from "@/types";

/** 省份与科类选项（与后端省份口径一致，共 31 省） */
export const PROFILE_OPTIONS = {
  provinces: [
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西",
    "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
  ] as Province[],
  subjects: ["物理类", "历史类", "综合/未改革"] as Subject[],
};

/** 可选主题标识（与 theme.THEMES[].id 对齐） */
export const THEME_IDS = ["dark", "light", "teal"] as const;
export type ThemeIdType = ThemeId;
export const DEFAULT_THEME: ThemeId = "dark";
