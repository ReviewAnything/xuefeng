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
        <view class="safe-net" :class="breach.cls">
          <view class="safe-head">
            <text class="safe-dot" :class="breach.cls"></text>
            <text class="safe-title">保底安全网</text>
            <text class="safe-count" :class="breach.cls">{{ breach.text }}</text>
          </view>
          <text class="safe-desc">{{ breach.desc }}</text>
          <wd-button v-if="breach.cls === 'danger'" type="error" block size="small"
                     class="safe-patch no-print" :loading="patching" @click="patchSafe">
            一键补位：拉取更低层次兜底院校
          </wd-button>
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
                <text class="row-name">{{ r.name }}<text v-if="rowBreach(r) === 'breach'" class="row-breach">失守</text></text>
                <text class="row-meta">{{ r.tier }} · {{ r.province }}<text v-if="r.line"> · 去年 {{ r.line }} 分<text v-if="r.line_rank"> / 位次 {{ r.line_rank }}</text><text v-if="r.line_year">（{{ r.line_year }}）</text></text></text>
                <text v-if="rowBreach(r) === 'breach'" class="row-breach-tip">你的位次 {{ plan.user_rank }} 比该校最低投档位次 {{ r.line_rank }} 更靠后，够不上</text>
              </view>
            </view>
            <input class="row-major" v-model="r.major" placeholder="拟报专业" />
          </view>
          <text v-if="isNoRow(g)" class="small">该档暂无院校，可回到推荐页放宽条件。</text>
        </view>
      </view>

      <view v-if="hasPlan" class="section">
        <text class="small">已填拟报专业 {{ stats.filled }} / {{ stats.total }}</text>
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
import { computed, ref, watch } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { useToast } from "wot-design-uni";
import { themeVars } from "@/utils/theme.js";
import { api } from "@/utils/api.js";
import { PLAN_KEY, applyMajors, appendSafeSchools, breachStats, breachStatus, buildPlanText, collectMajors, fillStats, flattenPlan, formatTime, groupRows, selectBackstops } from "@/utils/plan.js";

const toast = useToast();
const plan = ref(null);
const rows = ref([]);
const patching = ref(false);

const hasPlan = computed(() => !!plan.value);
const isEmpty = computed(() => !plan.value);
const groups = computed(() => groupRows(rows.value));
const stats = computed(() => fillStats(rows.value));
const timeLabel = computed(() => formatTime(plan.value && plan.value.at));

// S4 验收点：保底安全网红灯数可见。
// cls —— danger(有失守) / ok(全部核验且安全) / muted(无数据未核验)
// text —— 红灯计数文案；desc —— 处置建议
const breach = computed(() => {
  const s = breachStats(plan.value, rows.value);
  if (s.breach > 0) {
    return {
      cls: "danger",
      text: `保底失守 ${s.breach} 所`,
      desc: `${s.breach} 所「保底」院校的最低投档位次比你更靠前，按当前位次实际够不上。请补充更低层次的保底院校，或下调保底预期，避免滑档。`,
    };
  }
  if (s.covered > 0) {
    return {
      cls: "ok",
      text: `保底安全（${s.covered} 所已核验）`,
      desc: "所有带投档线的保底院校，你的位次均优于其最低投档位次。",
    };
  }
  return {
    cls: "muted",
    text: `保底未核验（${s.total} 所缺投档线）`,
    desc: "保底院校暂无院校级投档线，无法判定是否真能兜底；请以本省考试院/院校招生网公布的往年投档位次为准。",
  };
});

function rowBreach(r) {
  return breachStatus(plan.value && plan.value.user_rank, r);
}

onLoad(() => {
  const p = uni.getStorageSync(PLAN_KEY);
  if (!p) return;
  plan.value = p;
  // 回填上次手填的拟报专业，避免离开页面后全部丢失
  rows.value = applyMajors(flattenPlan(p), p.majors);
});

// 拟报专业改动即写入本机草稿（仅本地存储，不上传）
watch(rows, () => {
  if (!plan.value) return;
  try {
    uni.setStorageSync(PLAN_KEY, { ...plan.value, majors: collectMajors(rows.value) });
  } catch (e) {
    // 存储失败（配额/隐私模式）不应打断填写
  }
}, { deep: true });

function levelClass(level) {
  if (level === "冲") return "reach";
  if (level === "稳") return "match";
  return "safe";
}

function isNoRow(g) {
  return g.rows.length === 0;
}

function buildText() {
  return buildPlanText(plan.value, groups.value, timeLabel.value);
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

// S5-C 保底失守一键补位：拉取更低层次、用户位次可稳够的兜底院校并入「保」档。
// 候选筛选交给纯函数 selectBackstops（只挑 min_rank < 用户位次、不会再次失守的院校），
// 去重+并入交给 appendSafeSchools。
async function patchSafe() {
  if (patching.value || !plan.value) return;
  patching.value = true;
  try {
    const rec = await api.recommendSchools({
      province: plan.value.province, subject: plan.value.subject,
      user_rank: plan.value.user_rank, limit: 50,
    });
    const picks = selectBackstops(rec, plan.value.user_rank, 6);
    if (!picks.length) {
      toast.show("暂无可补位的更低层次兜底院校（可能该省缺院校投档线）");
      return;
    }
    const next = appendSafeSchools(JSON.parse(JSON.stringify(plan.value)), picks);
    plan.value = next;
    rows.value = applyMajors(flattenPlan(next), next.majors || collectMajors(rows.value));
    uni.setStorageSync(PLAN_KEY, next);
    toast.show(`已补位 ${picks.length} 所兜底院校到「保」档`);
  } catch (e) {
    toast.show("没连上服务，重试一次");
  } finally {
    patching.value = false;
  }
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

.safe-net { border-radius: 16rpx; padding: 20rpx; border: 1px solid #22262e; }
.safe-net.danger { border-color: #e5484d; background: rgba(229, 72, 77, 0.12); }
.safe-net.ok { border-color: #2f7d4f; background: rgba(95, 216, 127, 0.08); }
.safe-net.muted { border-color: #3a3f48; background: rgba(138, 144, 156, 0.06); }
.safe-head { display: flex; align-items: center; }
.safe-dot { width: 18rpx; height: 18rpx; border-radius: 50%; margin-right: 12rpx; flex: 0 0 auto; }
.safe-dot.danger { background: #e5484d; box-shadow: 0 0 10rpx 2rpx rgba(229, 72, 77, 0.6); animation: blink 1.2s infinite; }
.safe-dot.ok { background: #5fd87f; }
.safe-dot.muted { background: #6b7280; }
.safe-title { font-size: 26rpx; font-weight: 600; color: #c7ccd4; margin-right: auto; }
.safe-count { font-size: 26rpx; font-weight: 700; }
.safe-count.danger { color: #ff6b6b; }
.safe-count.ok { color: #5fd87f; }
.safe-count.muted { color: #8a909c; }
.safe-desc { display: block; margin-top: 10rpx; font-size: 21rpx; color: #9aa0aa; line-height: 1.6; }
.safe-patch { margin-top: 16rpx; }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }

.row-breach { font-size: 18rpx; color: #fff; background: #e5484d; border-radius: 6rpx; padding: 1rpx 8rpx; margin-left: 10rpx; vertical-align: middle; }
.row-breach-tip { display: block; font-size: 19rpx; color: #ff8787; margin-top: 3rpx; line-height: 1.5; }

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
