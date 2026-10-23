// 组合式函数：主题（P3 目录重构，对齐伯乐 composables/）
import { themeState, applyTheme, initTheme, setTheme } from "@/utils/theme";
import type { ThemeId } from "@/types";

export function useTheme() {
  return { themeState, applyTheme, initTheme, setTheme };
}
