<template>
  <wd-config-provider theme="dark" :theme-vars="themeVars">
    <view class="page">
      <view class="hero">
        <text class="h1">志愿表草稿</text>
        <text class="sub">按 冲/稳/保 三档整理，可填写拟报专业后打印或另存为 PDF（全程仅存本机）。</text>
      </view>

      <view v-if="isEmpty" class="section">
        <text class="small">还没有生成志愿表。请先到「院校推荐」页按位次生成 冲/稳/保 院校清单。</text>
        <view class="actions">
          <wd-button type="primary" block @click="goRecommend">去生成院校推荐</wd-button>
        </view>
      </view>

      <view v-if="hasPlan" class="section">
        <view class="meta-card">
          <text class="meta-line">省份：{{ plan.province }} · 科类：{{ plan.subject }}</text>
          <text class="meta-line">位次：{{ plan.user_rank }}<text v-if="plan.major"> · 目标专业：{{ plan.major }}</text></text>
          <text class="meta-line">生成时间：{{ timeLabel }}</text>
        </view>
      </view>

      <view v-if="hasPlan" class="section">
        <view v-for="g in groups" :key="g.level" class="grp">
          <view class="grp-head">
            <text class="grp-title" :class="levelClass(g.level)">{{ g.title }}（{{ g.rows.length }}）</text>
            <text class="grp-sub">门槛位次参考见各行院校层次</text>
          </view>
          <view v-for="(r, i) in g.rows" :key="r.key" class="row">
            <view class="row-left">
              <text class="row-idx">{{ i + 1 }}</text>
              <view class="row-info">
                <text class="row-name">{{ r.name }}</text>
                <text class="row-meta">{{ r.tier }} · {{ r.province }}</text>
              </view>
            </view>
            <input class="row-major" v-model="r.major" placeholder="拟报专业" />
          </view>
          <text v-if="isNoRow(g)" class="small">该档暂无院校，可回到推荐页放宽条件。</text>
        </view>
      </view>

      <view v-if="hasPlan" class="section">
        <view class="actions no-print">
          <!-- #ifdef H5 -->
          <wd-button type="primary" block @click="print">打印 / 另存为 PDF</wd-button>
          <!-- #endif -->
          <wd-button block plain @click="copy">复制为文本</wd-button>
          <wd-button block plain @click="goRecommend">重新生成</wd-button>
        </view>
        <text class="small">打印时会自动隐藏按钮并切换为浅色排版；浏览器「另存为 PDF」即可得到文件。</text>
        <text class="small">本表仅为学习参考：院校池不等于录取承诺，正式填报请以各省考试院与院校招生网为准。</text>
      </view>
    </view>
    <wd-toast></wd-toast>
  </wd-config-provider>
</template>

<script setup>
import { computed, ref } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { useToast } from "wot-design-uni";
import { themeVars } from "@/utils/theme.js";

const toast = useToast();
const plan = ref(null);
const rows = ref([]);

const hasPlan = computed(() => !!plan.value);
const isEmpty = computed(() => !plan.value);

const LEVELS = [
  { key: "冲", title: "冲（够一够）" },
  { key: "稳", title: "稳（大概率）" },
  { key: "保", title: "保（兜底）" },
];

const groups = computed(() => {
  return LEVELS.map((l) => ({
    level: l.key,
    title: l.title,
    rows: rows.value.filter((r) => r.level === l.key),
  }));
});

const timeLabel = computed(() => {
  if (!plan.value || !plan.value.at) return "-";
  const d = new Date(plan.value.at);
  const pad = (n) => (n < 10 ? "0" + n : "" + n);
  return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
    " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
});

onLoad(() => {
  const p = uni.getStorageSync("zhiyuan_plan_v1");
  if (!p) return;
  plan.value = p;
  const list = [];
  (p.tiers || []).forEach((t) => {
    if (t.level === "不可及") return;
    (t.schools || []).forEach((s) => {
      list.push({
        key: t.tier + "-" + s.name,
        level: t.level,
        tier: t.tier,
        name: s.name,
        province: s.province || "",
        major: p.major || "",
      });
    });
  });
  rows.value = list;
});

function levelClass(level) {
  if (level === "冲") return "reach";
  if (level === "稳") return "match";
  return "safe";
}

function isNoRow(g) {
  return g.rows.length === 0;
}

function buildText() {
  const p = plan.value;
  const lines = [];
  lines.push("志愿表草稿（学习参考，非填报依据）");
  lines.push("省份：" + p.province + " | 科类：" + p.subject + " | 位次：" + p.user_rank);
  lines.push("生成时间：" + timeLabel.value);
  lines.push("");
  groups.value.forEach((g) => {
    lines.push("【" + g.title + "】");
    g.rows.forEach((r, i) => {
      lines.push((i + 1) + ". " + r.name + "（" + r.tier + "）  拟报专业：" + (r.major || "（待填）"));
    });
    lines.push("");
  });
  lines.push("说明：院校池来自教育部全国高校名单，未区分具体录取线；请以考试院/院校招生网为准。");
  return lines.join("\n");
}

function copy() {
  const text = buildText();
  uni.setClipboardData({
    data: text,
    success: () => toast.show("已复制志愿表文本"),
  });
}

function goRecommend() {
  const p = plan.value;
  const q = p ? `province=${encodeURIComponent(p.province)}&subject=${encodeURIComponent(p.subject)}&user_rank=${encodeURIComponent(p.user_rank)}` : "";
  uni.navigateTo({ url: q ? "/pages/recommend/recommend?" + q : "/pages/recommend/recommend" });
}

function print() {
  // #ifdef H5
  window.print();
  // #endif
  // #ifndef H5
  toast.show("请在 H5 端使用打印导出");
  // #endif
}
</script>

<style scoped>
.page { padding: 24rpx 24rpx 60rpx; }
.hero { padding: 16rpx 8rpx 24rpx; }
.h1 { font-size: 40rpx; font-weight: 700; color: #ffd24d; }
.sub { display: block; margin-top: 10rpx; font-size: 24rpx; color: #8a909c; line-height: 1.6; }

.section { margin-bottom: 24rpx; }
.small { font-size: 21rpx; color: #6b7280; display: block; margin-top: 10rpx; line-height: 1.6; }
.actions { display: flex; flex-direction: column; gap: 16rpx; margin-top: 18rpx; }

.meta-card { border: 1px solid #22262e; border-radius: 16rpx; padding: 20rpx; }
.meta-line { display: block; font-size: 24rpx; color: #c7ccd4; line-height: 1.8; }

.grp { margin-bottom: 22rpx; }
.grp-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 10rpx; }
.grp-title { font-size: 28rpx; font-weight: 600; }
.grp-title.reach { color: #f0ad4e; }
.grp-title.match { color: #6db3f2; }
.grp-title.safe { color: #5fd87f; }
.grp-sub { font-size: 20rpx; color: #6b7280; }

.row { display: flex; align-items: center; justify-content: space-between; padding: 14rpx 0; border-bottom: 1px solid #1c2027; }
.row-left { display: flex; align-items: center; }
.row-idx { width: 44rpx; font-size: 22rpx; color: #6b7280; }
.row-info { display: flex; flex-direction: column; }
.row-name { font-size: 25rpx; color: #c7ccd4; }
.row-meta { font-size: 20rpx; color: #6b7280; margin-top: 2rpx; }
.row-major { width: 260rpx; font-size: 22rpx; color: #c7ccd4; border: 1px solid #2a2e37; border-radius: 8rpx; padding: 6rpx 12rpx; }

@media print {
  .no-print { display: none; }
  .page { background: #ffffff; }
  .h1, .grp-title, .row-name, .meta-line { color: #111111; }
  .sub, .small, .row-meta, .grp-sub, .row-idx { color: #555555; }
}
</style>
