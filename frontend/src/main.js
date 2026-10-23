import { createSSRApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import themePlugin from "./plugins/theme";
import { themeState } from "./utils/theme.js";

export function createApp() {
  const app = createSSRApp(App);
  // P2：安装 Pinia，各页面可通过 useXxxStore() 访问响应式状态
  app.use(createPinia());
  // 启动时按端侧持久化初始化主题
  app.use(themePlugin);
  // 兼容保留：页面模板仍可用 $theme 直接绑定 mode/style
  app.config.globalProperties.$theme = themeState;
  return { app };
}
