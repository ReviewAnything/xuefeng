<template>
  <wd-config-provider theme="dark" :theme-vars="themeVars">
    <view class="page">
      <!-- 输入：三个字段，一屏，一个问题 -->
      <view v-if="!r" class="ask">
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

        <view class="ask-foot">
          <text class="lk" @click="goDiagnose">说不清自己要什么？先做八连问 ›</text>
        </view>
      </view>

      <!-- 结论：一句判断，然后是三个动作 -->
      <view v-else class="res">
        <view v-if="offlineHint" class="offline-tip">{{ offlineHint }}</view>
        <view class="topbar">
          <text class="cond">{{ r.province }} · {{ r.subject }} · {{ r.user_rank }} 名</text>
          <view class="topbar-right">
            <text :class="['cred', 'cred-' + credibility.cls]">{{ credibility.label }}</text>
            <text class="lk" @click="reset">改条件</text>
          </view>
        </view>

        <text class="headline">{{ r.headline }}</text>

        <!-- 位次带：四段门槛 + 你落在哪 -->
        <view class="ruler">
          <view class="zones">
            <view v-for="z in ruler.zones" :key="z.key" class="zone" :class="z.state"
                  :style="{ left: z.left + '%', width: z.width + '%' }"></view>
            <view class="me" :style="{ left: ruler.me + '%' }">
              <text class="me-label">你</text>
              <view class="me-dot"></view>
            </view>
          </view>
          <view class="legend">
            <view v-for="g in ruler.rows" :key="g.tier" class="lg">
              <text class="lg-k" :class="g.state">{{ g.label }}</text>
              <text class="lg-r">{{ g.min_rank }}</text>
              <text class="lg-g" :class="g.state">{{ g.gapText }}</text>
            </view>
          </view>
        </view>

        <view class="stance">
          <view v-for="s in r.stance" :key="s.k" class="st">
            <text class="st-k">{{ s.k }}</text>
            <text class="st-t">{{ s.t }}</text>
          </view>
        </view>

        <view class="guard">
          <text class="guard-t">{{ r.guard }}</text>
        </view>

        <view v-if="r.bands.length" class="bands">
          <text class="blk-title">照这个区间去筛学校</text>
          <view v-for="b in r.bands" :key="b.key" class="band">
            <text class="band-k" :class="b.key">{{ b.label }}</text>
            <text class="band-v">{{ b.from }} – {{ b.to }} 名</text>
          </view>
        </view>

        <view class="facts">
          <text v-for="(x, i) in r.facts" :key="i" class="fact">· {{ x }}</text>
        </view>

        <view class="actions">
          <wd-button type="primary" block :loading="making" @click="goPlan">生成志愿表</wd-button>
          <wd-button plain block @click="goRecommend">看院校池</wd-button>
          <wd-button plain block @click="goVerify">你能上哪档 · 哪些专业值得读 ›</wd-button>
        </view>

        <!-- S5-D 志愿表发现性：存在本机草稿时显式入口 + 红点提示 -->
        <view class="draft-row" v-if="hasDraft" @click="openPlan">
          <text class="draft-dot"></text>
          <text class="draft-txt">你有一份志愿表草稿，点击查看 / 继续编辑 ›</text>
        </view>

        <text class="lk" style="display:block;margin:14rpx 0;" @click="goCompass">查看历年省控线（2022–2026）›</text>

        <text class="basis">{{ r.basis }}</text>
      </view>
    </view>
    <wd-toast></wd-toast>
  </wd-config-provider>
</template>

<script setup>
import { computed, reactive, ref } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { useToast } from "wot-design-uni";
import { api } from "@/utils/api.js";
import { PLAN_KEY, buildPlan } from "@/utils/plan.js";
import { themeVars } from "@/utils/theme.js";
import { applyProfile, saveFromForm } from "@/utils/profile.js";

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

// S5-D：本机是否存在志愿表草稿（决定结论页是否展示常驻入口 + 红点）
const hasDraft = computed(() => !!uni.getStorageSync(PLAN_KEY));

// P2 信任呈现：把「数据能不能信」放在最显眼处（绿=官方 / 蓝=真实抓取非官方 / 灰=估算 / 黄=演示）
const credibility = computed(() => {
  const ds = r.value && r.value.data_source;
  if (ds === "demo") return { label: "演示数据", cls: "demo" };
  if (ds === "official" || ds === "official_overlay") return { label: "官方数据", cls: "official" };
  if (ds === "real") return { label: "真实抓取", cls: "real" };
  return { label: "估算数据", cls: "est" };
});
// 后端未连接且未开演示时的非打断提示（来自 App 启动健康检查）
const offlineHint = computed(() => {
  if (api.isDemo()) return "";
  let ok = true;
  try { ok = !!uni.getStorageSync("zhiyuan_backend_ok"); } catch (e) {}
  return ok ? "" : "数据服务未连接，可在「我的」开启演示模式先体验";
});

// 尺子按「专科门槛」做满量程：左边是门槛更硬的档，右边是你的保底空间
const RULER = ["985", "211", "普通二本", "专科"];

const ruler = computed(() => {
  if (!r.value) return { zones: [], rows: [], me: 0 };
  const gs = RULER.map((t) => r.value.gates.find((g) => g.tier === t)).filter(Boolean);
  if (!gs.length) return { zones: [], rows: [], me: 0 };
  const full = gs[gs.length - 1].min_rank;
  const zones = [];
  let prev = 0;
  gs.forEach((g) => {
    zones.push({
      key: g.tier, label: g.label, state: g.state,
      left: (prev / full) * 100, width: ((g.min_rank - prev) / full) * 100,
    });
    prev = g.min_rank;
  });
  const rows = gs.map((g) => ({
    tier: g.tier, label: g.label, min_rank: g.min_rank, state: g.state,
    gapText: g.gap < 0 ? "差 " + -g.gap + " 位" : "在门内",
  }));
  return { zones, rows, me: Math.min(100, (r.value.user_rank / full) * 100) };
});

onLoad((q) => {
  // 先带入全局档案（省份/科类/位次/专业），避免每页重填
  Object.assign(f, applyProfile(f));
  if (q && q.province) f.province = decodeURIComponent(q.province);
  if (q && q.subject) f.subject = decodeURIComponent(q.subject);
  if (q && q.user_rank) f.rank = decodeURIComponent(q.user_rank);
  // 带参数进来（从诊断页/外链）就直接出结论，不再让人点一次
  if (f.province && f.subject && f.rank) run();
});

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
  } catch (e) {
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
  } catch (e) {
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
  uni.navigateTo({ url: "/pages/diagnose/diagnose" });
}
function goCompass() {
  uni.navigateTo({ url: "/pages/compass/compass" });
}
</script>

<style scoped>
.page { padding: 32rpx 28rpx 80rpx; min-height: 100vh; background: #0f1115; }

/* 输入 */
.ask { padding-top: 60rpx; }
.ask-h1 { display: block; font-size: 64rpx; font-weight: 700; color: #e6e8ec; letter-spacing: 2rpx; }
.ask-sub { display: block; margin-top: 16rpx; font-size: 26rpx; color: #8a909c; line-height: 1.6; }
.fields { margin: 56rpx 0 40rpx; border: 1px solid #22262e; border-radius: 16rpx; overflow: hidden; }
.ask-foot { margin-top: 40rpx; }
.lk { font-size: 24rpx; color: #6db3f2; }
.err { display: block; margin-top: 20rpx; font-size: 24rpx; color: #ff6b6b; }

/* 结论 */
.res { padding-top: 12rpx; }
.topbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 28rpx; }
.topbar-right { display: flex; align-items: center; gap: 16rpx; }
.cred { font-size: 20rpx; padding: 3rpx 12rpx; border-radius: 999rpx; border: 1px solid transparent; }
.cred-official { color: #5fd87f; border-color: #2f7d4f; background: rgba(95, 216, 127, 0.08); }
.cred-real { color: #6db3f2; border-color: #2f5a8f; background: rgba(109, 179, 242, 0.08); }
.cred-est { color: #c7ccd4; border-color: #3a3f48; background: rgba(138, 144, 156, 0.08); }
.cred-demo { color: #f0ad4e; border-color: #7d5a1a; background: rgba(240, 173, 78, 0.1); }
.offline-tip { font-size: 22rpx; color: #f0ad4e; background: rgba(240, 173, 78, 0.1); border: 1px solid #5a4a1a; border-radius: 12rpx; padding: 14rpx 18rpx; margin-bottom: 20rpx; line-height: 1.6; }
.cond { font-size: 22rpx; color: #8a909c; letter-spacing: 1rpx; }

.headline {
  display: block; font-size: 42rpx; line-height: 1.5; font-weight: 700;
  color: #ffd24d; letter-spacing: 1rpx;
}

/* 位次带 */
.ruler { margin: 44rpx 0 8rpx; }
.zones { position: relative; height: 56rpx; border-radius: 8rpx; overflow: hidden; background: #1a1e25; }
.zone { position: absolute; top: 0; bottom: 0; border-right: 1px solid #0f1115; }
.zone.open { background: rgba(95, 216, 127, 0.16); }
.zone.closed { background: rgba(107, 114, 128, 0.18); }
.me { position: absolute; top: 0; bottom: 0; transform: translateX(-50%); }
.me-dot {
  position: absolute; top: 50%; left: 50%; width: 18rpx; height: 18rpx; margin: -9rpx 0 0 -9rpx;
  border-radius: 50%; background: #ffd24d; box-shadow: 0 0 0 6rpx rgba(255, 210, 77, 0.18);
}
.me-label {
  position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%);
  font-size: 18rpx; color: #ffd24d; font-weight: 600; margin-bottom: 2rpx;
}
.legend { margin-top: 14rpx; }
.lg { display: flex; align-items: baseline; padding: 6rpx 0; }
.lg-k { width: 78rpx; font-size: 21rpx; font-weight: 600; }
.lg-k.open { color: #5fd87f; }
.lg-k.closed { color: #6b7280; }
.lg-r { width: 140rpx; font-size: 21rpx; color: #8a909c; font-variant-numeric: tabular-nums; }
.lg-g { font-size: 21rpx; }
.lg-g.open { color: #4f8f63; }
.lg-g.closed { color: #8a5c5c; }

/* 三个动作 */
.stance { margin-top: 20rpx; }
.st { padding: 22rpx 0; border-top: 1px solid #1c2027; }
.st-k { display: block; font-size: 22rpx; color: #6db3f2; font-weight: 600; margin-bottom: 8rpx; }
.st-t { display: block; font-size: 27rpx; color: #d5d9e0; line-height: 1.7; }

.guard {
  margin-top: 14rpx; padding: 22rpx 24rpx; border-left: 4rpx solid #ff6b6b;
  background: rgba(255, 107, 107, 0.07); border-radius: 0 12rpx 12rpx 0;
}
.guard-t { font-size: 25rpx; color: #ff9d9d; line-height: 1.6; }

/* 区间 */
.bands { margin-top: 36rpx; }
.blk-title { display: block; font-size: 22rpx; color: #8a909c; margin-bottom: 12rpx; }
.band { display: flex; align-items: baseline; gap: 16rpx; padding: 10rpx 0; }
.band-k { font-size: 26rpx; font-weight: 600; width: 40rpx; }
.band-k.reach { color: #f0ad4e; }
.band-k.match { color: #6db3f2; }
.band-k.safe { color: #5fd87f; }
.band-v { font-size: 26rpx; color: #d5d9e0; font-variant-numeric: tabular-nums; }

.facts { margin-top: 32rpx; }
.fact { display: block; font-size: 22rpx; color: #828a96; line-height: 1.8; }

.actions { display: flex; flex-direction: column; gap: 16rpx; margin-top: 44rpx; }
.basis { display: block; margin-top: 28rpx; font-size: 20rpx; color: #5b626d; line-height: 1.7; }

/* S5-D 志愿表草稿常驻入口 */
.draft-row { display: flex; align-items: center; margin-top: 22rpx; padding: 16rpx 18rpx; border: 1px dashed #3a3f48; border-radius: 12rpx; background: rgba(95, 216, 127, 0.05); }
.draft-dot { width: 14rpx; height: 14rpx; border-radius: 50%; background: #e5484d; margin-right: 12rpx; box-shadow: 0 0 8rpx 1rpx rgba(229, 72, 77, 0.6); }
.draft-txt { font-size: 23rpx; color: #c7ccd4; }
</style>
