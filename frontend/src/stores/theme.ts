// 主题 Store（P2 Pinia 迁移）
import { defineStore } from "pinia";
import { themeState, applyTheme, setTheme } from "@/utils/theme.js";
import type { ThemeId } from "@/types";

export const useThemeStore = defineStore("theme", {
  state: () => ({
    id: themeState.id as ThemeId,
    mode: themeState.mode,
    style: themeState.style,
  }),
  actions: {
    apply(id: ThemeId) {
      applyTheme(id);
      this.id = themeState.id as ThemeId;
      this.mode = themeState.mode;
      this.style = themeState.style;
    },
    set(id: ThemeId) {
      setTheme(id);
    },
  },
});
