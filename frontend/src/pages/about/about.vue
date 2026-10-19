<template>
  <view class="page">
    <view class="hero">
      <text class="h1">关于与本应用</text>
      <text class="sub">v{{ version }} · 数据日期 {{ date }} · uni-app 跨端 + Python 后端</text>
    </view>

    <view class="card">
      <text class="h3">这是什么</text>
      <text class="p">一个把张雪峰「普通家庭+就业导向」的务实框架，与开源社区资源结合的<b>志愿决策助手</b>。它输出决策框架而非录取结论，并内置偏见校正层。</text>
    </view>

    <view class="card">
      <text class="h3">架构（v2 重构）</text>
      <view class="arch">
        <text class="row">· 前端：uni-app(Vue3) —— H5 / 微信小程序 / App 一套代码</text>
        <text class="row">· 后端：Python FastAPI —— P2 数据层（录取位次 / 冲稳保 / 观点×数据核验）</text>
        <text class="row">· 数据源：shared/content.json —— 前后端共用单一内容源</text>
        <text class="row">· 数据可插拔：放入真实 gaokao-advisor CSV 自动切换</text>
      </view>
    </view>

    <view class="card">
      <text class="h3">五个方向如何落地</text>
      <view class="arch">
        <text class="row">① 决策辅助而非答案：灵魂八连问 → 框架画布，不下定论</text>
        <text class="row">② 定性×定量：专业图谱观点 → 后端真实录取数据核验</text>
        <text class="row">③ 偏见校正：每个专业都带反方/长期/官方评估提示</text>
        <text class="row">④ 本地隐私：输入仅存端侧存储，可导出，无强制上云</text>
        <text class="row">⑤ 动态更新：内容集中在 content.json，年度刷新只改数据层</text>
      </view>
    </view>

    <view class="card warn">
      <text class="h3">免责声明</text>
      <text class="p">本应用由 AI 基于公开资料与开源社区内容整理，<b>仅供学习参考，不构成正式升学/志愿填报建议</b>。实际填报请以各省教育考试院官方数据为准。收录的开源项目多为社区自发纪念与二次创作，与商业主体无关联。内置录取数据为参数化样例（演示用），非官方录取数据。</text>
    </view>
  </view>
</template>

<script setup>
import { APP_VERSION, DATA_DATE } from "@/utils/content.js";
const version = APP_VERSION;
const date = DATA_DATE;
</script>

<style scoped>
.page { padding: 24rpx 24rpx 60rpx; }
.hero { padding: 16rpx 8rpx 18rpx; }
.h1 { font-size: 40rpx; font-weight: 700; color: #ffd24d; }
.sub { display: block; margin-top: 10rpx; font-size: 24rpx; color: #8a909c; line-height: 1.6; }
.card { background: #16191f; border: 1px solid #23262e; border-radius: 20rpx; padding: 26rpx; margin-bottom: 24rpx; }
.card.warn { border-color: #5a4a1a; }
.h3 { font-size: 30rpx; font-weight: 600; color: #e6e8ec; display: block; margin-bottom: 14rpx; }
.p { font-size: 24rpx; color: #c7ccd4; line-height: 1.7; }
.arch { display: flex; flex-direction: column; gap: 8rpx; }
.row { font-size: 24rpx; color: #c7ccd4; line-height: 1.7; }
</style>
