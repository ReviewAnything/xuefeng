<template>
  <wd-config-provider :theme="$theme.mode" :theme-vars="themeVars" :custom-style="$theme.style">
    <view class="page">
      <view class="xf-hero">
        <view class="xf-tile xf-tile--gold">
          <app-icon name="calendar" color="#ffd24d" :size="36"></app-icon>
        </view>
        <view class="xf-hero-body">
          <text class="xf-h1">历年省控线</text>
          <text class="xf-sub">2022–2026 官方录取控制分数线，可逐年溯源。省控线只给批次门槛，不含位次。</text>
        </view>
      </view>

      <!-- 年份时间轴：五年一条线，点哪年看哪年 -->
      <view class="tl-wrap">
        <view class="tl-line"></view>
        <view class="tl">
          <view v-for="y in years" :key="y" class="tl-item" :class="{ on: year === y }" @click="setYear(y)">
            <text class="tl-y" :class="{ on: year === y }">{{ y }}</text>
            <view class="tl-dot" :class="{ on: year === y }"></view>
            <text class="tl-tag">{{ y === latestYear ? "最新" : "" }}</text>
          </view>
        </view>
      </view>

      <!-- 模式 -->
      <view class="seg sm">
        <view class="seg-item" :class="{ on: mode === 'single' }" @click="setMode('single')">
          <app-icon name="school" :color="mode === 'single' ? '#ffd24d' : '#8f96a2'" :size="26"></app-icon>
          <text class="seg-text">单省明细</text>
        </view>
        <view class="seg-item" :class="{ on: mode === 'cross' }" @click="setMode('cross')">
          <app-icon name="chart" :color="mode === 'cross' ? '#ffd24d' : '#8f96a2'" :size="26"></app-icon>
          <text class="seg-text">跨省对比</text>
        </view>
      </view>

      <view v-if="err" class="err">
        <app-icon name="alert" color="#ff8787" :size="26"></app-icon>
        <text class="err-t">{{ err }}</text>
      </view>

      <!-- 单省明细 -->
      <block v-if="mode === 'single' && provData">
        <scroll-view class="filters" scroll-x="true">
          <view class="chips">
            <view v-for="p in provinces" :key="p" class="chip" :class="{ on: p === province }" @click="setProvince(p)">{{ p }}</view>
          </view>
        </scroll-view>

        <view v-if="subjectKeys.length === 0" class="xf-card">
          <view class="xf-empty">
            <app-icon name="info" color="#4b515b" :size="56"></app-icon>
            <text class="xf-empty-title">该年暂无 {{ province }} 的省控线</text>
            <text class="xf-empty-desc">换一个年份或省份看看；其余年份仍有数据。</text>
          </view>
        </view>

        <view v-for="subj in subjectKeys" :key="subj" class="xf-card panel">
          <view class="panel-head">
            <text class="panel-h">{{ subj }}</text>
            <text class="panel-y">{{ year }} 年</text>
          </view>

          <view v-for="tier in tiersOf(subj)" :key="tier" class="tier-row">
            <view class="tier-main">
              <view class="tier-left">
                <text class="tier-name">{{ lineOf(subj, tier) || tier }}</text>
                <text class="tier-sub">{{ tier }}</text>
              </view>
              <view class="tier-right">
                <text class="tier-score">{{ scoreOf(subj, tier) }}</text>
                <text class="tier-unit" v-if="scoreOf(subj, tier) !== '—'">分</text>
              </view>
            </view>

            <!-- 五年走势：当前年高亮，另给区间与同比 -->
            <view class="trend">
              <view v-for="pt in trendBars(subj, tier)" :key="pt.year" class="tbar-col">
                <text class="tbar-v" :class="{ on: pt.year === year }">{{ pt.score }}</text>
                <view class="tbar" :class="{ on: pt.year === year }" :style="{ height: pt.h + 'rpx' }"></view>
                <text class="tbar-y" :class="{ on: pt.year === year }">{{ pt.year }}</text>
              </view>
            </view>

            <view class="tier-foot">
              <text class="tier-range">五年区间 {{ rangeText(subj, tier) }}</text>
              <text :class="['tier-delta', deltaCls(subj, tier)]">{{ deltaText(subj, tier) }}</text>
            </view>
          </view>
        </view>

        <view v-if="sourceUrl" class="source-row" @click="open(sourceUrl)">
          <app-icon name="external" color="#6db3f2" :size="26"></app-icon>
          <text class="source-t">{{ year }} 年官方来源（阳光高考）</text>
          <app-icon name="chevron-right" color="#6f7683" :size="24"></app-icon>
        </view>
      </block>

      <!-- 跨省对比 -->
      <block v-if="mode === 'cross' && crossAll">
        <view v-if="subjectOptions.length" class="filter-row">
          <text class="filter-k">科类</text>
          <view class="filter-tags">
            <view v-for="s in subjectOptions" :key="s" class="tag" :class="{ on: crossSubject === s }" @click="crossSubject = s">{{ s }}</view>
          </view>
        </view>
        <view v-if="tierOptions.length" class="filter-row">
          <text class="filter-k">档位</text>
          <view class="filter-tags">
            <view v-for="t in tierOptions" :key="t" class="tag" :class="{ on: crossTier === t }" @click="crossTier = t">{{ t }}</view>
          </view>
        </view>

        <view class="notice">
          <app-icon name="info" color="#8f96a2" :size="26"></app-icon>
          <text class="notice-t">各省已统一为「物理类 / 历史类」，批次口径相近（一本线在部分省实为特殊类型招生控制线）。分数不可直接横比选校——各省试卷与考生结构不同。</text>
        </view>

        <view v-if="crossRows.length === 0" class="xf-card">
          <view class="xf-empty">
            <app-icon name="info" color="#4b515b" :size="56"></app-icon>
            <text class="xf-empty-title">该科类 / 档位暂无省份数据</text>
            <text class="xf-empty-desc">换一个档位，或切到「单省明细」看该省全部档位。</text>
          </view>
        </view>

        <view v-else class="xf-card panel">
          <view v-for="(row, i) in crossRows" :key="row.province" class="xrow">
            <text class="xrank">{{ i + 1 }}</text>
            <view class="xmain">
              <view class="xline-top">
                <text class="xprov">{{ row.province }}</text>
                <text class="xscore">{{ row.score }}<text class="xunit"> 分</text></text>
              </view>
              <view class="xbar">
                <view class="xbar-fill" :style="{ width: barWidth(row.score) + '%' }"></view>
              </view>
              <text class="xline">{{ row.line }}</text>
            </view>
          </view>
        </view>

        <view v-if="sourceUrl" class="source-row" @click="open(sourceUrl)">
          <app-icon name="external" color="#6db3f2" :size="26"></app-icon>
          <text class="source-t">{{ year }} 年官方来源（阳光高考）</text>
          <app-icon name="chevron-right" color="#6f7683" :size="24"></app-icon>
        </view>
      </block>

      <view class="disclaim">数据仅供学习参考，正式填报以各省教育考试院为准。</view>
      <wd-toast />
    </view>
  </wd-config-provider>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { api } from "@/utils/api";
import { useToast } from "wot-design-uni";
import { themeVars } from "@/utils/theme";

const toast = useToast();

const years = ref<any[]>([]);
const yearInfo = ref<Record<string, any>>({});
const year = ref(2026);
const mode = ref("single");
const provinces = ref<any[]>([]);
const province = ref("河南");

const loading = ref(false);
const err = ref("");

// 单省：{ 科类: { 档位: [ {year, score, line} ] } }
const provData = ref(null);
// 跨省：{ 省: { 科类: { 档位: {line, score} } } }
const crossAll = ref(null);

const crossTier = ref("普通一本");
const crossSubject = ref("物理类");

const sourceUrl = computed(() => (yearInfo.value[String(year.value)] || {}).source_url || "");
const latestYear = computed(() => (years.value.length ? years.value[0] : 0));

const subjectKeys = computed(() => (provData.value ? Object.keys(provData.value) : []));
function tiersOf(subj: any) {
  return provData.value && provData.value[subj] ? Object.keys(provData.value[subj]) : [];
}
function cellOf(subj: any, tier: any) {
  const arr = provData.value && provData.value[subj] && provData.value[subj][tier];
  if (!arr) return null;
  return arr.find((p) => p.year === year.value) || null;
}
function lineOf(subj: any, tier: any) {
  const c = cellOf(subj, tier);
  return c ? c.line : "";
}
function scoreOf(subj: any, tier: any) {
  const c = cellOf(subj, tier);
  return c ? c.score : "—";
}

function sortedPoints(subj: any, tier: any) {
  const arr = provData.value && provData.value[subj] && provData.value[subj][tier];
  if (!arr || !arr.length) return [];
  return arr.slice().sort((a, b) => a.year - b.year);
}

function trendBars(subj: any, tier: any) {
  const arr = sortedPoints(subj, tier);
  if (!arr.length) return [];
  const scores = arr.map((p) => p.score);
  const mn = Math.min(...scores);
  const mx = Math.max(...scores);
  return arr.map((p) => ({
    year: p.year,
    score: p.score,
    h: mx === mn ? 50 : Math.round(30 + ((p.score - mn) / (mx - mn)) * 70),
  }));
}

// 五年区间：一眼看出这档线的波动范围
function rangeText(subj: any, tier: any) {
  const arr = sortedPoints(subj, tier);
  if (!arr.length) return "—";
  const scores = arr.map((p) => p.score);
  return Math.min(...scores) + "–" + Math.max(...scores) + " 分";
}

// 同比：较上一年变化，向上为红（分数涨），向下为绿
function deltaValue(subj: any, tier: any) {
  const arr = sortedPoints(subj, tier);
  const idx = arr.findIndex((p) => p.year === year.value);
  if (idx <= 0) return null;
  return arr[idx].score - arr[idx - 1].score;
}
function deltaText(subj: any, tier: any) {
  const d = deltaValue(subj, tier);
  if (d === null) return "无上年可比";
  if (d === 0) return "与上年持平";
  return (d > 0 ? "↑ " : "↓ ") + Math.abs(d) + " 分";
}
function deltaCls(subj: any, tier: any) {
  const d = deltaValue(subj, tier);
  if (d === null || d === 0) return "flat";
  return d > 0 ? "up" : "down";
}

const subjectOptions = computed(() => {
  const set = new Set();
  const d = crossAll.value;
  if (d) Object.values(d).forEach((subjMap) => Object.keys(subjMap).forEach((s) => set.add(s)));
  return [...set];
});
const tierOptions = computed(() => {
  const set = new Set();
  const d = crossAll.value;
  if (d)
    Object.values(d).forEach((subjMap) => {
      const sm = subjMap[crossSubject.value];
      if (sm) Object.keys(sm).forEach((t) => set.add(t));
    });
  return [...set];
});
const crossRows = computed(() => {
  const d = crossAll.value;
  if (!d) return [];
  const out: any[] = [];
  for (const [prov, subjMap] of Object.entries(d)) {
    const sm = subjMap[crossSubject.value];
    if (!sm) continue;
    const t = sm[crossTier.value];
    if (!t) continue;
    out.push({ province: prov, score: t.score, line: t.line });
  }
  return out.sort((a, b) => b.score - a.score);
});

// 跨省条形按本组最高分归一，避免绝对刻度被极端值拉平
const crossMax = computed(() => {
  const rows = crossRows.value;
  return rows.length ? Math.max(...rows.map((r) => r.score)) : 1;
});
function barWidth(score: any) {
  const mx = crossMax.value || 1;
  return Math.max(6, Math.round((score / mx) * 100));
}

async function loadYears() {
  try {
    const r = await api.controlLineYears();
    const ys = (r.years || []).slice().sort((a, b) => b - a);
    years.value = ys;
    yearInfo.value = r.by_year || {};
    const latest = ys[0];
    provinces.value =
      (r.by_year && r.by_year[String(latest)] && r.by_year[String(latest)].provinces) || [];
    if (!year.value || !ys.includes(year.value)) year.value = latest;
  } catch (e: any) {
    err.value = "加载年份失败：" + (e.message || e);
  }
}

async function loadSingle() {
  if (!province.value) return;
  loading.value = true;
  err.value = "";
  try {
    const ys = years.value.length ? years.value : [year.value];
    const res = await Promise.all(ys.map((y) => api.controlLines(y, province.value)));
    const merged: Record<string, any> = {};
    res.forEach((r, i) => {
      const y = ys[i];
      const subjMap = (r.data && r.data[province.value]) || {};
      for (const [subj, tierMap] of Object.entries(subjMap)) {
        if (!merged[subj]) merged[subj] = {};
        for (const [tier, info] of Object.entries(tierMap)) {
          if (!merged[subj][tier]) merged[subj][tier] = [];
          merged[subj][tier].push({ year: y, score: info.score, line: info.line });
        }
      }
    });
    provData.value = merged;
  } catch (e: any) {
    err.value = "加载省控线失败：" + (e.message || e);
    provData.value = null;
  } finally {
    loading.value = false;
  }
}

async function loadCross() {
  loading.value = true;
  err.value = "";
  try {
    const r = await api.controlLines(year.value);
    crossAll.value = (r && r.data) || {};
    const subs = subjectOptions.value;
    if (subs.length && !subs.includes(crossSubject.value)) crossSubject.value = subs[0];
    const tiers = tierOptions.value;
    if (tiers.length && !tiers.includes(crossTier.value)) crossTier.value = tiers[0];
  } catch (e: any) {
    err.value = "加载跨省数据失败：" + (e.message || e);
    crossAll.value = null;
  } finally {
    loading.value = false;
  }
}

function setYear(y: any) {
  year.value = y;
  if (mode.value === "cross") loadCross();
}
function setMode(m: any) {
  if (mode.value === m) return;
  mode.value = m;
  if (m === "single") loadSingle();
  else loadCross();
}
function setProvince(p: any) {
  province.value = p;
  loadSingle();
}
function open(u: any) {
  if (!u) {
    toast.show("暂无来源链接");
    return;
  }
  // #ifdef H5
  window.open(u, "_blank");
  // #endif
  // #ifndef H5
  uni.setClipboardData({ data: u, success: () => toast.show("链接已复制，请在浏览器打开") });
  // #endif
}

onMounted(async () => {
  await loadYears();
  if (mode.value === "single") await loadSingle();
  else await loadCross();
});
</script>

<style scoped>
.page { padding: 24rpx 24rpx 80rpx; min-height: 100vh; background: var(--xf-bg); }

/* 年份时间轴 */
.tl-wrap { position: relative; margin: 18rpx 0 22rpx; padding: 6rpx 0; }
.tl-line { position: absolute; left: 8%; right: 8%; top: 62rpx; height: 2rpx; background: var(--xf-line); }
.tl { display: flex; position: relative; }
.tl-item { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 8rpx; padding: 2rpx 0 4rpx; }
.tl-y { font-size: 22rpx; color: var(--xf-text-4); font-variant-numeric: tabular-nums; }
.tl-y.on { color: var(--xf-gold); font-weight: 700; }
.tl-dot { width: 18rpx; height: 18rpx; border-radius: 50%; background: var(--xf-surface-3); border: 2rpx solid var(--xf-bg); }
.tl-dot.on { width: 24rpx; height: 24rpx; background: var(--xf-gold); box-shadow: 0 0 0 6rpx rgba(255, 210, 77, 0.16); }
.tl-tag { font-size: 17rpx; color: var(--xf-gold-dim); min-height: 24rpx; }

/* 模式 */
.seg { display: flex; gap: 12rpx; margin-bottom: 16rpx; }
.seg-item {
  flex: 1; display: flex; align-items: center; justify-content: center; gap: 10rpx;
  padding: 16rpx 0; min-height: 84rpx; border-radius: var(--xf-r-md);
  background: var(--xf-surface); border: 1rpx solid var(--xf-line);
}
.seg-item.on { background: rgba(255, 210, 77, 0.09); border-color: rgba(255, 210, 77, 0.4); }
.seg-text { font-size: 25rpx; color: var(--xf-text-3); }
.seg-item.on .seg-text { color: var(--xf-gold); font-weight: 600; }

/* 省筛选 */
.filters { white-space: nowrap; margin: 4rpx 0 16rpx; }
.chips { display: inline-flex; gap: 12rpx; padding: 2rpx 2rpx 8rpx; }
.chip {
  padding: 12rpx 24rpx; border-radius: 999rpx; font-size: 23rpx;
  background: var(--xf-surface); border: 1rpx solid var(--xf-line); color: var(--xf-text-3);
}
.chip.on { background: rgba(255, 210, 77, 0.12); border-color: rgba(255, 210, 77, 0.45); color: var(--xf-gold); font-weight: 600; }

.err { display: flex; align-items: flex-start; gap: 10rpx; margin: 16rpx 0; padding: 14rpx 16rpx; border-radius: var(--xf-r-sm); font-size: 22rpx; color: var(--xf-danger-text); background: rgba(229, 72, 77, 0.08); border: 1rpx solid rgba(229, 72, 77, 0.32); }
.err-t { flex: 1; line-height: 1.6; }

/* 单省面板 */
.panel { margin-bottom: 18rpx; }
.panel-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 6rpx; }
.panel-h { font-size: 28rpx; font-weight: 700; color: var(--xf-text); }
.panel-y { font-size: 20rpx; color: var(--xf-text-4); }

.tier-row { padding: 16rpx 0; border-top: 1rpx solid var(--xf-line-soft); }
.tier-row:first-of-type { border-top: none; }
.tier-main { display: flex; align-items: flex-end; justify-content: space-between; gap: 12rpx; }
.tier-left { min-width: 0; }
.tier-name { display: block; font-size: 24rpx; color: var(--xf-text-2); }
.tier-sub { display: block; margin-top: 2rpx; font-size: 18rpx; color: var(--xf-text-4); }
.tier-right { display: flex; align-items: baseline; gap: 4rpx; }
.tier-score { font-size: 40rpx; font-weight: 700; color: var(--xf-gold); line-height: 1.1; font-variant-numeric: tabular-nums; }
.tier-unit { font-size: 19rpx; color: var(--xf-text-4); }

/* 五年柱 */
.trend { display: flex; align-items: flex-end; gap: 8rpx; margin-top: 14rpx; height: 132rpx; }
.tbar-col { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; gap: 4rpx; }
.tbar-v { font-size: 17rpx; color: var(--xf-text-4); font-variant-numeric: tabular-nums; }
.tbar-v.on { color: var(--xf-gold); font-weight: 700; }
.tbar { width: 100%; max-width: 56rpx; background: var(--xf-surface-3); border-radius: 6rpx 6rpx 0 0; transition: height 260ms var(--xf-ease); }
.tbar.on { background: linear-gradient(180deg, var(--xf-gold), rgba(255, 210, 77, 0.42)); }
.tbar-y { font-size: 16rpx; color: var(--xf-text-4); font-variant-numeric: tabular-nums; }
.tbar-y.on { color: var(--xf-text-2); }

.tier-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 10rpx; }
.tier-range { font-size: 19rpx; color: var(--xf-text-4); }
.tier-delta { font-size: 20rpx; }
.tier-delta.up { color: var(--xf-danger-text); }
.tier-delta.down { color: var(--xf-safe); }
.tier-delta.flat { color: var(--xf-text-4); }

/* 跨省 */
.filter-row { display: flex; align-items: flex-start; gap: 14rpx; margin-bottom: 12rpx; }
.filter-k { flex: 0 0 auto; font-size: 21rpx; color: var(--xf-text-4); padding-top: 10rpx; }
.filter-tags { flex: 1; display: flex; flex-wrap: wrap; gap: 10rpx; }
.tag { padding: 9rpx 20rpx; border-radius: 999rpx; font-size: 22rpx; background: var(--xf-surface); border: 1rpx solid var(--xf-line); color: var(--xf-text-3); }
.tag.on { background: rgba(255, 210, 77, 0.12); border-color: rgba(255, 210, 77, 0.45); color: var(--xf-gold); font-weight: 600; }

.notice { display: flex; align-items: flex-start; gap: 12rpx; margin: 6rpx 0 16rpx; padding: 16rpx 18rpx; border-radius: var(--xf-r-sm); background: var(--xf-surface); border: 1rpx solid var(--xf-line); }
.notice-t { flex: 1; font-size: 20rpx; color: var(--xf-text-3); line-height: 1.7; }

.xrow { display: flex; align-items: flex-start; gap: 12rpx; padding: 14rpx 0; border-top: 1rpx solid var(--xf-line-soft); }
.xrow:first-of-type { border-top: none; }
.xrank { width: 34rpx; font-size: 19rpx; color: var(--xf-text-4); padding-top: 6rpx; font-variant-numeric: tabular-nums; }
.xmain { flex: 1; min-width: 0; }
.xline-top { display: flex; align-items: baseline; justify-content: space-between; gap: 12rpx; }
.xprov { font-size: 25rpx; color: var(--xf-text); }
.xscore { font-size: 28rpx; font-weight: 700; color: var(--xf-gold); font-variant-numeric: tabular-nums; }
.xunit { font-size: 18rpx; color: var(--xf-text-4); font-weight: 400; }
.xbar { height: 8rpx; border-radius: 4rpx; background: var(--xf-surface-3); margin: 8rpx 0 6rpx; overflow: hidden; }
.xbar-fill { height: 100%; border-radius: 4rpx; background: linear-gradient(90deg, rgba(255, 210, 77, 0.5), var(--xf-gold)); }
.xline { display: block; font-size: 18rpx; color: var(--xf-text-4); }

.source-row { display: flex; align-items: center; gap: 10rpx; min-height: 88rpx; padding: 0 18rpx; margin-top: 6rpx; border-radius: var(--xf-r-md); background: var(--xf-surface); border: 1rpx solid var(--xf-line); }
.source-t { flex: 1; font-size: 23rpx; color: var(--xf-real); }

.disclaim { margin-top: 24rpx; font-size: 20rpx; color: var(--xf-text-4); line-height: 1.7; text-align: center; }
</style>
