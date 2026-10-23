<template>
  <wd-config-provider :theme="$theme.mode" :theme-vars="themeVars" :style="$theme.style">
    <view class="page">
      <!-- 输入：三个字段，一屏，一个问题 -->
      <view v-if="!r" class="ask">
        <view class="ask-mark">
          <view class="xf-tile xf-tile--gold">
            <app-icon name="target" color="#ffd24d" :size="40"></app-icon>
          </view>
        </view>
        <text class="ask-h1">你多少名？</text>
        <text class="ask-sub">省份、科类、位次。输完直接给你结论。</text>

        <view class="fields">
          <wd-picker v-model="f.province" label="省份" :columns="provinces"
                     placeholder="选择" label-width="20%" />
          <wd-picker v-model="f.subject" label="科类" :columns="subjects"
                     placeholder="选择" label-width="20%" />
          <wd-input v-model="f.rank" label="位次" type="number"
                    placeholder="如 40000" label-width="20%" />
        </view>

        <wd-button type="primary" block size="large" :loading="loading" @click="run">
          出结论
        </wd-button>
        <text v-if="err" class="err">{{ err }}</text>

        <!-- 骨架屏：等结果时给出「正在算什么」的形状，而不是干等 -->
        <view v-if="loading" class="skel-card xf-card">
          <view class="xf-skel xf-skel-line xf-skel-line--w40"></view>
          <view class="xf-skel xf-skel-line xf-skel-line--w70"></view>
          <view class="xf-skel xf-skel-line"></view>
        </view>

        <view class="ask-foot">
          <view class="ask-link" @click="goDiagnose">
            <app-icon name="bulb" color="#8f96a2" :size="28"></app-icon>
            <text class="ask-link-t">说不清自己要什么？先做八连问</text>
            <app-icon name="chevron-right" color="#6f7683" :size="24"></app-icon>
          </view>
        </view>
      </view>

      <!-- 结论：一张主结果卡，然后是三个动作 -->
      <view v-else class="res xf-fade">
        <view v-if="offlineHint" class="offline-tip">
          <app-icon name="alert" color="#f0ad4e" :size="28"></app-icon>
          <text class="offline-tip-t">{{ offlineHint }}</text>
        </view>

        <view class="topbar">
          <text class="cond">{{ r.province }} · {{ r.subject }} · {{ r.user_rank }} 名</text>
          <view class="topbar-right">
            <view :class="['xf-chip', 'xf-chip--' + cred.cls]">
              <app-icon :name="cred.icon" :color="cred.color" :size="22"></app-icon>
              <text>{{ cred.label }}</text>
            </view>
            <text class="lk" @click="reset">改条件</text>
          </view>
        </view>

        <!-- 主结果卡：结论一句话 + 位次尺，放同一张卡里，视线不打断 -->
        <view class="hero-card">
          <text class="headline">{{ r.headline }}</text>

          <view class="ruler">
            <view class="zones">
              <view v-for="z in ruler.zones" :key="z.key" class="zone" :class="z.state"
                    :style="{ left: z.left + '%', width: z.width + '%' }"></view>
              <view class="me" :style="{ left: ruler.me + '%' }">
                <text class="me-label">你</text>
                <view class="me-dot"></view>
              </view>
            </view>
            <view class="ticks">
              <text v-for="g in ruler.rows" :key="g.tier" class="tick"
                    :style="{ left: g.at + '%' }">{{ shortLabel(g.label) }}</text>
            </view>
          </view>
        </view>

        <!-- 门槛明细：一行一档，右对齐位次，一眼比出差距 -->
        <view class="xf-card ladder">
          <view v-for="g in ruler.rows" :key="g.tier" class="lg">
            <view class="lg-dot" :class="g.state"></view>
            <text class="lg-k">{{ g.label }}</text>
            <text class="lg-r">{{ g.min_rank }} 名</text>
            <text class="lg-g" :class="g.state">{{ g.gapText }}</text>
          </view>
          <text v-if="!ruler.rows.length" class="xf-tiny">该省暂无可比门槛，看下方区间即可。</text>
        </view>

        <!-- 三个判断（定位 / 主攻 / 保底） -->
        <view class="stance">
          <view v-for="(s, i) in r.stance" :key="s.k" class="st">
            <view class="xf-tile" :class="'xf-tile--' + stanceTone(i)">
              <app-icon :name="stanceIcon(i)" :color="stanceColor(i)" :size="30"></app-icon>
            </view>
            <view class="st-body">
              <text class="st-k">{{ s.k }}</text>
              <text class="st-t">{{ s.t }}</text>
            </view>
          </view>
        </view>

        <view v-if="r.guard" class="guard">
          <app-icon name="alert" color="#ff8787" :size="30"></app-icon>
          <text class="guard-t">{{ r.guard }}</text>
        </view>

        <view v-if="r.bands.length" class="bands">
          <text class="blk-title">照这个区间去筛学校</text>
          <view v-for="b in r.bands" :key="b.key" class="band" :class="'band--' + b.key">
            <view class="xf-tile" :class="'xf-tile--' + b.key">
              <app-icon :name="levelIcon(b.key)" :color="levelColor(b.key)" :size="28"></app-icon>
            </view>
            <text class="band-k">{{ b.label }}</text>
            <text class="band-v">{{ b.from }} – {{ b.to }} 名</text>
          </view>
        </view>

        <!-- 下一步：主次分明的动作行，不再是三个等权按钮 -->
        <view class="actions">
          <view class="xf-action xf-action--primary" @click="goPlan">
            <view class="xf-tile xf-tile--gold">
              <app-icon name="list" color="#ffd24d" :size="32"></app-icon>
            </view>
            <view class="xf-action-label">
              <text class="xf-action-title">{{ making ? "正在生成…" : "生成我的志愿表" }}</text>
              <text class="xf-action-desc">按冲稳保排好顺序，可改可导出</text>
            </view>
            <app-icon name="chevron-right" color="#c9a53a" :size="26"></app-icon>
          </view>

          <view class="xf-action" @click="goRecommend">
            <view class="xf-tile">
              <app-icon name="school" color="#c2c8d0" :size="32"></app-icon>
            </view>
            <view class="xf-action-label">
              <text class="xf-action-title">先看院校池</text>
              <text class="xf-action-desc">每个档位有哪些学校、去年多少分</text>
            </view>
            <app-icon name="chevron-right" color="#6f7683" :size="26"></app-icon>
          </view>

          <view class="xf-action" @click="goVerify">
            <view class="xf-tile">
              <app-icon name="search" color="#c2c8d0" :size="32"></app-icon>
            </view>
            <view class="xf-action-label">
              <text class="xf-action-title">查某个专业能不能上</text>
              <text class="xf-action-desc">输入专业名，给能上 / 需谨慎 / 够不上</text>
            </view>
            <app-icon name="chevron-right" color="#6f7683" :size="26"></app-icon>
          </view>
        </view>

        <!-- S5-D 志愿表发现性：存在本机草稿时显式入口 + 红点提示 -->
        <view class="draft-row" v-if="hasDraft" @click="openPlan">
          <text class="draft-dot"></text>
          <text class="draft-txt">你有一份志愿表草稿，点击继续编辑</text>
          <app-icon name="chevron-right" color="#5fd87f" :size="24"></app-icon>
        </view>

        <view class="link-row" @click="goCompass">
          <app-icon name="calendar" color="#8f96a2" :size="28"></app-icon>
          <text class="link-row-t">查看历年省控线（2022–2026）</text>
          <app-icon name="chevron-right" color="#6f7683" :size="24"></app-icon>
        </view>

        <view class="xf-divider"></view>
        <text class="basis">{{ r.basis }}</text>
      </view>
    </view>
    <wd-toast></wd-toast>

    <!-- 首启引导：只出现一次，三步说清「这工具怎么用」，之后不再打扰 -->
    <view v-if="showIntro" class="intro-mask">
      <view class="intro-card xf-fade">
        <view class="intro-head">
          <view class="xf-tile xf-tile--gold">
            <app-icon name="compass" color="#ffd24d" :size="34"></app-icon>
          </view>
          <view class="intro-head-body">
            <text class="intro-title">先看三件事</text>
            <text class="intro-sub">十秒了解这个工具怎么用</text>
          </view>
        </view>

        <view class="intro-steps">
          <view class="intro-step">
            <text class="intro-n">1</text>
            <view class="intro-body">
              <text class="intro-t">填位次，看你在哪一档</text>
              <text class="intro-d">省份 + 科类 + 位次，直接给结论和冲稳保区间</text>
            </view>
          </view>
          <view class="intro-step">
            <text class="intro-n">2</text>
            <view class="intro-body">
              <text class="intro-t">挑学校，生成志愿表</text>
              <text class="intro-d">院校池按档位列出，挑中的会自动进志愿表</text>
            </view>
          </view>
          <view class="intro-step">
            <text class="intro-n">3</text>
            <view class="intro-body">
              <text class="intro-t">排顺序，导出给家人看</text>
              <text class="intro-d">填拟报专业后可复制、打印或存 PDF</text>
            </view>
          </view>
        </view>

        <text class="intro-note">数据仅供学习参考，正式填报以各省考试院为准。随时可在「我的」修改信息。</text>

        <view class="xf-action xf-action--primary" @click="closeIntro">
          <view class="xf-action-label">
            <text class="xf-action-title">知道了，开始</text>
          </view>
          <app-icon name="chevron-right" color="#c9a53a" :size="26"></app-icon>
        </view>
      </view>
    </view>
  </wd-config-provider>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { useToast } from "wot-design-uni";
import { api } from "@/utils/api";
import { PLAN_KEY, buildPlan } from "@/utils/plan";
import { themeVars, credMeta, levelColor, levelIcon } from "@/utils/theme";
import { applyProfile, saveFromForm } from "@/utils/profile";

const toast = useToast();

const provinces = ["北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海",
  "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西",
  "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆"];
const subjects = ["物理类", "历史类", "综合/未改革"];
const KEY = "zhiyuan_verdict_v1";

const f = reactive({ province: "", subject: "", rank: "" });
const r = ref(null);
const err = ref("");
const loading = ref(false);
const making = ref(false);

// 首启引导（只出现一次）：新用户第一次打开最需要的不是功能列表，而是「这工具怎么用」
const INTRO_KEY = "zhiyuan_intro_done";
const showIntro = ref(false);

// S5-D：本机是否存在志愿表草稿（决定结论页是否展示常驻入口 + 红点）
const hasDraft = computed(() => !!uni.getStorageSync(PLAN_KEY));

// P2 信任呈现：把「数据能不能信」放在最显眼处（口径统一来自 theme.credMeta）
const cred = computed(() => credMeta(r.value && r.value.data_source));

// 后端未连接且未开演示时的非打断提示（来自 App 启动健康检查）
const offlineHint = computed(() => {
  if (api.isDemo()) return "";
  let ok = true;
  try { ok = !!uni.getStorageSync("zhiyuan_backend_ok"); } catch (e: any) {}
  return ok ? "" : "数据服务未连接，可在「我的」开启演示模式先体验";
});

// 尺子按「专科门槛」做满量程：左边是门槛更硬的档，右边是你的保底空间
const RULER = ["985", "211", "普通二本", "专科"];

const ruler = computed(() => {
  if (!r.value) return { zones: [], rows: [], me: 0 };
  const gs = RULER.map((t) => r.value.gates.find((g) => g.tier === t)).filter(Boolean);
  if (!gs.length) return { zones: [], rows: [], me: 0 };
  const full = gs[gs.length - 1].min_rank;
  const zones: any[] = [];
  let prev = 0;
  gs.forEach((g) => {
    zones.push({
      key: g.tier, label: g.label, state: g.state,
      left: (prev / full) * 100, width: ((g.min_rank - prev) / full) * 100,
      at: (g.min_rank / full) * 100,
    });
    prev = g.min_rank;
  });
  const rows = gs.map((g) => ({
    tier: g.tier, label: g.label, min_rank: g.min_rank, state: g.state,
    at: (g.min_rank / full) * 100,
    gapText: g.gap < 0 ? "差 " + -g.gap + " 位" : "在门内",
  }));
  return { zones, rows, me: Math.min(100, (r.value.user_rank / full) * 100) };
});

function shortLabel(label: any) {
  return String(label || "").replace("普通", "");
}

// 三个判断按「定位 → 主攻 → 保底」给不同语气，避免三行长得一样
const STANCE_TONES = [
  { icon: "target", tone: "gold", color: "#ffd24d" },
  { icon: "trending-up", tone: "reach", color: "#f0ad4e" },
  { icon: "shield", tone: "safe", color: "#5fd87f" },
];
function stanceTone(i: any) { return (STANCE_TONES[i] || STANCE_TONES[0]).tone; }
function stanceIcon(i: any) { return (STANCE_TONES[i] || STANCE_TONES[0]).icon; }
function stanceColor(i: any) { return (STANCE_TONES[i] || STANCE_TONES[0]).color; }

onLoad((q) => {
  // 首启引导：没看过就弹一次（看过的人不再打扰）
  try { showIntro.value = !uni.getStorageSync(INTRO_KEY); } catch (e: any) { showIntro.value = false; }
  // 先带入全局档案（省份/科类/位次/专业），避免每页重填
  Object.assign(f, applyProfile(f));
  if (q && q.province) f.province = decodeURIComponent(q.province);
  if (q && q.subject) f.subject = decodeURIComponent(q.subject);
  if (q && q.user_rank) f.rank = decodeURIComponent(q.user_rank);
  // 带参数进来（从诊断页/外链）就直接出结论，不再让人点一次
  if (f.province && f.subject && f.rank) {
    showIntro.value = false;   // 直奔结果时不挡路
    run();
  }
});

function closeIntro() {
  showIntro.value = false;
  try { uni.setStorageSync(INTRO_KEY, 1); } catch (e: any) { /* 存储失败不阻断 */ }
}

async function run() {
  err.value = "";
  if (!f.province || !f.subject || !f.rank) {
    toast.show("省份 / 科类 / 位次都要填");
    return;
  }
  const rank = Number(f.rank);
  if (!(rank > 0)) {
    toast.show("位次填正整数");
    return;
  }
  loading.value = true;
  try {
    r.value = await api.verdict(f.province, f.subject, rank);
    uni.setStorageSync(KEY, { ...f });
    // 出结论即写入全局档案，后续「院校池 / 查专业 / 志愿表」自动带齐条件
    saveFromForm(f);
  } catch (e: any) {
    err.value = e && e.message ? e.message : "没连上服务，重试一次";
  } finally {
    loading.value = false;
  }
}

function reset() {
  r.value = null;
  err.value = "";
}

// 一键出表：结论页不再把人甩到「推荐页再点一次」，直接拿池子落盘进志愿表
async function goPlan() {
  if (!r.value || making.value) return;
  making.value = true;
  try {
    const rec = await api.recommendSchools({
      province: r.value.province, subject: r.value.subject,
      user_rank: r.value.user_rank, limit: 8,
    });
    const p = buildPlan(rec);
    if (p) uni.setStorageSync(PLAN_KEY, p);
    uni.switchTab({ url: "/pages/plan/plan" });
  } catch (e: any) {
    toast.show(e && e.message ? e.message : "没连上服务，重试一次");
  } finally {
    making.value = false;
  }
}

function goRecommend() {
  // 条件已写入全局档案，tab 间用 switchTab 跳转（不再带 query）
  uni.switchTab({ url: "/pages/recommend/recommend" });
}

// S3 下钻：带着条件进核验页（批量模式），「你能上哪档 → 哪些专业值得读」复用 verify 引擎
function goVerify() {
  uni.switchTab({ url: "/pages/verify/verify" });
}

// S5-D：直接打开已有志愿表草稿（不覆盖、不重新生成）
function openPlan() {
  uni.switchTab({ url: "/pages/plan/plan" });
}

function goDiagnose() {
  uni.navigateTo({ url: "/subpackages/diagnose/diagnose" });
}
function goCompass() {
  uni.navigateTo({ url: "/subpackages/compass/compass" });
}
</script>

<style scoped>
.page { padding: 32rpx 28rpx 80rpx; min-height: 100vh; background: var(--xf-bg); }

/* 输入 */
.ask { padding-top: 48rpx; }
.ask-mark { margin-bottom: 24rpx; }
.ask-h1 { display: block; font-size: 64rpx; font-weight: 700; color: var(--xf-text); letter-spacing: 2rpx; }
.ask-sub { display: block; margin-top: 16rpx; font-size: 26rpx; color: var(--xf-text-3); line-height: 1.6; }
.fields { margin: 52rpx 0 36rpx; border: 1rpx solid var(--xf-line); border-radius: var(--xf-r-md); overflow: hidden; background: var(--xf-surface); }
.ask-foot { margin-top: 36rpx; }
.ask-link { display: flex; align-items: center; gap: 12rpx; min-height: 88rpx; padding: 0 6rpx; }
.ask-link-t { flex: 1; font-size: 24rpx; color: var(--xf-text-3); }
.lk { font-size: 24rpx; color: var(--xf-real); }
.err { display: block; margin-top: 20rpx; font-size: 24rpx; color: var(--xf-danger-text); line-height: 1.6; }
.skel-card { margin-top: 32rpx; }

/* 结论 */
.res { padding-top: 8rpx; }
.topbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20rpx; }
.topbar-right { display: flex; align-items: center; gap: 16rpx; }
.offline-tip {
  display: flex; align-items: flex-start; gap: 12rpx;
  font-size: 22rpx; color: var(--xf-demo); background: rgba(240, 173, 78, 0.09);
  border: 1rpx solid rgba(240, 173, 78, 0.3); border-radius: var(--xf-r-sm);
  padding: 14rpx 18rpx; margin-bottom: 20rpx;
}
.offline-tip-t { flex: 1; line-height: 1.6; }
.cond { font-size: 22rpx; color: var(--xf-text-3); letter-spacing: 1rpx; }

/* 主结果卡：金边 + 渐变，让「结论」是全页唯一焦点 */
.hero-card {
  position: relative;
  padding: 30rpx 26rpx 26rpx;
  border-radius: var(--xf-r-lg);
  background: linear-gradient(150deg, rgba(255, 210, 77, 0.13), rgba(255, 210, 77, 0.02) 58%), var(--xf-surface);
  border: 1rpx solid rgba(255, 210, 77, 0.3);
}
.headline { display: block; font-size: 42rpx; line-height: 1.5; font-weight: 700; color: var(--xf-gold); letter-spacing: 1rpx; }

/* 位次带 */
.ruler { margin: 34rpx 0 4rpx; }
.zones { position: relative; height: 56rpx; border-radius: 8rpx; overflow: hidden; background: var(--xf-surface-3); }
.zone { position: absolute; top: 0; bottom: 0; border-right: 1rpx solid var(--xf-bg); }
.zone.open { background: rgba(95, 216, 127, 0.2); }
.zone.closed { background: rgba(120, 128, 140, 0.16); }
.me { position: absolute; top: 0; bottom: 0; transform: translateX(-50%); transition: left 420ms var(--xf-ease); }
.me-dot {
  position: absolute; top: 50%; left: 50%; width: 20rpx; height: 20rpx; margin: -10rpx 0 0 -10rpx;
  border-radius: 50%; background: var(--xf-gold); box-shadow: 0 0 0 7rpx rgba(255, 210, 77, 0.2);
}
.me-label {
  position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%);
  font-size: 18rpx; color: var(--xf-gold); font-weight: 600; margin-bottom: 2rpx;
}
.ticks { position: relative; height: 26rpx; margin-top: 10rpx; }
.tick { position: absolute; top: 0; transform: translateX(-50%); font-size: 18rpx; color: var(--xf-text-4); }

/* 门槛明细 */
.ladder { margin-top: 18rpx; }
.lg { display: flex; align-items: center; gap: 12rpx; padding: 12rpx 0; border-bottom: 1rpx solid var(--xf-line-soft); }
.lg:last-child { border-bottom: none; }
.lg-dot { width: 12rpx; height: 12rpx; border-radius: 50%; flex: 0 0 auto; }
.lg-dot.open { background: var(--xf-safe); }
.lg-dot.closed { background: var(--xf-text-4); }
.lg-k { flex: 1; font-size: 25rpx; color: var(--xf-text); font-weight: 600; }
.lg-r { font-size: 24rpx; color: var(--xf-text-2); font-variant-numeric: tabular-nums; }
.lg-g { width: 130rpx; text-align: right; font-size: 22rpx; }
.lg-g.open { color: var(--xf-safe); }
.lg-g.closed { color: var(--xf-danger-text); }

/* 三个判断 */
.stance { margin-top: 26rpx; }
.st { display: flex; align-items: flex-start; gap: 18rpx; padding: 20rpx 0; border-top: 1rpx solid var(--xf-line-soft); }
.st-body { flex: 1; min-width: 0; }
.st-k { display: block; font-size: 22rpx; color: var(--xf-text-3); font-weight: 600; margin-bottom: 6rpx; }
.st-t { display: block; font-size: 27rpx; color: var(--xf-text-2); line-height: 1.7; }

/* 风险提示 */
.guard {
  display: flex; align-items: flex-start; gap: 14rpx;
  margin-top: 18rpx; padding: 22rpx 22rpx; border-left: 6rpx solid var(--xf-danger);
  background: rgba(229, 72, 77, 0.08); border-radius: 0 var(--xf-r-md) var(--xf-r-md) 0;
}
.guard-t { flex: 1; font-size: 25rpx; color: var(--xf-danger-text); line-height: 1.6; }

/* 区间 */
.bands { margin-top: 34rpx; }
.blk-title { display: block; font-size: 22rpx; color: var(--xf-text-3); margin-bottom: 12rpx; }
.band { display: flex; align-items: center; gap: 16rpx; padding: 12rpx 0; }
.band-k { flex: 1; font-size: 26rpx; font-weight: 600; color: var(--xf-text); }
.band-v { font-size: 26rpx; color: var(--xf-text-2); font-variant-numeric: tabular-nums; }

/* 动作 */
.actions { display: flex; flex-direction: column; gap: 14rpx; margin-top: 38rpx; }

.basis { display: block; font-size: 21rpx; color: var(--xf-text-4); line-height: 1.7; }

/* S5-D 志愿表草稿常驻入口 */
.draft-row {
  display: flex; align-items: center; gap: 10rpx;
  margin-top: 20rpx; padding: 18rpx; min-height: 88rpx;
  border: 1rpx dashed rgba(95, 216, 127, 0.45); border-radius: var(--xf-r-md);
  background: rgba(95, 216, 127, 0.05);
}
.draft-dot { width: 14rpx; height: 14rpx; border-radius: 50%; background: var(--xf-danger); margin-right: 6rpx; box-shadow: 0 0 8rpx 1rpx rgba(229, 72, 77, 0.6); }
.draft-txt { flex: 1; font-size: 23rpx; color: var(--xf-text-2); }

/* 次级链接 */
.link-row { display: flex; align-items: center; gap: 12rpx; min-height: 88rpx; margin-top: 8rpx; }
.link-row-t { flex: 1; font-size: 24rpx; color: var(--xf-text-3); }

/* 首启引导浮层 */
.intro-mask {
  position: fixed; left: 0; right: 0; top: 0; bottom: 0; z-index: 200;
  background: rgba(6, 8, 11, 0.72);
  display: flex; align-items: center; justify-content: center;
  padding: 0 32rpx;
}
.intro-card {
  width: 100%; max-width: 640rpx;
  background: var(--xf-surface); border: 1rpx solid rgba(255, 210, 77, 0.3);
  border-radius: var(--xf-r-lg); padding: 30rpx 26rpx 24rpx;
  box-shadow: 0 24rpx 64rpx rgba(0, 0, 0, 0.5);
}
.intro-head { display: flex; align-items: center; gap: 16rpx; }
.intro-head-body { flex: 1; min-width: 0; }
.intro-title { display: block; font-size: 34rpx; font-weight: 700; color: var(--xf-text); }
.intro-sub { display: block; margin-top: 4rpx; font-size: 22rpx; color: var(--xf-text-3); }
.intro-steps { margin: 22rpx 0 8rpx; }
.intro-step { display: flex; align-items: flex-start; gap: 14rpx; padding: 14rpx 0; border-top: 1rpx solid var(--xf-line-soft); }
.intro-step:first-child { border-top: none; }
.intro-n {
  flex: 0 0 auto; width: 40rpx; height: 40rpx; border-radius: 50%;
  background: rgba(255, 210, 77, 0.14); color: var(--xf-gold);
  font-size: 21rpx; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
}
.intro-body { flex: 1; min-width: 0; }
.intro-t { display: block; font-size: 25rpx; color: var(--xf-text); font-weight: 600; }
.intro-d { display: block; margin-top: 4rpx; font-size: 21rpx; color: var(--xf-text-3); line-height: 1.6; }
.intro-note { display: block; margin: 8rpx 0 18rpx; font-size: 19rpx; color: var(--xf-text-4); line-height: 1.6; }
</style>
