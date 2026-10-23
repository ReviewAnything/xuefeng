<template>
  <image class="app-icon" :src="src" :style="box" mode="aspectFit"></image>
</template>

<script setup>
// 统一图标出口（P3-A）：easycom 自动注册为 <app-icon>，无需 import。
// 之所以内部用 <image> 而不是内联 <svg>：小程序端不支持模板里直接写 svg 标签，
// data URI 交给 image 是唯一 H5/小程序/App 三端都稳的渲染方式。
import { computed } from "vue";
import { iconSrc } from "@/utils/icons";

const props = defineProps({
  name: { type: String, required: true },
  color: { type: String, default: "#e6e8ec" },
  size: { type: [Number, String], default: 34 },
  width: { type: [Number, String], default: 1.7 },
  opacity: { type: [Number, String], default: 1 },
});

const src = computed(() => iconSrc(props.name, props.color, Number(props.width) || 1.7));
const box = computed(() => {
  const s = typeof props.size === "number" ? props.size + "rpx" : props.size;
  return { width: s, height: s, opacity: props.opacity };
});
</script>

<style scoped>
.app-icon {
  display: inline-block;
  vertical-align: middle;
  flex: 0 0 auto;
}
</style>
