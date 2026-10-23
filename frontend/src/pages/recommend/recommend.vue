<template>
  <wd-config-provider :theme="$theme.mode" :theme-vars="themeVars" :style="$theme.style">
    <view class="page">
      <!-- 吸顶条件条：出过结果后不再让人滚回顶部找输入框 -->
      <view v-if="hasResult" class="sticky-bar">
        <text class="sticky-cond">{{ f.province }} · {{ f.subject }} · {{ f.user_rank }} 名</text>
        <view class="sticky-act" @click="editConditions">
          <app-icon name="refresh" color="#8f96a2" :size="26"></app-icon>
          <text class="sticky-act-t">改条件</text>
        </view>
      </view>

      <view v-if="!hasResult" class="xf-hero">
        <view class="xf-tile xf-tile--gold">
          <app-icon name="school" color="#ffd24d" :size="36"></app-icon>
        </view>
        <view class="xf-hero-body">
          <text class="xf-h1">能上哪些学校</text>
          <text class="xf-sub">按你的位次分档：冲、稳、保各给一批院校，标出去年最低分。</text>
        </view>
      </view>

      <!-- 输入 -->
      <view v-if="!hasResult" class="xf-card input-card">
        <view class="section-head">
          <text class="xf-h3">输入你的条件</text>
          <view class="xf-chip">
            <app-icon name="layers" color="#8f96a2" :size="22"></app-icon>
            <text>教育部 2868 所</text>
          </view>
        </view>

        <view class="fields">
          <wd-picker v-model="f.province" label="高考省份" :columns="provinces" placeholder="请选择" label-width="30%"></wd-picker>
          <wd-picker v-model="f.subject" label="选科方向" :columns="subjects" placeholder="请选择" label-width="30%"></wd-picker>
          <wd-input v-model="f.user_rank" label="高考位次" type="number" placeholder="如：40000" label-width="30%"></wd-input>
          <wd-picker v-model="f.major" label="目标专业" :columns="majorOptions" placeholder="请选择" label-width="30%"></wd-picker>
        </view>

        <wd-button type="primary" block size="large" :loading="loading" @click="run">
          生成院校推荐
        </wd-button>
        <text v-if="err" class="err">{{ err }}</text>

        <view v-if="loading" class="skel">
          <view class="xf-skel xf-skel-line xf-skel-line--w40"></view>
          <view class="xf-skel xf-skel-line"></view>
          <view class="xf-skel xf-skel-line xf-skel-line--w70"></view>
        </view>
      </view>

      <!-- 结果 -->
      <view v-if="hasResult" class="res xf-fade">
        <!-- 汇总：四个数一眼看完 -->
        <view class="sum-card">
          <view class="sum-row">
            <view class="sum-item">
              <text class="sum-n reach">{{ result.summary.reach }}</text>
              <text class="sum-l">冲</text>
            </view>
            <view class="sum-item">
              <text class="sum-n match">{{ result.summary.match }}</text>
              <text class="sum-l">稳</text>
            </view>
            <view class="sum-item">
              <text class="sum-n safe">{{ result.summary.safe }}</text>
              <text class="sum-l">保</text>
            </view>
            <view class="sum-item">
              <text class="sum-n none">{{ result.summary.unreachable }}</text>
              <text class="sum-l">不可及</text>
            </view>
          </view>
          <view class="sum-foot">
            <view :class="['xf-chip', 'xf-chip--' + cred.cls]">
              <app-icon :name="cred.icon" :color="cred.color" :size="22"></app-icon>
              <text>{{ cred.label }}</text>
            </view>
            <text class="sum-source">{{ sourceLabel }}</text>
          </view>
        </view>

        <!-- S5-A：校线权威声明（真实抓取 ≠ 官方） -->
        <view v-if="result && result.school_line_hits" class="notice notice--real">
          <app-icon name="info" color="#6db3f2" :size="28"></app-icon>
          <text class="notice-t">其中 {{ result.school_line_hits }} 所院校已匹配投档线（行内标「去年最低」）；当前为真实抓取结果，非考试院官方发布。</text>
        </view>
        <view v-else-if="result" class="notice">
          <app-icon name="info" color="#8f96a2" :size="28"></app-icon>
          <text class="notice-t">该省尚未导入院校级投档线，院校行不含「去年最低」。可在管理端「校线导入」上传官方原表后重新生成。</text>
        </view>

        <!-- 档位卡：左侧色条 + 档位图标，扫读即分档 -->
        <view v-for="t in result.tiers" :key="t.tier" class="tier-card" :class="'tier-card--' + stripCls(t.level)">
          <view class="tier-head">
            <view class="xf-tile" :class="'xf-tile--' + stripCls(t.level)">
              <app-icon :name="levelIcon(t.level)" :color="levelColor(t.level)" :size="30"></app-icon>
            </view>
            <view class="tier-head-body">
              <text class="tier-name">{{ t.tier }}</text>
              <text class="tier-meta">门槛 ≈ {{ t.min_score }} 分 · 位次 {{ t.min_rank }}</text>
            </view>
            <view class="xf-chip" :class="'xf-chip--' + stripCls(t.level)">{{ t.level }}</view>
          </view>

          <text class="tier-pool">{{ t.pool_label }}（共 {{ t.pool_total }} 所，展示前 {{ t.schools.length }} 所）</text>

          <view v-if="t.schools.length" class="schools">
            <view v-for="s in t.schools" :key="s.name" class="school" @click="goGroups(s)">
              <view class="school-top">
                <text class="school-name">{{ s.name }}</text>
                <view class="school-right">
                  <text v-if="s.nature" class="school-nature">{{ s.nature }}</text>
                  <app-icon name="chevron-right" color="#6f7683" :size="24"></app-icon>
                </view>
              </view>
              <text class="school-meta">{{ s.province }}<text v-if="s.city"> · {{ s.city }}</text><text v-if="s.category"> · {{ s.category }}</text></text>
              <view v-if="s.min_score" class="school-line">
                <app-icon name="check" color="#5fd87f" :size="22"></app-icon>
                <text class="school-line-t">去年最低 {{ s.min_score }} 分<text v-if="s.min_rank"> · 位次 {{ s.min_rank }}</text><text v-if="s.line_year">（{{ s.line_year }} 年投档线）</text></text>
              </view>
            </view>
          </view>

          <text v-if="noLine(t)" class="tier-tip">本档还没有院校投档线，只按层次归类，不显示「去年最低」。</text>
          <text v-if="isShared(t)" class="tier-tip">院校已在上方「{{ t.pool_shared_with }}」档展示（同一院校池）。</text>
          <text v-if="isEmptyTier(t)" class="tier-tip">该层次暂无匹配院校，可放宽目标专业再试。</text>
        </view>

        <!-- 下一步 -->
        <view class="actions">
          <view class="xf-action xf-action--primary" @click="goPlan">
            <view class="xf-tile xf-tile--gold">
              <app-icon name="list" color="#ffd24d" :size="32"></app-icon>
            </view>
            <view class="xf-action-label">
              <text class="xf-action-title">生成志愿表</text>
              <text class="xf-action-desc">可继续编辑、复制、打印或导出 PDF</text>
            </view>
            <app-icon name="chevron-right" color="#c9a53a" :size="26"></app-icon>
          </view>
        </view>

        <view class="draft-row" v-if="hasDraft" @click="openPlan">
          <text class="draft-dot"></text>
          <text class="draft-txt">你有一份志愿表草稿，点击继续编辑</text>
          <app-icon name="chevron-right" color="#5fd87f" :size="24"></app-icon>
        </view>

        <view v-if="result.notes && result.notes.length" class="notes">
          <text v-for="(n, i) in result.notes" :key="i" class="note">· {{ n }}</text>
        </view>
      </view>
    </view>
    <wd-toast></wd-toast>
  </wd-config-provider>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { onLoad, onShow } from "@dcloudio/uni-app";
import { useToast } from "wot-design-uni";
import { MAJORS, ensureContent } from "@/utils/content";
import { api } from "@/utils/api";
import { PLAN_KEY, buildPlan } from "@/utils/plan";
import { themeVars, credMeta, levelColor, levelIcon } from "@/utils/theme";
import { applyProfile, saveFromForm } from "@/utils/profile";

const toast = useToast();

const provinces = ["北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆"];
const subjects = ["物理类", "历史类", "综合/未改革"];
const NO_MAJOR = "不限（用省份基线）";
const majorOptions = ref<any[]>([]);

const f = reactive({ province: "", subject: "", user_rank: "", major: NO_MAJOR });
const result = ref(null);
const err = ref("");
const loading = ref(false);

const hasResult = computed(() => {
  const r = result.value;
  return !!(r && r.tiers && r.tiers.length);
});

// P2 信任呈现：口径统一走 theme.credMeta
const cred = computed(() => credMeta(result.value && result.value.data_source));

// 档位 → CSS 色条/芯片后缀（冲/稳/保/其它）
function stripCls(level: any) {
  if (level === "冲") return "reach";
  if (level === "稳") return "match";
  if (level === "保") return "safe";
  return "est";
}

// S5-D：本机是否存在志愿表草稿（决定推荐页是否展示常驻入口 + 红点）
const hasDraft = computed(() => !!uni.getStorageSync(PLAN_KEY));
const sourceLabel = computed(() => {
  const ds = result.value ? result.value.data_source : "";
  if (ds === "demo") return "演示数据（示意，非真实录取信息）";
  if (ds === "official_overlay") return "31 省官方省控线（2022–2026）+ 估算基线";
  if (ds === "real") return "gaokao-advisor 估算基线";
  return "参数化样例";
});

onLoad(async (q) => {
  await ensureContent();
  majorOptions.value = [NO_MAJOR].concat(MAJORS.map((m) => m.name));
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

// 模板里不写复合表达式（Vue in-DOM 编译器对 && 支持不稳），统一抽成方法
function hasSchools(t: any) {
  return !!(t && t.schools && t.schools.length);
}
function noLine(t: any) {
  return hasSchools(t) && !t.school_line_hits;
}
function isShared(t: any) {
  return !hasSchools(t) && !!t.pool_shared_with;
}
function isEmptyTier(t: any) {
  return !hasSchools(t) && !t.pool_shared_with;
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
  } catch (e: any) {
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

// 回到条件输入（吸顶条上的「改条件」）
function editConditions() {
  result.value = null;
  err.value = "";
}

function goPlan() {
  uni.switchTab({ url: "/pages/plan/plan" });
}

// S5-D：直接打开已有志愿表草稿（不覆盖、不重新生成）
function openPlan() {
  uni.switchTab({ url: "/pages/plan/plan" });
}

// 点击院校 → 查看该校「院校专业组」结构（按当前选科）
function goGroups(s: any) {
  const subj = result.value ? result.value.subject : f.subject;
  const q = `university=${encodeURIComponent(s.name)}&subject=${encodeURIComponent(subj)}`;
  uni.navigateTo({ url: `/subpackages/majorGroup/majorGroup?${q}` });
}
</script>

<style scoped>
.page { padding: 24rpx 24rpx 80rpx; min-height: 100vh; background: var(--xf-bg); }

/* 吸顶条件条 */
.sticky-bar {
  position: sticky; top: 0; z-index: 20;
  display: flex; align-items: center; justify-content: space-between;
  margin: -24rpx -24rpx 20rpx; padding: 18rpx 24rpx;
  background: rgba(15, 17, 21, 0.94);
  border-bottom: 1rpx solid var(--xf-line);
  backdrop-filter: blur(8px);
}
.sticky-cond { font-size: 23rpx; color: var(--xf-text-2); font-variant-numeric: tabular-nums; }
.sticky-act { display: flex; align-items: center; gap: 8rpx; min-height: 64rpx; padding-left: 12rpx; }
.sticky-act-t { font-size: 23rpx; color: var(--xf-text-3); }

/* 输入卡 */
.input-card { margin-top: 8rpx; }
.section-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14rpx; }
.fields { margin: 6rpx 0 26rpx; border: 1rpx solid var(--xf-line); border-radius: var(--xf-r-sm); overflow: hidden; }
.err { display: block; margin-top: 16rpx; font-size: 23rpx; color: var(--xf-danger-text); line-height: 1.6; }
.skel { margin-top: 28rpx; }

/* 汇总 */
.sum-card {
  padding: 24rpx 22rpx 20rpx; border-radius: var(--xf-r-lg);
  background: var(--xf-surface); border: 1rpx solid var(--xf-line);
}
.sum-row { display: flex; }
.sum-item { flex: 1; text-align: center; border-right: 1rpx solid var(--xf-line-soft); }
.sum-item:last-child { border-right: none; }
.sum-n { display: block; font-size: 44rpx; font-weight: 700; line-height: 1.2; font-variant-numeric: tabular-nums; }
.sum-n.reach { color: var(--xf-reach); }
.sum-n.match { color: var(--xf-match); }
.sum-n.safe { color: var(--xf-safe); }
.sum-n.none { color: var(--xf-text-4); }
.sum-l { display: block; margin-top: 4rpx; font-size: 21rpx; color: var(--xf-text-3); }
.sum-foot { display: flex; align-items: center; gap: 12rpx; margin-top: 20rpx; padding-top: 18rpx; border-top: 1rpx solid var(--xf-line-soft); }
.sum-source { flex: 1; font-size: 21rpx; color: var(--xf-text-4); line-height: 1.5; }

/* 声明条 */
.notice { display: flex; align-items: flex-start; gap: 12rpx; margin-top: 16rpx; padding: 16rpx 18rpx; border-radius: var(--xf-r-sm); background: rgba(143, 150, 162, 0.08); border: 1rpx solid var(--xf-line); }
.notice--real { background: rgba(109, 179, 242, 0.08); border-color: rgba(109, 179, 242, 0.28); }
.notice-t { flex: 1; font-size: 21rpx; color: var(--xf-text-3); line-height: 1.65; }

/* 档位卡 */
.tier-card {
  margin-top: 18rpx; padding: 22rpx;
  background: var(--xf-surface);
  border: 1rpx solid var(--xf-line);
  /* 左侧语义色条：用局部变量承接，避免被上面的 border 简写覆盖 */
  border-left: 7rpx solid var(--tier-c, var(--xf-line));
  border-radius: 0 var(--xf-r-md) var(--xf-r-md) 0;
}
.tier-card--reach { --tier-c: var(--xf-reach); }
.tier-card--match { --tier-c: var(--xf-match); }
.tier-card--safe { --tier-c: var(--xf-safe); }
.tier-card--est { --tier-c: var(--xf-text-4); }
.tier-head { display: flex; align-items: center; gap: 16rpx; }
.tier-head-body { flex: 1; min-width: 0; }
.tier-name { display: block; font-size: 30rpx; font-weight: 700; color: var(--xf-text); }
.tier-meta { display: block; margin-top: 4rpx; font-size: 21rpx; color: var(--xf-text-3); font-variant-numeric: tabular-nums; }
.tier-pool { display: block; margin-top: 14rpx; font-size: 21rpx; color: var(--xf-text-4); line-height: 1.6; }
.tier-tip { display: block; margin-top: 12rpx; font-size: 21rpx; color: var(--xf-text-4); line-height: 1.6; }

/* 院校行 */
.schools { margin-top: 8rpx; }
.school { padding: 16rpx 0; min-height: 88rpx; border-top: 1rpx solid var(--xf-line-soft); }
.school:active { background: rgba(255, 255, 255, 0.02); }
.school-top { display: flex; align-items: center; justify-content: space-between; gap: 12rpx; }
.school-right { display: flex; align-items: center; gap: 10rpx; }
.school-nature { font-size: 19rpx; color: var(--xf-text-3); border: 1rpx solid var(--xf-line); border-radius: 6rpx; padding: 2rpx 8rpx; }
.school-name { font-size: 26rpx; color: var(--xf-text); font-weight: 600; }
.school-meta { display: block; font-size: 20rpx; color: var(--xf-text-4); margin-top: 5rpx; }
.school-line { display: flex; align-items: center; gap: 8rpx; margin-top: 6rpx; }
.school-line-t { font-size: 21rpx; color: var(--xf-safe); }

/* 动作 */
.actions { display: flex; flex-direction: column; gap: 14rpx; margin-top: 30rpx; }

.notes { margin-top: 22rpx; }
.note { display: block; font-size: 21rpx; color: var(--xf-demo); line-height: 1.7; }

/* 草稿入口 */
.draft-row { display: flex; align-items: center; gap: 10rpx; margin-top: 18rpx; padding: 18rpx; min-height: 88rpx; border: 1rpx dashed rgba(95, 216, 127, 0.45); border-radius: var(--xf-r-md); background: rgba(95, 216, 127, 0.05); }
.draft-dot { width: 14rpx; height: 14rpx; border-radius: 50%; background: var(--xf-danger); margin-right: 6rpx; box-shadow: 0 0 8rpx 1rpx rgba(229, 72, 77, 0.6); }
.draft-txt { flex: 1; font-size: 23rpx; color: var(--xf-text-2); }
</style>
