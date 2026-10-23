<script>
// 应用启动：静默探测后端可用性（不弹窗、不打断），结果存端侧供各页判断是否提示「演示模式」。
import { api } from "@/utils/api.js";
import { initTheme } from "@/utils/theme";
export default {
  onLaunch() {
    // 在页面渲染前把主题变量铺到 <html>，避免明暗切换首帧闪烁
    initTheme();
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
/* ===========================================================================
   全局视觉层（P3-A）
   ---------------------------------------------------------------------------
   这里的样式是**全局**的（App.vue 的 style 不带 scoped），因此：
     · 只放令牌与可复用工具类（.xf-*），不放任何单页布局；
     · 单页仍用自己的 scoped style 做布局，视觉值一律取自这里的变量。
   变量定义在 page 上（H5 会映射到 uni-page-body，小程序同样支持自定义属性），
   子节点全部继承，所以页面里写 var(--xf-gold) 即可，不必再硬编码色值。
   =========================================================================== */
/* 变量挂 :root（H5 编译成 <html>，小程序即页面根节点）。
   运行时主题切换会把 --xf-* 写到 <html>/config-provider 根，覆盖这里的默认值，
   所以这里只留「暗夜金」作为首屏与无 JS 时的兜底。 */
:root {
  /* 面 */
  --xf-bg: #0f1115;
  --xf-surface: #16191f;
  --xf-surface-2: #1c2026;
  --xf-surface-3: #23262e;
  --xf-line: #23262e;
  --xf-line-soft: #1c2027;
  /* 字（4 级，最暗一级仍保证可读） */
  --xf-text: #e9ebef;
  --xf-text-2: #c2c8d0;
  --xf-text-3: #8f96a2;
  --xf-text-4: #6f7683;
  /* 品牌与语义 */
  --xf-gold: #ffd24d;
  --xf-gold-dim: #c9a53a;
  --xf-reach: #f0ad4e;
  --xf-match: #6db3f2;
  --xf-safe: #5fd87f;
  --xf-danger: #e5484d;
  --xf-danger-text: #ff8787;
  /* 数据可信度 */
  --xf-official: #5fd87f;
  --xf-real: #6db3f2;
  --xf-est: #9aa0aa;
  --xf-demo: #f0ad4e;
  /* 主题相关（随主题切换覆盖） */
  --xf-fill: rgba(255, 255, 255, 0.05);
  --xf-shimmer-1: #1a1e25;
  --xf-shimmer-2: #232833;
  /* 圆角 / 动效 */
  --xf-r-sm: 10rpx;
  --xf-r-md: 16rpx;
  --xf-r-lg: 22rpx;
  --xf-r-pill: 999rpx;
  --xf-ease: cubic-bezier(0.22, 0.61, 0.36, 1);
}

page {
  background: var(--xf-bg);
  color: var(--xf-text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Microsoft YaHei", sans-serif;
  -webkit-font-smoothing: antialiased;
}

view, text, input, textarea, picker, scroll-view {
  box-sizing: border-box;
}

/* ---- 版心与标题 ---- */
.xf-page { padding: 28rpx 28rpx 80rpx; min-height: 100vh; background: var(--xf-bg); }
.xf-hero { padding: 20rpx 4rpx 24rpx; display: flex; align-items: flex-start; gap: 18rpx; }
.xf-hero-body { flex: 1; min-width: 0; }
.xf-h1 { display: block; font-size: 44rpx; font-weight: 700; color: var(--xf-text); letter-spacing: 1rpx; line-height: 1.35; }
.xf-h2 { display: block; font-size: 34rpx; font-weight: 700; color: var(--xf-text); line-height: 1.4; }
.xf-h3 { display: block; font-size: 28rpx; font-weight: 600; color: var(--xf-text); line-height: 1.4; }
.xf-sub { display: block; margin-top: 10rpx; font-size: 24rpx; color: var(--xf-text-3); line-height: 1.65; }
.xf-tiny { display: block; font-size: 22rpx; color: var(--xf-text-3); line-height: 1.7; }
.xf-micro { display: block; font-size: 20rpx; color: var(--xf-text-4); line-height: 1.7; }

/* ---- 卡片 ---- */
.xf-card {
  background: var(--xf-surface);
  border: 1rpx solid var(--xf-line);
  border-radius: var(--xf-r-md);
  padding: 22rpx;
}
.xf-card + .xf-card { margin-top: 18rpx; }
/* 左侧语义色条：冲/稳/保/危险一眼可分，不靠读文字 */
.xf-strip { border-left: 6rpx solid var(--xf-line); border-radius: 0 var(--xf-r-md) var(--xf-r-md) 0; }
.xf-strip--reach { border-left-color: var(--xf-reach); }
.xf-strip--match { border-left-color: var(--xf-match); }
.xf-strip--safe { border-left-color: var(--xf-safe); }
.xf-strip--danger { border-left-color: var(--xf-danger); }
.xf-strip--gold { border-left-color: var(--xf-gold); }

/* ---- 芯片/徽章 ---- */
.xf-chip {
  display: inline-flex; align-items: center; gap: 8rpx;
  padding: 5rpx 14rpx; border-radius: var(--xf-r-pill);
  font-size: 21rpx; line-height: 1.3;
  border: 1rpx solid var(--xf-line);
  color: var(--xf-text-3); background: var(--xf-fill);
}
.xf-chip--official { color: var(--xf-official); border-color: rgba(95, 216, 127, 0.38); background: rgba(95, 216, 127, 0.08); }
.xf-chip--real { color: var(--xf-real); border-color: rgba(109, 179, 242, 0.38); background: rgba(109, 179, 242, 0.08); }
.xf-chip--est { color: var(--xf-est); border-color: rgba(154, 160, 170, 0.3); background: rgba(154, 160, 170, 0.07); }
.xf-chip--demo { color: var(--xf-demo); border-color: rgba(240, 173, 78, 0.4); background: rgba(240, 173, 78, 0.1); }
.xf-chip--reach { color: var(--xf-reach); border-color: rgba(240, 173, 78, 0.35); }
.xf-chip--match { color: var(--xf-match); border-color: rgba(109, 179, 242, 0.35); }
.xf-chip--safe { color: var(--xf-safe); border-color: rgba(95, 216, 127, 0.35); }

/* ---- 动作行（替代一屏三四个等权按钮：主次分明，且能带图标）---- */
.xf-action {
  display: flex; align-items: center; gap: 18rpx;
  padding: 22rpx 20rpx; min-height: 96rpx;
  background: var(--xf-surface); border: 1rpx solid var(--xf-line);
  border-radius: var(--xf-r-md);
  transition: transform var(--xf-ease) 140ms, border-color var(--xf-ease) 140ms;
}
.xf-action:active { transform: scale(0.985); border-color: var(--xf-gold-dim); }
.xf-action--primary { background: linear-gradient(135deg, rgba(255, 210, 77, 0.16), rgba(255, 210, 77, 0.04)); border-color: rgba(255, 210, 77, 0.42); }
.xf-action-label { flex: 1; min-width: 0; }
.xf-action-title { display: block; font-size: 27rpx; font-weight: 600; color: var(--xf-text); }
.xf-action-desc { display: block; margin-top: 4rpx; font-size: 21rpx; color: var(--xf-text-3); line-height: 1.5; }
/* 图标底座：让线条图标有落点，不飘在文字旁 */
.xf-tile {
  flex: 0 0 auto; width: 64rpx; height: 64rpx; border-radius: 18rpx;
  display: flex; align-items: center; justify-content: center;
  background: var(--xf-fill); border: 1rpx solid var(--xf-line);
}
.xf-tile--gold { background: rgba(255, 210, 77, 0.12); border-color: rgba(255, 210, 77, 0.3); }
.xf-tile--reach { background: rgba(240, 173, 78, 0.12); border-color: rgba(240, 173, 78, 0.28); }
.xf-tile--match { background: rgba(109, 179, 242, 0.12); border-color: rgba(109, 179, 242, 0.28); }
.xf-tile--safe { background: rgba(95, 216, 127, 0.12); border-color: rgba(95, 216, 127, 0.28); }
.xf-tile--danger { background: rgba(229, 72, 77, 0.14); border-color: rgba(229, 72, 77, 0.36); }

/* ---- 空状态：永远给「下一步做什么」，而不是一句「暂无数据」---- */
.xf-empty { padding: 56rpx 24rpx; text-align: center; }
.xf-empty-title { display: block; font-size: 27rpx; font-weight: 600; color: var(--xf-text-2); }
.xf-empty-desc { display: block; margin-top: 10rpx; font-size: 22rpx; color: var(--xf-text-3); line-height: 1.7; }

/* ---- 骨架屏：替代白屏 loading ---- */
.xf-skel {
  background: linear-gradient(100deg, var(--xf-shimmer-1) 20%, var(--xf-shimmer-2) 38%, var(--xf-shimmer-1) 56%);
  background-size: 260% 100%;
  border-radius: 10rpx;
  animation: xf-shimmer 1.25s ease-in-out infinite;
}
.xf-skel-line { height: 24rpx; margin-bottom: 14rpx; }
.xf-skel-line--w70 { width: 70%; }
.xf-skel-line--w40 { width: 40%; }
@keyframes xf-shimmer {
  0% { background-position: 130% 0; }
  100% { background-position: -30% 0; }
}

/* ---- 入场动效：只做轻微上浮，不做花哨位移 ---- */
.xf-fade { animation: xf-rise 260ms var(--xf-ease) both; }
@keyframes xf-rise {
  from { opacity: 0; transform: translateY(10rpx); }
  to { opacity: 1; transform: translateY(0); }
}

.xf-divider { height: 1rpx; background: var(--xf-line-soft); margin: 20rpx 0; }

/* 尊重系统「减弱动态效果」：动效全部退化为静态 */
@media (prefers-reduced-motion: reduce) {
  .xf-fade, .xf-skel { animation: none; }
  .xf-action { transition: none; }
}
</style>
