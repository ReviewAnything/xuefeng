<template>
  <wd-config-provider theme="dark" :theme-vars="themeVars">
    <view class="page">
      <view class="hero">
        <text class="h1">观点 × 数据 交叉核验</text>
        <text class="sub">P2 核心：把定性观点与后端定量录取数据做一致性校验，强化偏见校正。</text>
      </view>

      <view class="section">
        <view class="section-head">
          <text class="h3">输入你的条件</text>
          <wd-tag type="primary" plain>31 省 · 2868 所院校</wd-tag>
        </view>

        <wd-cell-group border>
          <wd-picker v-model="p.province" label="高考省份" :columns="provinces" placeholder="请选择" label-width="30%" />
          <wd-picker v-model="p.subject" label="选科方向" :columns="subjects" placeholder="请选择" label-width="30%" />
          <wd-input v-model="p.user_rank" label="高考位次" type="number" placeholder="如：40000" label-width="30%" />
          <wd-picker v-model="p.major_name" label="目标专业" :columns="majorNames" placeholder="请选择" label-width="30%" />
        </wd-cell-group>

        <view class="actions">
          <wd-button type="primary" block size="large" :loading="loading" @click="run">开始交叉核验</wd-button>
          <wd-button v-if="canvasPicks.length" plain block @click="importFromCanvas">从诊断画布导入（{{ canvasPicks.length }} 个方向）并批量核验</wd-button>
        </view>
        <text v-if="err" class="err">{{ err }}</text>
      </view>

      <!-- 批量核验：P1→P2 打通 -->
      <view class="section" v-if="batchMode">
        <view class="section-head">
          <text class="h3">批量核验（画布推荐方向）</text>
          <wd-tag type="primary" plain>一次算完</wd-tag>
        </view>
        <text class="small">点按可增删待核验专业；结果按「冲突 → 需谨慎 → 一致」排序，先看风险项。</text>
        <view class="tags">
          <wd-tag v-for="n in candidates" :key="n"
                  :type="selected.includes(n) ? 'success' : 'default'"
                  :plain="!selected.includes(n)" @click="toggle(n)">{{ n }}</wd-tag>
        </view>
        <view class="actions">
          <wd-button type="primary" block size="large" :loading="batchLoading" @click="runBatch">
            {{ batchLoading ? "批量核验中…" : "批量核验 " + selected.length + " 个专业" }}
          </wd-button>
        </view>
        <text v-if="batchErr" class="err">{{ batchErr }}</text>
      </view>

      <view class="section" v-if="batch">
        <view class="section-head">
          <text class="h3">批量核验结果</text>
          <text class="bk-sub">{{ batch.province }} · {{ batch.subject }} · 位次 {{ batch.user_rank }}</text>
        </view>
        <view class="sum">
          <text class="sum-i conflict">冲突 {{ batch.summary.conflict }}</text>
          <text class="sum-i caution">需谨慎 {{ batch.summary.caution }}</text>
          <text class="sum-i aligned">一致 {{ batch.summary.aligned }}</text>
        </view>
        <view v-for="r in batch.results" :key="r.major" class="brow" @click="openOne(r.major)">
          <view class="brow-head">
            <text class="brow-name">{{ r.major }}</text>
            <wd-tag :type="alignType(r.alignment)" plain>{{ r.alignment_label }}</wd-tag>
          </view>
          <text class="brow-meta">
            {{ r.view_label }} · 最易触及 {{ r.best_reachable ? r.best_reachable.tier : "不可及" }}
            <text v-if="r.best_reachable">（位次 {{ r.best_reachable.min_rank }}，判定{{ r.best_reachable.level }}）</text>
          </text>
        </view>
        <text v-if="unknownLabel" class="small">未收录专业：{{ unknownLabel }}</text>
        <text class="small">点击任一专业可展开完整核验详情（定性观点 / 偏见校正 / 各批次门槛 / 建议动作）。</text>
      </view>

      <view class="section" v-if="res">
        <view class="section-head">
          <text class="h3">{{ res.major }}</text>
          <wd-tag :type="viewTagType" plain>{{ res.view_label }}</wd-tag>
        </view>

        <view class="align" :class="res.alignment">
          <text class="align-label">{{ res.alignment_label }}</text>
        </view>

        <view class="block">
          <text class="bk">定性观点</text>
          <text class="bt">{{ res.reason }}</text>
        </view>
        <view class="block warn">
          <text class="bk">⚖ 偏见校正</text>
          <text class="bt">{{ res.bias }}</text>
        </view>

        <view class="block">
          <view class="block-head">
            <text class="bk">各批次录取门槛</text>
            <text class="bk-sub">{{ res.province }} · {{ res.subject }}</text>
          </view>
          <view class="tier" v-for="t in res.tiers" :key="t.tier"
                :class="{ best: isBestTier(t.tier) }">
            <view class="tier-name">
              <text class="tt">{{ t.tier }}</text>
              <wd-tag :type="t.data_source === 'official' ? 'success' : 'warning'" plain>
                {{ t.data_source === "official" ? "官方" : "估算" }}
              </wd-tag>
            </view>
            <text class="ts">≈{{ t.min_score }}分 / 位次{{ t.min_rank }}</text>
            <wd-tag :type="levelType(t.level)" plain>{{ t.level }}</wd-tag>
          </view>
          <text class="dsrc">数据源：{{ sourceLabel }}</text>
        </view>

        <view class="block" v-if="hasSchools">
          <wd-collapse v-model="schoolOpen">
            <wd-collapse-item :title="`可触及层次院校（${res.reachable_tier} · ${res.reachable_tier_school_count} 所）`" name="schools">
              <view class="uni-wrap">
                <wd-tag v-for="s in res.reachable_tier_schools" :key="s" type="default" plain>{{ s }}</wd-tag>
              </view>
              <text class="dsrc">教育部官方 {{ res.reachable_tier }} 院校完整清单；同层次内未区分具体录取线，请以各校招生网/考试院为准。</text>
            </wd-collapse-item>
          </wd-collapse>
        </view>

        <view class="block msg">
          <rich-text :nodes="res.message"></rich-text>
        </view>

        <view class="block">
          <text class="bk">建议动作</text>
          <view v-for="(s, i) in res.suggestions" :key="i" class="sg">· {{ s }}</view>
        </view>
      </view>
    </view>
    <wd-toast />
  </wd-config-provider>
</template>

<script setup>
import { computed, reactive, ref } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { useToast } from "wot-design-uni";
import { MAJORS } from "@/utils/content.js";
import { api } from "@/utils/api.js";
import { themeVars } from "@/utils/theme.js";

const toast = useToast();

// 全国 31 省（与 admission_real_baseline.json 覆盖一致）
const provinces = ["北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆"];
const subjects = ["物理类", "历史类", "综合/未改革"];
const majorNames = MAJORS.map((m) => m.name);

const p = reactive({ province: "", subject: "", user_rank: "", major_name: "" });
const res = ref(null);
const err = ref("");
const loading = ref(false);
const schoolOpen = ref("");

// —— 批量核验（P1→P2 打通）——
const batchMode = ref(false);
const candidates = ref([]);      // 可勾选的专业（画布推荐方向）
const selected = ref([]);        // 已勾选
const canvasPicks = ref([]);     // 端侧存储的画布结果（仅本机）
const batch = ref(null);
const batchErr = ref("");
const batchLoading = ref(false);

const viewTagType = computed(() => {
  const v = res.value && res.value.view;
  return v === "recommend" ? "success" : v === "caution" ? "warning" : "danger";
});

const hasSchools = computed(() => {
  const r = res.value;
  return !!(r && r.reachable_tier && r.reachable_tier_schools && r.reachable_tier_schools.length);
});

const unknownLabel = computed(() => {
  const b = batch.value;
  return b && b.unknown && b.unknown.length ? b.unknown.join("、") : "";
});

const sourceLabel = computed(() => {
  if (!res.value) return "";
  return res.value.data_source === "official_overlay"
    ? "11 省官方省控线 + 其余估算（以考试院为准）"
    : res.value.data_source === "real"
      ? "真实录取记录（估算）"
      : "参数化样例（演示）";
});

function levelType(level) {
  return { 保: "success", 稳: "primary", 冲: "warning", 不可及: "default" }[level] || "default";
}

// 当前最易触及的批次高亮（抽成方法，避免模板内长表达式）
function isBestTier(tier) {
  const b = res.value && res.value.best_reachable;
  return !!(b && b.tier === tier);
}

function alignType(alignment) {
  return { aligned: "success", caution: "warning", conflict: "danger" }[alignment] || "default";
}

// 读取端侧画布结果（诊断页写入，仅存本机）
function loadCanvas() {
  const saved = uni.getStorageSync("zhiyuan_canvas_v2");
  if (saved && Array.isArray(saved.picks) && saved.picks.length) {
    canvasPicks.value = saved.picks;
    if (!p.province && saved.province) p.province = saved.province;
    if (!p.subject && saved.subject) p.subject = saved.subject;
    if (!p.user_rank && saved.user_rank) p.user_rank = String(saved.user_rank);
    return true;
  }
  return false;
}

function toggle(name) {
  selected.value = selected.value.includes(name)
    ? selected.value.filter((n) => n !== name)
    : [...selected.value, name];
}

// 手动从画布导入后批量核验
function importFromCanvas() {
  if (!loadCanvas()) { toast.show("本机暂无画布结果，请先完成诊断"); return; }
  batchMode.value = true;
  candidates.value = canvasPicks.value.slice(0, 20);
  selected.value = candidates.value.slice();
  runBatch();
}

async function runBatch() {
  if (!p.province || !p.subject || !p.user_rank) {
    batchErr.value = "请先填写省份 / 科类 / 位次";
    toast.show(batchErr.value);
    return;
  }
  if (!selected.value.length) {
    batchErr.value = "请至少勾选一个专业";
    toast.show(batchErr.value);
    return;
  }
  batchErr.value = "";
  batchLoading.value = true;
  try {
    batch.value = await api.verifyBatch(p.province, p.subject, Number(p.user_rank), selected.value);
  } catch (e) {
    batchErr.value = "后端未连接（请先启动 Python 后端 uvicorn main:app --port 8000）：" + (e.message || e);
  } finally {
    batchLoading.value = false;
  }
}

// 从批量结果里点开某一专业的完整详情
async function openOne(name) {
  p.major_name = name;
  await run();
}

// 支持从「诊断画布」一键带入（省份/科类/位次/专业，或 batch=1 进入批量模式）
onLoad((q) => {
  loadCanvas();
  if (q) {
    if (q.province) p.province = q.province;
    if (q.subject) p.subject = q.subject;
    if (q.user_rank) p.user_rank = q.user_rank;
    if (q.major_name) p.major_name = q.major_name;
    if (q.batch === "1" || q.batch === 1) {
      batchMode.value = true;
      candidates.value = (canvasPicks.value.length ? canvasPicks.value : MAJORS.map((m) => m.name)).slice(0, 20);
      selected.value = candidates.value.slice();
      if (p.province && p.subject && p.user_rank) runBatch();
    }
  }
});

async function run() {
  if (!p.province || !p.subject || !p.user_rank || !p.major_name) {
    err.value = "请完整填写省份 / 科类 / 位次 / 专业";
    toast.show(err.value);
    return;
  }
  err.value = "";
  loading.value = true;
  try {
    res.value = await api.verify({
      province: p.province,
      subject: p.subject,
      user_rank: Number(p.user_rank),
      major_name: p.major_name,
    });
  } catch (e) {
    err.value = "后端未连接（请先启动 Python 后端 uvicorn main:app --port 8000）：" + (e.message || e);
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.page { padding: 24rpx 24rpx 60rpx; }
.hero { padding: 16rpx 8rpx 20rpx; }
.h1 { font-size: 40rpx; font-weight: 700; color: #ffd24d; }
.sub { display: block; margin-top: 10rpx; font-size: 24rpx; color: #8a909c; line-height: 1.6; }

.section { margin-bottom: 24rpx; }
.section-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14rpx; }
.h3 { font-size: 30rpx; font-weight: 600; color: #e6e8ec; }
.actions { margin-top: 18rpx; }

.align { border-radius: 12rpx; padding: 16rpx; text-align: center; margin: 6rpx 0 18rpx; }
.align-label { font-size: 28rpx; font-weight: 700; }
.align.aligned { background: #16361f; }
.align.aligned .align-label { color: #5fd87f; }
.align.caution { background: #3a2f12; }
.align.caution .align-label { color: #f0ad4e; }
.align.conflict { background: #3a1a1a; }
.align.conflict .align-label { color: #ff6b6b; }

.block { margin-bottom: 20rpx; }
.block.warn { background: #1c1f26; border-radius: 12rpx; padding: 14rpx 16rpx; }
.block-head { display: flex; align-items: baseline; justify-content: space-between; }
.bk { font-size: 24rpx; color: #ffd24d; font-weight: 600; display: block; margin-bottom: 8rpx; }
.bk-sub { font-size: 21rpx; color: #6b7280; }
.bt { font-size: 24rpx; color: #c7ccd4; line-height: 1.7; }

.tier { display: flex; align-items: center; gap: 12rpx; background: #16191f; border: 1px solid #23262e; border-radius: 12rpx; padding: 12rpx 16rpx; margin-bottom: 10rpx; }
.tier.best { border-color: #ffd24d; background: #1f1d14; }
.tier-name { display: flex; align-items: center; gap: 8rpx; min-width: 170rpx; }
.tt { font-size: 24rpx; color: #e6e8ec; }
.ts { font-size: 22rpx; color: #8a909c; flex: 1; }

/* 批量核验 */
.tags { display: flex; flex-wrap: wrap; gap: 12rpx; margin: 10rpx 0 14rpx; }
.sum { display: flex; gap: 12rpx; margin-bottom: 14rpx; }
.sum-i { font-size: 22rpx; padding: 6rpx 16rpx; border-radius: 999rpx; border: 1px solid #2a2e37; }
.sum-i.conflict { color: #ff6b6b; border-color: #4a2222; background: #2a1414; }
.sum-i.caution { color: #f0ad4e; border-color: #4a3a18; background: #2a2214; }
.sum-i.aligned { color: #5fd87f; border-color: #224a2c; background: #142a1a; }
.brow { background: #16191f; border: 1px solid #23262e; border-radius: 12rpx; padding: 14rpx 16rpx; margin-bottom: 10rpx; }
.brow-head { display: flex; align-items: center; justify-content: space-between; gap: 12rpx; }
.brow-name { font-size: 26rpx; color: #e6e8ec; font-weight: 600; }
.brow-meta { display: block; margin-top: 8rpx; font-size: 21rpx; color: #8a909c; line-height: 1.6; }

.dsrc { font-size: 21rpx; color: #6db3f2; display: block; margin-top: 8rpx; line-height: 1.6; }
.uni-wrap { display: flex; flex-wrap: wrap; gap: 10rpx; padding: 4rpx 0 10rpx; }
.msg { background: #1c1f26; border-radius: 12rpx; padding: 16rpx; }
.sg { font-size: 23rpx; color: #c7ccd4; line-height: 1.8; }
.err { display: block; font-size: 22rpx; color: #ff6b6b; margin-top: 12rpx; line-height: 1.5; }
</style>
