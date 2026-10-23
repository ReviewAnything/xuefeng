// 应用级插件：启动时初始化主题（P2 Pinia 迁移）
import { initTheme } from "@/utils/theme";

export default {
  install() {
    // 读取端侧持久化主题并应用到根节点（H5 同步 <html>，小程序写入页面 style）
    initTheme();
  },
};
