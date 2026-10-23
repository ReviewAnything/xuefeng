<template>
  <view class="wv-page">
    <web-view v-if="src" :src="src"></web-view>
    <view v-else class="wv-empty">
      <text class="wv-t">未提供可打开的链接</text>
    </view>
  </view>
</template>

<script setup>
import { ref } from "vue";
import { onLoad } from "@dcloudio/uni-app";

const src = ref("");
onLoad((q) => {
  if (q && q.src) {
    try {
      src.value = decodeURIComponent(q.src);
    } catch (e) {
      src.value = q.src;
    }
  }
});
</script>

<style scoped>
.wv-page { width: 100%; height: 100vh; }
.wv-empty { display: flex; align-items: center; justify-content: center; height: 100vh; }
.wv-t { color: #8a909c; font-size: 26rpx; }
</style>
