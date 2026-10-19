<script>
export default {
  onLaunch() {
    // 应用启动：可在端侧做本地存储迁移等
    console.log("志愿决策助手 v2 启动");
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
