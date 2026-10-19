<template>
  <view class="page">
    <view class="hero">
      <text class="h1">开源资源中心</text>
      <text class="sub">与张雪峰思想 / 高考志愿相关的开源项目，均提供进入入口。</text>
    </view>

    <scroll-view class="filters" scroll-x="true">
      <text v-for="r in resCats" :key="r.key" class="chip" :class="{ active: cur === r.key }" @click="cur = r.key">{{ r.label }}</text>
    </scroll-view>

    <view class="grid">
      <view v-for="item in list" :key="item.name" class="res">
        <view class="top">
          <text class="name">{{ item.name }}</text>
          <text class="meta">{{ item.meta }} · {{ item.lic }}</text>
        </view>
        <text class="desc">{{ item.desc }}</text>
        <view class="acts">
          <text v-for="l in item.links" :key="l.u" class="act" :class="{ primary: l.t.includes('GitHub') }" @click="open(l.u)">{{ l.t }} ↗</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref, computed } from "vue";
import { RESOURCES, RES_CATS } from "@/utils/content.js";

const resCats = RES_CATS;
const cur = ref("all");
const list = computed(() => RESOURCES.filter((r) => cur.value === "all" || r.cat === cur.value));

function open(u) {
  // H5 直接打开；小程序端复制链接
  // #ifdef H5
  window.open(u, "_blank");
  // #endif
  // #ifndef H5
  uni.setClipboardData({ data: u });
  // #endif
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
.grid { display: flex; flex-direction: column; gap: 20rpx; }
.res { background: #16191f; border: 1px solid #23262e; border-radius: 16rpx; padding: 22rpx; }
.top { display: flex; justify-content: space-between; align-items: baseline; }
.name { font-size: 27rpx; font-weight: 600; color: #e6e8ec; }
.meta { font-size: 21rpx; color: #6b7280; }
.desc { font-size: 23rpx; color: #9aa0aa; line-height: 1.6; display: block; margin: 10rpx 0 14rpx; }
.acts { display: flex; flex-wrap: wrap; gap: 12rpx; }
.act { font-size: 22rpx; padding: 8rpx 18rpx; border-radius: 10rpx; background: #23262e; color: #c7ccd4; }
.act.primary { background: #1c2a3a; color: #6db3f2; }
</style>
