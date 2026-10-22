import { createSSRApp } from "vue";
import App from "./App.vue";
import { themeState } from "./utils/theme.js";
export function createApp() {
  const app = createSSRApp(App);
  // 让所有页面模板可直接用 $theme.mode / $theme.style 绑定主题，无需逐页 import
  app.config.globalProperties.$theme = themeState;
  return { app };
}
