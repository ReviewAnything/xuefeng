<script>
// 应用启动：静默探测后端可用性（不弹窗、不打断），结果存端侧供各页判断是否提示「演示模式」。
import { api } from "@/utils/api.js";
export default {
  onLaunch() {
    if (api.isDemo()) {
      try { uni.setStorageSync("zhiyuan_backend_ok", false); } catch (e) {}
      return;
    }
    api.health()
      .then(() => { try { uni.setStorageSync("zhiyuan_backend_ok", true); } catch (e) {} })
      .catch(() => { try { uni.setStorageSync("zhiyuan_backend_ok", false); } catch (e) {} });
  },
};
</script>

<style>
/* 全局基础样式（深色主题，跨端通用） */
page {
  background: #0f1115;
  color: #e6e8ec;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Microsoft YaHei", sans-serif;
}
view, text, input, textarea, picker, scroll-view {
  box-sizing: border-box;
}
</style>
