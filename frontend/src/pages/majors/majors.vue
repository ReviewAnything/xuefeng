<template>
  <wd-config-provider theme="dark" :theme-vars="themeVars">
    <view class="page">
      <view class="hero">
        <text class="h1">专业图谱库</text>
        <text class="sub">每个专业含：定性观点 + 理由 + 偏见校正层 + 数据核验入口。</text>
      </view>

      <wd-search v-model="kw" placeholder="搜索专业名 / 标签，如：电气、天坑、考公" hide-cancel />

      <scroll-view class="filters" scroll-x="true">
        <view class="chips">
          <wd-tag v-for="c in cats" :key="c" :type="cur === c ? 'primary' : 'default'"
                  :plain="cur !== c" round @click="setCat(c)">{{ c }}</wd-tag>
        </view>
      </scroll-view>

      <view class="count">共 {{ list.length }} 个专业</view>

      <view class="grid">
        <view v-for="m in list" :key="m.name" class="mcard" :class="'view-' + m.view">
          <view class="mhead">
            <text class="mname">{{ m.name }}</text>
            <wd-tag :type="tagType(m.view)" plain>{{ vlabel(m.view) }}</wd-tag>
          </view>
          <text class="mcat">{{ m.cat }}</text>
          <view class="mbody">
            <text class="k">定性观点：</text>
            <text class="t">{{ m.reason }}</text>
          </view>
          <view class="tags">
            <wd-tag v-for="t in m.tags" :key="t" type="default" plain>{{ t }}</wd-tag>
          </view>
          <view class="bias">
            <text class="k">⚖ 偏见校正：</text>
            <text class="t">{{ m.bias }}</text>
          </view>
          <view class="src">
            <text class="src-y">{{ m.source_year }} 年整理</text>
            <text class="src-n">{{ m.source_note }}</text>
          </view>
          <view class="verify" @click="copyVerify(m.verify)">
            <text>🔗 核验口径：{{ shortVerify(m.verify) }}</text>
            <text class="copy">复制</text>
          </view>
        </view>
      </view>

      <view v-if="!list.length" class="empty">没有匹配的专业，试试其他关键词。</view>
    </view>
    <wd-toast />
  </wd-config-provider>
</template>

<script setup>
import { ref, computed } from "vue";
import { useToast } from "wot-design-uni";
import { MAJORS, CATS, VIEW_LABEL } from "@/utils/content.js";
import { themeVars } from "@/utils/theme.js";

const toast = useToast();
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
function tagType(v) { return { recommend: "success", caution: "warning", avoid: "danger" }[v] || "default"; }
function shortVerify(s) { return s.length > 32 ? s.slice(0, 32) + "…" : s; }
function copyVerify(s) {
  uni.setClipboardData({
    data: s,
    success: () => toast.show("核验口径已复制"),
  });
}
</script>

<style scoped>
.page { padding: 24rpx 24rpx 60rpx; }
.hero { padding: 16rpx 8rpx 20rpx; }
.h1 { font-size: 40rpx; font-weight: 700; color: #ffd24d; }
.sub { display: block; margin-top: 10rpx; font-size: 24rpx; color: #8a909c; line-height: 1.6; }

.filters { white-space: nowrap; margin: 18rpx 0 10rpx; }
.chips { display: inline-flex; gap: 12rpx; padding: 2rpx 2rpx 6rpx; }
.count { font-size: 21rpx; color: #6b7280; margin-bottom: 14rpx; }

.grid { display: flex; flex-direction: column; gap: 20rpx; }
.mcard { background: #16191f; border: 1px solid #23262e; border-left: 6rpx solid #2a2e37; border-radius: 16rpx; padding: 22rpx; }
.mcard.view-recommend { border-left-color: #5fd87f; }
.mcard.view-caution { border-left-color: #f0ad4e; }
.mcard.view-avoid { border-left-color: #ff6b6b; }
.mhead { display: flex; justify-content: space-between; align-items: center; gap: 12rpx; }
.mname { font-size: 30rpx; font-weight: 600; color: #e6e8ec; }
.mcat { font-size: 21rpx; color: #6b7280; display: block; margin: 6rpx 0 12rpx; }
.mbody { font-size: 24rpx; color: #c7ccd4; line-height: 1.7; }
.k { color: #ffd24d; }
.t { color: #c7ccd4; }
.tags { display: flex; flex-wrap: wrap; gap: 10rpx; margin: 12rpx 0; }
.bias { font-size: 23rpx; color: #9aa0aa; line-height: 1.7; background: #1c1f26; border-radius: 10rpx; padding: 14rpx; margin-top: 8rpx; }
.src { display: flex; align-items: baseline; gap: 10rpx; margin-top: 12rpx; font-size: 20rpx; line-height: 1.6; }
.src-y { flex: 0 0 auto; color: #6db3f2; border: 1px solid #233042; border-radius: 6rpx; padding: 2rpx 8rpx; }
.src-n { flex: 1; color: #6b7280; }
.verify { display: flex; align-items: center; justify-content: space-between; gap: 12rpx; margin-top: 14rpx; padding-top: 12rpx; border-top: 1px dashed #2a2e37; }
.verify text { font-size: 21rpx; color: #6db3f2; }
.verify .copy { color: #ffd24d; flex: 0 0 auto; }
.empty { text-align: center; color: #6b7280; font-size: 26rpx; padding: 60rpx 0; }
</style>
