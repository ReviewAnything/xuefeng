<template>
  <wd-config-provider theme="dark" :theme-vars="themeVars">
    <view class="page">
      <view class="hero">
        <text class="h1">开源资源中心</text>
        <text class="sub">与志愿决策 / 升学规划相关的开源项目，均提供进入入口。</text>
      </view>

      <scroll-view class="filters" scroll-x="true">
        <view class="chips">
          <wd-tag v-for="r in resCats" :key="r.key" :type="cur === r.key ? 'primary' : 'default'"
                  :plain="cur !== r.key" round @click="cur = r.key">{{ r.label }}</wd-tag>
        </view>
      </scroll-view>

      <view class="grid">
        <view v-for="item in list" :key="item.name" class="res">
          <view class="top">
            <text class="name">{{ item.name }}</text>
            <wd-tag type="default" plain>{{ item.lic }}</wd-tag>
          </view>
          <text class="meta">{{ item.meta }}</text>
          <text class="desc">{{ item.desc }}</text>
          <view class="acts">
            <wd-button v-for="l in item.links" :key="l.u" size="small"
                       :type="l.t.includes('GitHub') ? 'primary' : 'default'"
                       :plain="!l.t.includes('GitHub')" @click="open(l.u)">
              {{ l.t }} ↗
            </wd-button>
          </view>
        </view>
      </view>
    </view>
    <wd-toast />
  </wd-config-provider>
</template>

<script setup>
import { ref, computed } from "vue";
import { useToast } from "wot-design-uni";
import { RESOURCES, RES_CATS } from "@/utils/content.js";
import { themeVars } from "@/utils/theme.js";

const toast = useToast();
const resCats = RES_CATS;
const cur = ref("all");
const list = computed(() => RESOURCES.filter((r) => cur.value === "all" || r.cat === cur.value));

function open(u) {
  // H5 直接打开；小程序端复制链接
  // #ifdef H5
  window.open(u, "_blank");
  // #endif
  // #ifndef H5
  uni.setClipboardData({ data: u, success: () => toast.show("链接已复制，请在浏览器打开") });
  // #endif
}
</script>

<style scoped>
.page { padding: 24rpx 24rpx 60rpx; }
.hero { padding: 16rpx 8rpx 20rpx; }
.h1 { font-size: 40rpx; font-weight: 700; color: #ffd24d; }
.sub { display: block; margin-top: 10rpx; font-size: 24rpx; color: #8a909c; line-height: 1.6; }

.filters { white-space: nowrap; margin: 18rpx 0 14rpx; }
.chips { display: inline-flex; gap: 12rpx; padding: 2rpx 2rpx 6rpx; }

.grid { display: flex; flex-direction: column; gap: 20rpx; }
.res { background: #16191f; border: 1px solid #23262e; border-radius: 16rpx; padding: 22rpx; }
.top { display: flex; justify-content: space-between; align-items: center; gap: 12rpx; }
.name { font-size: 27rpx; font-weight: 600; color: #e6e8ec; }
.meta { display: block; font-size: 21rpx; color: #6b7280; margin-top: 8rpx; }
.desc { font-size: 23rpx; color: #9aa0aa; line-height: 1.7; display: block; margin: 12rpx 0 16rpx; }
.acts { display: flex; flex-wrap: wrap; gap: 12rpx; }
</style>
