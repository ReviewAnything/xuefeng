<template>
  <wd-config-provider theme="dark" :theme-vars="themeVars">
    <view class="page">
      <view class="hero">
        <text class="h1">年度罗盘</text>
        <text class="sub">近五年（2022–2026）官方省控线，逐年可溯源。来源：阳光高考逐年官方录取控制分数线主表。省控线不含一分一段位次，仅作批次门槛参考。</text>
      </view>

      <view class="disclaim">数据仅供学习参考，正式填报以各省教育考试院为准。</view>

      <!-- 年份 + 模式 -->
      <view class="seg">
        <view v-for="y in years" :key="y" class="seg-item" :class="{ on: year === y }" @click="setYear(y)">
          <text class="seg-text">{{ y }}</text>
        </view>
      </view>
      <view class="seg sm">
        <view class="seg-item" :class="{ on: mode === 'single' }" @click="setMode('single')">
          <text class="seg-text">单省明细</text>
        </view>
        <view class="seg-item" :class="{ on: mode === 'cross' }" @click="setMode('cross')">
          <text class="seg-text">跨省对比</text>
        </view>
      </view>

      <view v-if="loading" class="loading">加载中…</view>
      <view v-if="err" class="err">{{ err }}</view>

      <!-- 单省明细 -->
      <block v-if="mode === 'single' && provData">
        <scroll-view class="filters" scroll-x="true">
          <view class="chips">
            <view v-for="p in provinces" :key="p" class="chip" :class="{ on: p === province }" @click="setProvince(p)">{{ p }}</view>
          </view>
        </scroll-view>

        <view v-if="subjectKeys.length === 0" class="empty">该年暂无 {{ province }} 的省控线数据。</view>

        <view v-for="subj in subjectKeys" :key="subj" class="panel">
          <text class="panel-h">{{ subj }}</text>
          <view v-for="tier in tiersOf(subj)" :key="tier" class="tier-row">
            <view class="tier-main">
              <text class="tier-name">{{ lineOf(subj, tier) || tier }}</text>
              <text class="tier-score">{{ scoreOf(subj, tier) }}</text>
            </view>
            <view class="trend">
              <view v-for="pt in trendBars(subj, tier)" :key="pt.year" class="tbar" :style="{ height: pt.h + 'rpx' }">
                <text class="tbar-v">{{ pt.score }}</text>
                <text class="tbar-y">{{ pt.year }}</text>
              </view>
            </view>
          </view>
        </view>

        <view class="acts">
          <wd-button size="small" plain @click="open(sourceUrl)">当年来源 ↗</wd-button>
        </view>
      </block>

      <!-- 跨省对比 -->
      <block v-if="mode === 'cross' && crossAll">
        <view v-if="subjectOptions.length" class="filters">
          <wd-tag v-for="s in subjectOptions" :key="s" :type="crossSubject === s ? 'primary' : 'default'"
                  :plain="crossSubject !== s" round @click="crossSubject = s">{{ s }}</wd-tag>
        </view>
        <view v-if="tierOptions.length" class="filters">
          <wd-tag v-for="t in tierOptions" :key="t" :type="crossTier === t ? 'primary' : 'default'"
                  :plain="crossTier !== t" round @click="crossTier = t">{{ t }}</wd-tag>
        </view>

        <view class="disclaim warn">跨省对比注意口径：各省已统一为「物理类 / 历史类」科类，批次线口径相近（普通一本 / 普通二本 / 专科，部分省一本线实为特殊类型招生控制线）。但分数不可直接横比选校——各省试卷与考生结构不同，仅作省际难度参考。</view>

        <view v-if="crossRows.length === 0" class="empty">该科类/档位暂无省份数据。</view>
        <view v-else class="panel">
          <view v-for="row in crossRows" :key="row.province" class="xrow">
            <text class="xprov">{{ row.province }}</text>
            <text class="xscore">{{ row.score }}</text>
            <text class="xline">{{ row.line }}</text>
          </view>
        </view>

        <view class="acts">
          <wd-button size="small" plain @click="open(sourceUrl)">当年来源 ↗</wd-button>
        </view>
      </block>

      <wd-toast />
    </view>
  </wd-config-provider>
</template>

<script setup>
import { ref, computed, onMounted } from "vue";
import { api } from "@/utils/api.js";
import { useToast } from "wot-design-uni";
import { themeVars } from "@/utils/theme.js";

const toast = useToast();

const years = ref([]);
const yearInfo = ref({});
const year = ref(2026);
const mode = ref("single");
const provinces = ref([]);
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

const subjectKeys = computed(() => (provData.value ? Object.keys(provData.value) : []));
function tiersOf(subj) {
  return provData.value && provData.value[subj] ? Object.keys(provData.value[subj]) : [];
}
function cellOf(subj, tier) {
  const arr = provData.value && provData.value[subj] && provData.value[subj][tier];
  if (!arr) return null;
  return arr.find((p) => p.year === year.value) || null;
}
function lineOf(subj, tier) {
  const c = cellOf(subj, tier);
  return c ? c.line : "";
}
function scoreOf(subj, tier) {
  const c = cellOf(subj, tier);
  return c ? c.score : "—";
}
function trendBars(subj, tier) {
  const arr = provData.value && provData.value[subj] && provData.value[subj][tier];
  if (!arr || !arr.length) return [];
  const scores = arr.map((p) => p.score);
  const mn = Math.min(...scores);
  const mx = Math.max(...scores);
  return arr
    .slice()
    .sort((a, b) => a.year - b.year)
    .map((p) => ({
      year: p.year,
      score: p.score,
      h: mx === mn ? 50 : Math.round(30 + ((p.score - mn) / (mx - mn)) * 70),
    }));
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
  const out = [];
  for (const [prov, subjMap] of Object.entries(d)) {
    const sm = subjMap[crossSubject.value];
    if (!sm) continue;
    const t = sm[crossTier.value];
    if (!t) continue;
    out.push({ province: prov, score: t.score, line: t.line });
  }
  return out.sort((a, b) => b.score - a.score);
});

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
  } catch (e) {
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
    const merged = {};
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
  } catch (e) {
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
  } catch (e) {
    err.value = "加载跨省数据失败：" + (e.message || e);
    crossAll.value = null;
  } finally {
    loading.value = false;
  }
}

function setYear(y) {
  year.value = y;
  if (mode.value === "cross") loadCross();
}
function setMode(m) {
  if (mode.value === m) return;
  mode.value = m;
  if (m === "single") loadSingle();
  else loadCross();
}
function setProvince(p) {
  province.value = p;
  loadSingle();
}
function open(u) {
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
.page { padding: 24rpx 24rpx 60rpx; }
.hero { padding: 16rpx 8rpx 20rpx; }
.h1 { font-size: 40rpx; font-weight: 700; color: #ffd24d; }
.sub { display: block; margin-top: 10rpx; font-size: 24rpx; color: #8a909c; line-height: 1.6; }

.disclaim {
  margin: 14rpx 0 18rpx; padding: 14rpx 18rpx; border-radius: 12rpx;
  font-size: 21rpx; color: #9aa0aa; background: #12151a; border: 1px solid #23262e;
}
.disclaim.warn { color: #f0ad4e; border-color: #55411d; background: #1b1811; }

.seg { display: flex; gap: 12rpx; margin-bottom: 14rpx; }
.seg.sm { margin-bottom: 18rpx; }
.seg-item {
  flex: 1; text-align: center; padding: 16rpx 0; border-radius: 999rpx;
  background: #16191f; border: 1px solid #23262e;
}
.seg-item.on { background: #2a2413; border-color: #6b5a1c; }
.seg-text { font-size: 26rpx; color: #8a909c; }
.seg-item.on .seg-text { color: #ffd24d; font-weight: 600; }

.filters { white-space: nowrap; margin: 6rpx 0 14rpx; }
.chips { display: inline-flex; gap: 12rpx; padding: 2rpx 2rpx 6rpx; }
.chip {
  padding: 10rpx 22rpx; border-radius: 999rpx; font-size: 23rpx;
  background: #16191f; border: 1px solid #23262e; color: #8a909c;
}
.chip.on { background: #2a2413; border-color: #6b5a1c; color: #ffd24d; }

.loading { margin: 30rpx 0; text-align: center; font-size: 24rpx; color: #8a909c; }
.err { margin: 20rpx 0; padding: 14rpx; border-radius: 12rpx; font-size: 23rpx; color: #ff6b6b; background: #1b1111; border: 1px solid #5c2626; }
.empty { margin-top: 30rpx; text-align: center; font-size: 24rpx; color: #6b7280; }

.panel { background: #16191f; border: 1px solid #23262e; border-radius: 16rpx; padding: 22rpx; margin-bottom: 20rpx; }
.panel-h { display: block; font-size: 28rpx; font-weight: 600; color: #e6e8ec; margin-bottom: 12rpx; }

.tier-row { padding: 14rpx 0; border-top: 1px solid #23262e; }
.tier-row:first-of-type { border-top: none; }
.tier-main { display: flex; align-items: baseline; justify-content: space-between; gap: 12rpx; }
.tier-name { font-size: 25rpx; color: #c7ccd4; }
.tier-score { font-size: 30rpx; font-weight: 700; color: #ffd24d; }
.trend { display: flex; align-items: flex-end; gap: 10rpx; margin-top: 12rpx; height: 110rpx; }
.tbar {
  flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: center; justify-content: flex-end;
  background: #23262e; border-radius: 8rpx 8rpx 0 0;
}
.tbar-v { font-size: 19rpx; color: #e6e8ec; }
.tbar-y { font-size: 17rpx; color: #6b7280; margin-bottom: 4rpx; }

.xrow {
  display: flex; align-items: baseline; gap: 14rpx; padding: 14rpx 0; border-top: 1px solid #23262e;
}
.xrow:first-of-type { border-top: none; }
.xprov { font-size: 26rpx; color: #e6e8ec; flex: 1; }
.xscore { font-size: 30rpx; font-weight: 700; color: #ffd24d; }
.xline { font-size: 19rpx; color: #6b7280; max-width: 40%; text-align: right; }

.acts { display: flex; flex-wrap: wrap; gap: 12rpx; margin-top: 6rpx; }
</style>
