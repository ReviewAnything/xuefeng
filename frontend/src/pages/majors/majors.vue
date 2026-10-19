<template>
  <view class="page">
    <view class="hero">
      <text class="h1">专业图谱库</text>
      <text class="sub">每个专业含：张雪峰观点 + 理由 + 偏见校正层 + 数据核验入口。</text>
    </view>

    <scroll-view class="filters" scroll-x="true">
      <text v-for="c in cats" :key="c" class="chip" :class="{ active: cur === c }" @click="setCat(c)">{{ c }}</text>
    </scroll-view>
    <input class="search" v-model="kw" placeholder="搜索专业名 / 标签，如：电气、天坑、考公" />

    <view class="grid">
      <view v-for="m in list" :key="m.name" class="mcard" :class="'view-' + m.view">
        <view class="mhead">
          <text class="mname">{{ m.name }}</text>
          <text class="vbadge" :class="m.view">{{ vlabel(m.view) }}</text>
        </view>
        <text class="mcat">{{ m.cat }}</text>
        <view class="mbody">
          <text class="k">张雪峰视角：</text>
          <text class="t">{{ m.reason }}</text>
        </view>
        <view class="tags">
          <text v-for="t in m.tags" :key="t" class="tagx">{{ t }}</text>
        </view>
        <view class="bias">
          <text class="k">⚖ 偏见校正：</text>
          <text class="t">{{ m.bias }}</text>
        </view>
        <text class="verify" @click="copyVerify(m.verify)">🔗 核验：{{ shortVerify(m.verify) }}</text>
      </view>
    </view>
    <view v-if="!list.length" class="empty">没有匹配的专业。</view>
  </view>
</template>

<script setup>
import { ref, computed } from "vue";
import { MAJORS, CATS, VIEW_LABEL } from "@/utils/content.js";

const cats = ["全部", ...CATS];
const cur = ref("全部");
const kw = ref("");

const list = computed(() =>
  MAJORS.filter(
    (m) =>
      (cur.value === "全部" || m.cat === cur.value) &&
      (!kw.value || (m.name + m.tags.join("") + m.reason).includes(kw.value))
  )
);

function setCat(c) { cur.value = c; }
function vlabel(v) { return VIEW_LABEL[v]; }
function shortVerify(s) { return s.length > 36 ? s.slice(0, 36) + "…" : s; }
function copyVerify(s) {
  uni.setClipboardData({ data: s });
}
</script>

<style scoped>
.page { padding: 24rpx 24rpx 60rpx; }
.hero { padding: 16rpx 8rpx 18rpx; }
.h1 { font-size: 40rpx; font-weight: 700; color: #ffd24d; }
.sub { display: block; margin-top: 10rpx; font-size: 24rpx; color: #8a909c; line-height: 1.6; }
.filters { white-space: nowrap; margin-bottom: 16rpx; }
.chip { display: inline-block; font-size: 24rpx; padding: 10rpx 24rpx; border-radius: 999rpx; background: #16191f; color: #c7ccd4; margin-right: 12rpx; border: 1px solid #23262e; }
.chip.active { background: #ffd24d; color: #1a1a1a; font-weight: 600; }
.search { background: #16191f; border: 1px solid #23262e; border-radius: 12rpx; padding: 18rpx 20rpx; font-size: 26rpx; color: #e6e8ec; margin-bottom: 20rpx; }
.grid { display: flex; flex-direction: column; gap: 20rpx; }
.mcard { background: #16191f; border: 1px solid #23262e; border-left: 6rpx solid #2a2e37; border-radius: 16rpx; padding: 22rpx; }
.mcard.view-recommend { border-left-color: #5fd87f; }
.mcard.view-caution { border-left-color: #f0ad4e; }
.mcard.view-avoid { border-left-color: #ff6b6b; }
.mhead { display: flex; justify-content: space-between; align-items: center; }
.mname { font-size: 30rpx; font-weight: 600; color: #e6e8ec; }
.vbadge { font-size: 22rpx; padding: 4rpx 14rpx; border-radius: 999rpx; }
.vbadge.recommend { background: #16361f; color: #5fd87f; }
.vbadge.caution { background: #3a2f12; color: #f0ad4e; }
.vbadge.avoid { background: #3a1a1a; color: #ff6b6b; }
.mcat { font-size: 21rpx; color: #6b7280; display: block; margin: 4rpx 0 10rpx; }
.mbody { font-size: 24rpx; color: #c7ccd4; line-height: 1.6; }
.k { color: #ffd24d; }
.t { color: #c7ccd4; }
.tags { display: flex; flex-wrap: wrap; gap: 10rpx; margin: 12rpx 0; }
.tagx { font-size: 21rpx; padding: 4rpx 14rpx; border-radius: 999rpx; background: #23262e; color: #c7ccd4; }
.bias { font-size: 23rpx; color: #9aa0aa; line-height: 1.6; background: #1c1f26; border-radius: 10rpx; padding: 12rpx; margin-top: 8rpx; }
.verify { font-size: 21rpx; color: #6db3f2; display: block; margin-top: 10rpx; }
.empty { text-align: center; color: #6b7280; font-size: 26rpx; padding: 60rpx 0; }
</style>
