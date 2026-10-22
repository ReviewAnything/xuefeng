<template>
  <wd-config-provider theme="dark" :theme-vars="themeVars">
    <view class="page">
      <view class="hero">
        <text class="h1">院校推荐 · 冲稳保</text>
        <text class="sub">按你的位次给出各层次（985 / 211 / 普通本科 / 专科）的门槛判定与院校池。</text>
      </view>

      <view class="section">
        <view class="section-head">
          <text class="h3">输入你的条件</text>
          <wd-tag type="primary" plain>教育部 2868 所</wd-tag>
        </view>

        <wd-cell-group border>
          <wd-picker v-model="f.province" label="高考省份" :columns="provinces" placeholder="请选择" label-width="30%"></wd-picker>
          <wd-picker v-model="f.subject" label="选科方向" :columns="subjects" placeholder="请选择" label-width="30%"></wd-picker>
          <wd-input v-model="f.user_rank" label="高考位次" type="number" placeholder="如：40000" label-width="30%"></wd-input>
          <wd-picker v-model="f.major" label="目标专业" :columns="majorOptions" placeholder="请选择" label-width="30%"></wd-picker>
        </wd-cell-group>

        <view class="actions">
          <wd-button type="primary" block size="large" :loading="loading" @click="run">生成院校推荐</wd-button>
        </view>
        <text v-if="err" class="err">{{ err }}</text>
      </view>

      <view class="section" v-if="hasResult">
        <view class="section-head">
          <text class="h3">梯度概览</text>
          <text class="bk-sub">{{ result.province }} · {{ result.subject }} · 位次 {{ result.user_rank }}</text>
        </view>
        <view class="sum">
          <text class="sum-i reach">冲 {{ result.summary.reach }}</text>
          <text class="sum-i match">稳 {{ result.summary.match }}</text>
          <text class="sum-i safe">保 {{ result.summary.safe }}</text>
          <text class="sum-i none">不可及 {{ result.summary.unreachable }}</text>
        </view>
        <text class="small">数据源：{{ sourceLabel }}</text>
        <!-- S5-A：校线权威声明（真实抓取 ≠ 官方） -->
        <text class="small auth-rcmd" v-if="result && result.school_line_hits">其中 {{ result.school_line_hits }} 所院校已匹配投档线（行内标「去年最低」）；当前全部为真实抓取（掌上高考 2025），非考试院官方发布。</text>
        <text class="small auth-rcmd" v-else-if="result">该省尚未导入院校级投档线，院校行不含「去年最低」；可在管理端「校线导入」上传各省考试院官方投档原表后重新生成。</text>
      </view>

      <view class="section" v-if="hasResult">
        <view v-for="t in result.tiers" :key="t.tier" class="tier-card">
          <view class="tier-head">
            <text class="tier-name">{{ t.tier }}</text>
            <wd-tag :type="levelType(t.level)" plain>{{ t.level }}</wd-tag>
            <wd-tag :type="dsType(t.data_source)" plain>{{ sourceTag(t) }}</wd-tag>
          </view>
          <text class="tier-meta">门槛 ≈{{ t.min_score }} 分 / 位次 {{ t.min_rank }} · {{ t.pool_label }}（共 {{ t.pool_total }} 所，展示前 {{ t.schools.length }} 所）</text>
          <text class="basis">{{ t.basis }}</text>

          <view v-if="t.schools.length" class="schools">
            <view v-for="s in t.schools" :key="s.name" class="school" @click="goGroups(s)">
              <view class="school-top">
                <text class="school-name">{{ s.name }}</text>
                <view class="school-right">
                  <wd-tag v-if="s.nature" type="default" plain>{{ s.nature }}</wd-tag>
                  <text class="chev">专业组 ›</text>
                </view>
              </view>
              <text class="school-meta">{{ s.province }}<text v-if="s.city"> · {{ s.city }}</text><text v-if="s.category"> · {{ s.category }}</text></text>
              <text v-if="s.min_score" class="school-line">去年最低 {{ s.min_score }} 分<text v-if="s.min_rank"> · 位次 {{ s.min_rank }}</text><text v-if="s.line_year">（{{ s.line_year }} 年投档线）</text></text>
            </view>
          </view>
          <text v-if="noLine(t)" class="basis">本档还没有院校投档线，行内不显示「去年最低」，只按层次归类。</text>
          <text v-if="isShared(t)" class="small">院校已在上方「{{ t.pool_shared_with }}」档展示（同一院校池）。</text>
          <text v-if="isEmptyTier(t)" class="small">该层次暂无匹配院校（请放宽筛选条件）。</text>
        </view>
      </view>

      <view class="section" v-if="hasResult">
        <view class="actions">
          <wd-button block plain @click="goPlan">生成志愿表（可打印 / 导出 PDF）</wd-button>
        </view>
        <!-- S5-D 志愿表发现性：存在本机草稿时显式入口 + 红点提示 -->
        <view class="draft-row" v-if="hasDraft" @click="openPlan">
          <text class="draft-dot"></text>
          <text class="draft-txt">你有一份志愿表草稿，点击查看 ›</text>
        </view>
        <view class="notes">
          <text v-for="(n, i) in result.notes" :key="i" class="note">· {{ n }}</text>
        </view>
      </view>
    </view>
    <wd-toast></wd-toast>
  </wd-config-provider>
</template>

<script setup>
import { computed, reactive, ref } from "vue";
import { onLoad, onShow } from "@dcloudio/uni-app";
import { useToast } from "wot-design-uni";
import { MAJORS } from "@/utils/content.js";
import { api } from "@/utils/api.js";
import { PLAN_KEY, buildPlan } from "@/utils/plan.js";
import { themeVars } from "@/utils/theme.js";
import { applyProfile, saveFromForm } from "@/utils/profile.js";

const toast = useToast();

const provinces = ["北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆"];
const subjects = ["物理类", "历史类", "综合/未改革"];
const NO_MAJOR = "不限（用省份基线）";
const majorOptions = [NO_MAJOR].concat(MAJORS.map((m) => m.name));

const f = reactive({ province: "", subject: "", user_rank: "", major: NO_MAJOR });
const result = ref(null);
const err = ref("");
const loading = ref(false);

const hasResult = computed(() => {
  const r = result.value;
  return !!(r && r.tiers && r.tiers.length);
});

// S5-D：本机是否存在志愿表草稿（决定推荐页是否展示常驻入口 + 红点）
const hasDraft = computed(() => !!uni.getStorageSync(PLAN_KEY));
const sourceLabel = computed(() => {
  const ds = result.value ? result.value.data_source : "";
  if (ds === "demo") return "演示数据（示意，非真实录取信息）";
  if (ds === "official_overlay") return "31 省官方省控线（2022–2026）+ 估算基线";
  if (ds === "real") return "gaokao-advisor 估算基线";
  return "参数化样例";
});

onLoad((q) => {
  // 优先带入全局档案（「我能上哪」已写入），再允许外链参数覆盖
  Object.assign(f, applyProfile(f));
  if (q && q.province) f.province = decodeURIComponent(q.province);
  if (q && q.subject) f.subject = decodeURIComponent(q.subject);
  if (q && q.user_rank) f.user_rank = decodeURIComponent(q.user_rank);
});

// tab 页再次进入时同步档案（从「我能上哪 / 诊断」switchTab 过来，条件已在 profile 里）
onShow(() => {
  Object.assign(f, applyProfile(f));
});

function levelType(level) {
  if (level === "冲") return "warning";
  if (level === "稳") return "primary";
  if (level === "保") return "success";
  return "info";
}

// 模板里不写复合表达式（Vue in-DOM 编译器对 && 支持不稳），统一抽成方法
function hasSchools(t) {
  return !!(t && t.schools && t.schools.length);
}
function noLine(t) {
  return hasSchools(t) && !t.school_line_hits;
}
function isShared(t) {
  return !hasSchools(t) && !!t.pool_shared_with;
}
function isEmptyTier(t) {
  return !hasSchools(t) && !t.pool_shared_with;
}

function dsType(ds) {
  return ds === "official" ? "success" : "warning";
}

// 官方值可能是往年沿用（carried），必须把真实来源年份显示出来，
// 否则「2026 官方 532 分」其实是 2024 特控线，属于误导。
function sourceTag(t) {
  if (!t || t.data_source !== "official") return "估算";
  if (t.carried && t.source_year) return "官方·沿用" + t.source_year;
  return "官方";
}

async function run() {
  err.value = "";
  if (!f.province || !f.subject || !f.user_rank) {
    toast.show("请先填写省份 / 科类 / 位次");
    return;
  }
  const rank = Number(f.user_rank);
  if (!(rank > 0)) {
    toast.show("位次必须为正整数");
    return;
  }
  loading.value = true;
  try {
    const params = { province: f.province, subject: f.subject, user_rank: rank, limit: 8 };
    if (f.major !== NO_MAJOR) params.major_name = f.major;
    result.value = await api.recommendSchools(params);
    savePlan();
    // 把条件写入全局档案，便于「志愿表 / 查专业」自动带齐
    saveFromForm(f);
  } catch (e) {
    err.value = e && e.message ? e.message : "数据服务未连接，可在「我的」开启演示模式先体验";
  } finally {
    loading.value = false;
  }
}

// 落盘本机的「志愿表草稿」，供导出页读取（仅存本机，不上传）
function savePlan() {
  const p = buildPlan(result.value);
  if (p) uni.setStorageSync(PLAN_KEY, p);
}

function goPlan() {
  uni.switchTab({ url: "/pages/plan/plan" });
}

// S5-D：直接打开已有志愿表草稿（不覆盖、不重新生成）
function openPlan() {
  uni.switchTab({ url: "/pages/plan/plan" });
}

// 点击院校 → 查看该校「院校专业组」结构（按当前选科）
function goGroups(s) {
  const subj = result.value ? result.value.subject : f.subject;
  const q = `university=${encodeURIComponent(s.name)}&subject=${encodeURIComponent(subj)}`;
  uni.navigateTo({ url: `/pages/majorGroup/majorGroup?${q}` });
}
</script>

<style scoped>
.page { padding: 24rpx 24rpx 60rpx; }
.hero { padding: 16rpx 8rpx 24rpx; }
.h1 { font-size: 40rpx; font-weight: 700; color: #ffd24d; }
.sub { display: block; margin-top: 10rpx; font-size: 24rpx; color: #8a909c; line-height: 1.6; }

.section { margin-bottom: 24rpx; }
.section-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14rpx; }
.h3 { font-size: 30rpx; font-weight: 600; color: #e6e8ec; }
.bk-sub { font-size: 21rpx; color: #6b7280; }
.auth-rcmd { color: #f0ad4e; }
.actions { display: flex; flex-direction: column; gap: 16rpx; margin-top: 18rpx; }
.small { font-size: 21rpx; color: #6b7280; display: block; margin-top: 10rpx; line-height: 1.6; }
.err { font-size: 22rpx; color: #ff6b6b; display: block; margin-top: 12rpx; line-height: 1.5; }

.sum { display: flex; flex-wrap: wrap; gap: 12rpx; }
.sum-i { font-size: 22rpx; padding: 4rpx 16rpx; border-radius: 999rpx; border: 1px solid #2a2e37; }
.sum-i.reach { color: #f0ad4e; }
.sum-i.match { color: #6db3f2; }
.sum-i.safe { color: #5fd87f; }
.sum-i.none { color: #6b7280; }

.tier-card { border: 1px solid #22262e; border-radius: 16rpx; padding: 20rpx; margin-bottom: 18rpx; }
.tier-head { display: flex; align-items: center; gap: 12rpx; margin-bottom: 8rpx; }
.tier-name { font-size: 30rpx; font-weight: 600; color: #e6e8ec; }
.tier-meta { display: block; font-size: 22rpx; color: #8a909c; line-height: 1.6; }
.basis { display: block; font-size: 20rpx; color: #6b7280; margin-top: 4rpx; line-height: 1.5; }

.schools { margin-top: 14rpx; }
.school { padding: 12rpx 0; border-top: 1px solid #1c2027; }
.school-top { display: flex; align-items: center; justify-content: space-between; }
.school-right { display: flex; align-items: center; gap: 10rpx; }
.chev { font-size: 20rpx; color: #6db3f2; }
.school-name { font-size: 25rpx; color: #c7ccd4; }
.school-meta { display: block; font-size: 20rpx; color: #6b7280; margin-top: 4rpx; }
.school-line { display: block; font-size: 20rpx; color: #5fd87f; margin-top: 4rpx; }
.school-line.muted { color: #5a606b; }

.notes { margin-top: 16rpx; }
.note { display: block; font-size: 20rpx; color: #f0ad4e; line-height: 1.6; }

/* S5-D 志愿表草稿常驻入口 */
.draft-row { display: flex; align-items: center; margin-top: 16rpx; padding: 14rpx 18rpx; border: 1px dashed #3a3f48; border-radius: 12rpx; background: rgba(95, 216, 127, 0.05); }
.draft-dot { width: 14rpx; height: 14rpx; border-radius: 50%; background: #e5484d; margin-right: 12rpx; box-shadow: 0 0 8rpx 1rpx rgba(229, 72, 77, 0.6); }
.draft-txt { font-size: 22rpx; color: #c7ccd4; }
</style>
