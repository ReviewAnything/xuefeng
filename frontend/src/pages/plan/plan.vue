<template>
  <wd-config-provider :theme="$theme.mode" :theme-vars="themeVars" :style="$theme.style">
    <view class="page">
      <!-- 打印专用页眉（屏幕上不显示，打印时替代 App 导航栏） -->
      <view class="print-head">
        <text class="print-title">志愿表草稿</text>
        <text class="print-meta">{{ printMeta }}</text>
      </view>

      <view v-if="!hasPlan" class="xf-hero">
        <view class="xf-tile xf-tile--gold">
          <app-icon name="list" color="#ffd24d" :size="36"></app-icon>
        </view>
        <view class="xf-hero-body">
          <text class="xf-h1">志愿表</text>
          <text class="xf-sub">按冲稳保整理成表，填好拟报专业后可直接打印或存成 PDF。全程只存本机。</text>
        </view>
      </view>

      <view v-if="isEmpty" class="empty-wrap">
        <view class="xf-card empty-card">
          <view class="xf-empty">
            <app-icon name="list" color="#4b515b" :size="64"></app-icon>
            <text class="xf-empty-title">还没有志愿表</text>
            <text class="xf-empty-desc">先按位次生成一份冲稳保院校清单，再来这里调整顺序、填专业、导出。</text>
          </view>
          <view class="xf-action xf-action--primary" @click="goRecommend">
            <view class="xf-tile xf-tile--gold">
              <app-icon name="school" color="#ffd24d" :size="32"></app-icon>
            </view>
            <view class="xf-action-label">
              <text class="xf-action-title">去生成院校推荐</text>
              <text class="xf-action-desc">用你的位次算出冲稳保三档院校</text>
            </view>
            <app-icon name="chevron-right" color="#c9a53a" :size="26"></app-icon>
          </view>
          <view class="link-row" @click="goCompass">
            <app-icon name="calendar" color="#8f96a2" :size="28"></app-icon>
            <text class="link-row-t">查看历年省控线（2022–2026）</text>
            <app-icon name="chevron-right" color="#6f7683" :size="24"></app-icon>
          </view>
        </view>
      </view>

      <view v-if="hasPlan" class="section">
        <view class="xf-card meta-card">
          <view class="meta-row">
            <app-icon name="user" color="#8f96a2" :size="26"></app-icon>
            <text class="meta-line">{{ plan.province }} · {{ plan.subject }} · {{ plan.user_rank }} 名</text>
            <text class="meta-time">{{ timeLabel }}</text>
          </view>
          <view v-if="plan.major" class="meta-row">
            <app-icon name="bulb" color="#8f96a2" :size="26"></app-icon>
            <text class="meta-line">目标专业：{{ plan.major }}</text>
          </view>
        </view>
      </view>

      <!-- S10-B：志愿个数上限（各省本科批配额），超填/偏少都提醒 -->
      <view v-if="hasPlan && volLimit" class="section">
        <view class="xf-card cap-card" :class="'cap--' + capCls">
          <view class="cap-head">
            <view class="cap-num-wrap">
              <text class="cap-num" :class="capCls">{{ filledCount }}</text>
              <text class="cap-den">/ {{ volLimit.undergrad }}</text>
            </view>
            <view class="cap-head-body">
              <text class="cap-title">本科批志愿上限</text>
              <text class="cap-sub">{{ modeLabel }} · 最多 {{ volLimit.undergrad }} 个</text>
            </view>
            <view :class="['xf-chip', capChipCls]">{{ capText }}</view>
          </view>

          <view class="cap-bar">
            <view class="cap-fill" :class="capCls" :style="{ width: fillPct + '%' }"></view>
          </view>

          <view class="cap-levels">
            <text class="cap-lvl reach">冲 {{ levelCounts.reach }}</text>
            <text class="cap-lvl match">稳 {{ levelCounts.match }}</text>
            <text class="cap-lvl safe">保 {{ levelCounts.safe }}</text>
            <text v-if="volLimit.split" class="cap-suggest">建议 冲{{ volLimit.split.reach }} 稳{{ volLimit.split.match }} 保{{ volLimit.split.safe }}</text>
          </view>

          <text class="cap-note">专科批上限 {{ volLimit.junior }} 个；提前批 / 艺术体育类另计。{{ volLimit.note || '每年可能调整，正式填报以本省教育考试院为准。' }}</text>
        </view>
      </view>

      <!-- 保底安全网 -->
      <view v-if="hasPlan" class="section">
        <view class="xf-card safe-net" :class="breach.cls">
          <view class="safe-head">
            <view class="xf-tile" :class="breachTile">
              <app-icon :name="breachIcon" :color="breachColor" :size="30"></app-icon>
            </view>
            <view class="safe-head-body">
              <text class="safe-title">保底安全网</text>
              <text class="safe-count" :class="breach.cls">{{ breach.text }}</text>
            </view>
          </view>
          <text class="safe-desc">{{ breach.desc }}</text>

          <view v-if="breach.cls === 'danger'" class="xf-action xf-action--primary no-print" @click="patchSafe">
            <view class="xf-tile xf-tile--gold">
              <app-icon name="refresh" :color="patching ? '#8f96a2' : '#ffd24d'" :size="30"></app-icon>
            </view>
            <view class="xf-action-label">
              <text class="xf-action-title">{{ patching ? "正在补位…" : "一键补位" }}</text>
              <text class="xf-action-desc">拉取更低层次、你能稳够的兜底院校</text>
            </view>
          </view>

          <!-- S7-E 补位前后对比：用户真正关心的是「失守有没有被填平」 -->
          <view v-if="patchDiff" class="patch-diff no-print">
            <text class="patch-title">补位前后对比</text>
            <text class="patch-line">
              可稳够：{{ patchDiff.safe_before }} 所 →
              <text class="patch-good">{{ patchDiff.safe_after }} 所</text>
            </text>
            <text class="patch-line">
              失守院校：{{ patchDiff.before.breach }} 所 → {{ patchDiff.after.breach }} 所
              <text v-if="patchDiff.before.breach > patchDiff.after.breach" class="patch-good">
                （填平 {{ patchDiff.before.breach - patchDiff.after.breach }} 所）
              </text>
            </text>
            <text class="patch-line">新增兜底：{{ patchDiff.added.map((s) => s.name).join("、") }}</text>
            <text v-if="patchDiff.skipped" class="patch-line muted">
              {{ patchDiff.skipped }} 所候选已在志愿表中，未重复加入
            </text>
            <text v-if="patchDiff.still_breach.length" class="patch-line warn">
              仍失守：{{ patchDiff.still_breach.join("、") }}（位次够不上，建议继续下调保底预期）
            </text>
          </view>
        </view>
      </view>

      <!-- 三档明细 -->
      <view v-if="hasPlan" class="section">
        <view v-for="g in groups" :key="g.level" class="grp" :class="'grp--' + levelClass(g.level)">
          <view class="grp-head">
            <view class="grp-head-left">
              <app-icon :name="levelIcon(g.level)" :color="levelColor(g.level)" :size="28"></app-icon>
              <text class="grp-title" :class="levelClass(g.level)">{{ g.title }}</text>
              <text class="grp-count">{{ g.rows.length }}</text>
            </view>
            <view v-if="volLimit && volLimit.mode === '院校专业组'" class="grp-adjust no-print" @click="toggleAdjust(g.level)">
              <text class="adj-label">服从调剂</text>
              <view class="adj-switch" :class="adjust[g.level] ? 'on' : 'off'">
                <text class="adj-knob">{{ adjust[g.level] ? '是' : '否' }}</text>
              </view>
            </view>
            <text v-else-if="volLimit && volLimit.mode === '专业+院校'" class="grp-sub">专业+院校模式无调剂</text>
          </view>

          <view v-for="(r, i) in g.rows" :key="r.key" class="row">
            <text class="row-idx">{{ i + 1 }}</text>
            <view class="row-info">
              <view class="row-name-line">
                <text class="row-name">{{ r.name }}</text>
                <text v-if="rowBreach(r) === 'breach'" class="row-breach">失守</text>
              </view>
              <text class="row-meta">{{ r.tier }} · {{ r.province }}<text v-if="r.line"> · 去年 {{ r.line }} 分<text v-if="r.line_rank"> / 位次 {{ r.line_rank }}</text><text v-if="r.line_year">（{{ r.line_year }}）</text></text></text>
              <text v-if="rowBreach(r) === 'breach'" class="row-breach-tip">你的位次 {{ plan.user_rank }} 比该校最低投档位次 {{ r.line_rank }} 更靠后，够不上</text>
            </view>
            <view class="row-right">
              <input class="row-major" v-model="r.major" placeholder="拟报专业" />
              <view class="row-actions no-print">
                <view class="row-move" @click="move(r.key, 'up')">
                  <app-icon name="arrow-up" color="#9aa0aa" :size="26"></app-icon>
                </view>
                <view class="row-move" @click="move(r.key, 'down')">
                  <app-icon name="arrow-down" color="#9aa0aa" :size="26"></app-icon>
                </view>
              </view>
            </view>
          </view>
          <text v-if="isNoRow(g)" class="grp-empty">该档暂无院校，可回到院校池放宽条件。</text>
        </view>
      </view>

      <!-- 动作区 -->
      <view v-if="hasPlan" class="section">
        <text class="fill-stat">已填拟报专业 {{ stats.filled }} / {{ stats.total }}</text>

        <view class="actions no-print">
          <!-- #ifdef H5 -->
          <view class="xf-action xf-action--primary" @click="print">
            <view class="xf-tile xf-tile--gold">
              <app-icon name="printer" color="#ffd24d" :size="32"></app-icon>
            </view>
            <view class="xf-action-label">
              <text class="xf-action-title">打印 / 另存为 PDF</text>
              <text class="xf-action-desc">自动隐藏按钮，切浅色 A4 版式</text>
            </view>
            <app-icon name="chevron-right" color="#c9a53a" :size="26"></app-icon>
          </view>
          <!-- #endif -->

          <view class="xf-action" @click="copy">
            <view class="xf-tile">
              <app-icon name="copy" color="#c2c8d0" :size="30"></app-icon>
            </view>
            <view class="xf-action-label">
              <text class="xf-action-title">复制为文本</text>
              <text class="xf-action-desc">粘到微信 / 备忘录里继续改</text>
            </view>
            <app-icon name="chevron-right" color="#6f7683" :size="26"></app-icon>
          </view>

          <view class="xf-action" @click="toggleFillOrder">
            <view class="xf-tile">
              <app-icon name="trending-up" color="#c2c8d0" :size="30"></app-icon>
            </view>
            <view class="xf-action-label">
              <text class="xf-action-title">{{ showFillOrder ? "收起填报顺序" : "看填报顺序" }}</text>
              <text class="xf-action-desc">按往年投档位次的相对可及性排序</text>
            </view>
            <app-icon :name="showFillOrder ? 'chevron-down' : 'chevron-right'" color="#6f7683" :size="26"></app-icon>
          </view>

          <view class="xf-action" @click="copyFillOrder">
            <view class="xf-tile">
              <app-icon name="download" color="#c2c8d0" :size="30"></app-icon>
            </view>
            <view class="xf-action-label">
              <text class="xf-action-title">复制填报顺序</text>
              <text class="xf-action-desc">带序号的纯文本清单，可直接照抄</text>
            </view>
            <app-icon name="chevron-right" color="#6f7683" :size="26"></app-icon>
          </view>

          <view class="xf-action" @click="goRecommend">
            <view class="xf-tile">
              <app-icon name="refresh" color="#c2c8d0" :size="30"></app-icon>
            </view>
            <view class="xf-action-label">
              <text class="xf-action-title">重新生成</text>
              <text class="xf-action-desc">回到院校池换条件再出表</text>
            </view>
            <app-icon name="chevron-right" color="#6f7683" :size="26"></app-icon>
          </view>
        </view>

        <!-- S8-D：按可及性排序的填报顺序；S9-B 跨年/跨批次可比性标注 -->
        <view v-if="showFillOrder && hasPlan" class="fill-order">
          <text class="fo-title">填报顺序建议（{{ fillOrder.total }} 所）</text>
          <view v-if="fillOrder.reference_year" class="fo-ref">
            <text class="fo-ref-tag">位次余量参考口径</text>
            <text class="fo-ref-text">年份 {{ fillOrder.reference_year }}{{ fillOrder.reference_batch ? ' · 批次「' + fillOrder.reference_batch + '」' : '' }}</text>
          </view>
          <text class="fo-basis">排序依据：{{ fillOrder.basis }}</text>
          <view v-for="it in fillOrder.items" :key="it.seq" :class="foRowClass(it)">
            <text class="fo-seq">{{ it.seq }}.</text>
            <view class="fo-main">
              <text class="fo-name">[{{ it.level }}] {{ it.name }}</text>
              <text class="fo-meta">{{ it.margin_label }}</text>
              <text v-if="it.has_line_data && !it.comparable" class="fo-warn">余量仅供参考</text>
            </view>
          </view>
          <text v-if="fillOrder.unknown_count" class="fo-note">
            其中 {{ fillOrder.unknown_count }} 所缺往年投档位次，附在同档末尾，顺序不代表可及性判断。
          </text>
          <text v-if="fillOrder.incomparable_count" class="fo-note warn">
            另有 {{ fillOrder.incomparable_count }} 所投档线与参考年份/批次口径不同，其位次余量仅供参考。
          </text>
          <text class="fo-note">顺序仅反映往年投档位次的相对关系，不构成录取承诺。</text>
        </view>

        <view class="disclaimer">
          <app-icon name="shield" color="#6f7683" :size="26"></app-icon>
          <text class="disclaimer-t">本表仅为学习参考：院校池不等于录取承诺，正式填报请以各省考试院与院校招生网为准。</text>
        </view>
      </view>
    </view>
    <wd-toast></wd-toast>
  </wd-config-provider>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import { onLoad, onShow } from "@dcloudio/uni-app";
import { useToast } from "wot-design-uni";
import { themeVars, levelColor, levelIcon } from "@/utils/theme.js";
import { api } from "@/utils/api.js";
import { PLAN_KEY, applyMajors, breachStats, breachStatus, buildFillOrderText, buildPlanText, collectMajors, diffSafePatch, fillOrder as buildFillOrder, fillStats, flattenPlan, formatTime, groupRows, selectBackstops } from "@/utils/plan.js";

const toast = useToast();
const plan = ref(null);
const rows = ref([]);
const patching = ref(false);
const patchDiff = ref(null);   // S7-E 补位前后对比
const showFillOrder = ref(false);   // S8-D 填报顺序展开开关
const volLimit = ref(null);   // S10-B：本省志愿个数上限（本科批配额）
const adjust = ref({ 冲: true, 稳: true, 保: true });  // S10-B：各组服从专业调剂

const hasPlan = computed(() => !!plan.value);
const isEmpty = computed(() => !plan.value);
const groups = computed(() => groupRows(rows.value));
const stats = computed(() => fillStats(rows.value));
const timeLabel = computed(() => formatTime(plan.value && plan.value.at));

// 打印页眉：把「谁的表、什么条件、什么时候生成」印在纸上，脱离手机也能对上人
const printMeta = computed(() => {
  const p = plan.value;
  if (!p) return "";
  return `${p.province} · ${p.subject} · 位次 ${p.user_rank}${p.major ? " · 目标专业 " + p.major : ""} · ${timeLabel.value}`;
});

// S10-B：志愿个数上限相关派生量
const modeLabel = computed(() => {
  if (!volLimit.value) return "";
  const m = volLimit.value.mode;
  if (m === "院校专业组") return "院校专业组模式";
  if (m === "专业+院校") return "专业+院校模式";
  return "旧高考院校志愿模式";
});
const filledCount = computed(() => rows.value.length);
const levelCounts = computed(() => {
  const c = { reach: 0, match: 0, safe: 0 };
  rows.value.forEach((r) => {
    if (r.level === "冲") c.reach++;
    else if (r.level === "稳") c.match++;
    else if (r.level === "保") c.safe++;
  });
  return c;
});
const overLimit = computed(() => volLimit.value && filledCount.value > volLimit.value.undergrad);
const minSafe = computed(() => (volLimit.value && volLimit.value.split ? volLimit.value.split.safe : 0));
const fillPct = computed(() => {
  if (!volLimit.value) return 0;
  return Math.min(100, Math.round((filledCount.value / volLimit.value.undergrad) * 100));
});
const capCls = computed(() => {
  if (overLimit.value) return "over";
  if (filledCount.value === 0) return "empty";
  if (filledCount.value < minSafe.value) return "low";
  return "ok";
});
// 上限状态用一句话说清，避免只靠颜色传达
const capText = computed(() => {
  if (capCls.value === "over") return "已超出";
  if (capCls.value === "empty") return "尚未填写";
  if (capCls.value === "low") return "偏少";
  return "数量合理";
});
const capChipCls = computed(() => {
  if (capCls.value === "over") return "xf-chip--reach";
  if (capCls.value === "ok") return "xf-chip--safe";
  return "xf-chip--est";
});
const capInfo = computed(() => (volLimit.value ? {
  volLimit: volLimit.value, adjust: adjust.value,
  filledCount: filledCount.value, levelCounts: levelCounts.value,
} : null));

// S8-D：按可及性排序的填报顺序（纯函数，随 rows 变动实时重算）
const fillOrder = computed(() => buildFillOrder(plan.value, rows.value));
// S9-B：跨年/跨批次的行底色高亮（避免在模板表达式里写 && 触发编译器告警）
function foRowClass(it) {
  return it && it.has_line_data && !it.comparable ? "fo-row fo-row-warn" : "fo-row";
}

// S4 验收点：保底安全网红灯数可见。
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
const breachTile = computed(() => {
  if (breach.value.cls === "danger") return "xf-tile--danger";
  if (breach.value.cls === "ok") return "xf-tile--safe";
  return "";
});
const breachIcon = computed(() => {
  if (breach.value.cls === "danger") return "alert";
  if (breach.value.cls === "ok") return "shield";
  return "info";
});
const breachColor = computed(() => {
  if (breach.value.cls === "danger") return "#ff8787";
  if (breach.value.cls === "ok") return "#5fd87f";
  return "#8f96a2";
});

function rowBreach(r) {
  return breachStatus(plan.value && plan.value.user_rank, r);
}

function loadPlanFromStorage() {
  const p = uni.getStorageSync(PLAN_KEY);
  if (!p) return;
  plan.value = p;
  if (p.adjust) adjust.value = { 冲: true, 稳: true, 保: true, ...p.adjust };
  // 回填上次手填的拟报专业，避免离开页面后全部丢失
  rows.value = applyMajors(flattenPlan(p), p.majors);
  // S10-B：拉取本省志愿个数上限（缺数据不阻断志愿表使用）
  if (p.province) {
    api.volunteerLimit(p.province)
      .then((r) => { volLimit.value = r; })
      .catch(() => { /* 上限数据缺失时静默降级，仅不显示上限卡片 */ });
  }
}

onLoad(loadPlanFromStorage);
// tab 页：从「我能上哪 / 院校池」switchTab 过来时草稿可能已更新，重新载入
onShow(loadPlanFromStorage);

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

// S10-B：各组「服从专业调剂」开关（仅院校专业组模式有意义）。
function toggleAdjust(level) {
  adjust.value = { ...adjust.value, [level]: !adjust.value[level] };
  if (plan.value) {
    plan.value.adjust = adjust.value;
    try {
      uni.setStorageSync(PLAN_KEY, { ...plan.value, majors: collectMajors(rows.value) });
    } catch (e) { /* 存储失败不阻断 */ }
  }
}

// S10-B：组内专业排序——在同档（冲/稳/保）内上下移动某行，调整填报顺序显示与导出顺序。
function move(key, dir) {
  const p = plan.value;
  if (!p || !Array.isArray(p.tiers)) return;
  for (const t of p.tiers) {
    const schools = t.schools || [];
    const idx = schools.findIndex((s) => (t.tier + "-" + s.name) === key);
    if (idx >= 0) {
      const j = dir === "up" ? idx - 1 : idx + 1;
      if (j < 0 || j >= schools.length) return;
      const arr = schools.slice();
      const tmp = arr[idx]; arr[idx] = arr[j]; arr[j] = tmp;
      t.schools = arr;
      break;
    }
  }
  rows.value = applyMajors(flattenPlan(p), p.majors);
}

function buildText() {
  return buildPlanText(plan.value, groups.value, timeLabel.value, capInfo.value);
}

function copy() {
  const text = buildText();
  uni.setClipboardData({
    data: text,
    success: () => toast.show("已复制志愿表文本"),
  });
}

function toggleFillOrder() {
  showFillOrder.value = !showFillOrder.value;
}

function copyFillOrder() {
  if (!fillOrder.value.total) {
    toast.show("志愿表为空，暂无顺序建议");
    return;
  }
  uni.setClipboardData({
    data: buildFillOrderText(plan.value, fillOrder.value, timeLabel.value, capInfo.value),
    success: () => toast.show("已复制填报顺序清单"),
  });
}

function goRecommend() {
  uni.switchTab({ url: "/pages/recommend/recommend" });
}
function goCompass() {
  uni.navigateTo({ url: "/pages/compass/compass" });
}

// S5-C 保底失守一键补位：拉取更低层次、用户位次可稳够的兜底院校并入「保」档。
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
    const d = diffSafePatch(plan.value, picks);
    if (!d.added.length) {
      toast.show("候选兜底院校都已在志愿表里，无需重复补位");
      return;
    }
    const next = d.next;
    plan.value = next;
    patchDiff.value = d;
    rows.value = applyMajors(flattenPlan(next), next.majors || collectMajors(rows.value));
    uni.setStorageSync(PLAN_KEY, next);
    toast.show(d.text);
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
.page { padding: 24rpx 24rpx 80rpx; min-height: 100vh; background: var(--xf-bg); }

.print-head { display: none; }

.section { margin-bottom: 22rpx; }
.actions { display: flex; flex-direction: column; gap: 14rpx; margin-top: 16rpx; }

/* 空状态 */
.empty-wrap { margin-top: 12rpx; }
.empty-card { padding-bottom: 12rpx; }

/* 条件卡 */
.meta-card { padding: 18rpx 22rpx; }
.meta-row { display: flex; align-items: center; gap: 12rpx; min-height: 44rpx; }
.meta-line { flex: 1; font-size: 24rpx; color: var(--xf-text-2); line-height: 1.6; }
.meta-time { font-size: 20rpx; color: var(--xf-text-4); }

/* 志愿上限 */
.cap-card { padding: 22rpx; }
.cap--over { border-color: rgba(229, 72, 77, 0.5); }
.cap-head { display: flex; align-items: center; gap: 16rpx; }
.cap-num-wrap { display: flex; align-items: baseline; gap: 4rpx; }
.cap-num { font-size: 52rpx; font-weight: 700; line-height: 1; font-variant-numeric: tabular-nums; }
.cap-num.ok { color: var(--xf-safe); }
.cap-num.low { color: var(--xf-reach); }
.cap-num.over { color: var(--xf-danger-text); }
.cap-num.empty { color: var(--xf-text-3); }
.cap-den { font-size: 24rpx; color: var(--xf-text-4); }
.cap-head-body { flex: 1; min-width: 0; }
.cap-title { display: block; font-size: 25rpx; font-weight: 600; color: var(--xf-text); }
.cap-sub { display: block; margin-top: 2rpx; font-size: 20rpx; color: var(--xf-text-4); }

/* 分段进度条：每 5% 一格，比纯色条更容易估出比例 */
.cap-bar {
  height: 16rpx; margin: 18rpx 0 12rpx; border-radius: 8rpx; overflow: hidden;
  background: repeating-linear-gradient(90deg, var(--xf-surface-3) 0 5%, var(--xf-bg) 5% 5.6%);
}
.cap-fill { height: 100%; border-radius: 8rpx; transition: width 260ms var(--xf-ease); }
.cap-fill.ok { background: linear-gradient(90deg, #3f9f5c, var(--xf-safe)); }
.cap-fill.low { background: linear-gradient(90deg, #b07a26, var(--xf-reach)); }
.cap-fill.over { background: linear-gradient(90deg, #a33135, var(--xf-danger)); }
.cap-fill.empty { background: transparent; }

.cap-levels { display: flex; align-items: center; gap: 12rpx; flex-wrap: wrap; }
.cap-lvl { font-size: 20rpx; padding: 3rpx 12rpx; border-radius: 6rpx; background: rgba(255, 255, 255, 0.04); }
.cap-lvl.reach { color: var(--xf-reach); }
.cap-lvl.match { color: var(--xf-match); }
.cap-lvl.safe { color: var(--xf-safe); }
.cap-suggest { font-size: 20rpx; color: var(--xf-text-4); }
.cap-note { display: block; margin-top: 10rpx; font-size: 19rpx; color: var(--xf-text-4); line-height: 1.6; }

/* 保底安全网 */
.safe-net { padding: 20rpx; }
.safe-net.danger { border-color: rgba(229, 72, 77, 0.5); background: rgba(229, 72, 77, 0.07); }
.safe-net.ok { border-color: rgba(95, 216, 127, 0.36); background: rgba(95, 216, 127, 0.05); }
.safe-head { display: flex; align-items: center; gap: 14rpx; }
.safe-head-body { flex: 1; min-width: 0; }
.safe-title { display: block; font-size: 24rpx; color: var(--xf-text-3); }
.safe-count { display: block; margin-top: 2rpx; font-size: 28rpx; font-weight: 700; }
.safe-count.danger { color: var(--xf-danger-text); }
.safe-count.ok { color: var(--xf-safe); }
.safe-count.muted { color: var(--xf-text-3); }
.safe-desc { display: block; margin-top: 12rpx; font-size: 21rpx; color: var(--xf-text-3); line-height: 1.7; }

.patch-diff { margin-top: 16rpx; padding: 16rpx; border-radius: var(--xf-r-sm); background: rgba(95, 216, 127, 0.06); border: 1rpx solid rgba(95, 216, 127, 0.3); }
.patch-title { display: block; font-size: 23rpx; font-weight: 600; color: var(--xf-text-2); margin-bottom: 6rpx; }
.patch-line { display: block; font-size: 21rpx; color: var(--xf-text-3); line-height: 1.7; }
.patch-good { color: var(--xf-safe); }
.patch-line.warn { color: var(--xf-danger-text); }
.patch-line.muted { color: var(--xf-text-4); }

/* 档位分组 */
.grp { margin-bottom: 22rpx; }
.grp-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8rpx; }
.grp-head-left { display: flex; align-items: center; gap: 10rpx; }
.grp-title { font-size: 27rpx; font-weight: 700; }
.grp-title.reach { color: var(--xf-reach); }
.grp-title.match { color: var(--xf-match); }
.grp-title.safe { color: var(--xf-safe); }
.grp-count { font-size: 20rpx; color: var(--xf-text-4); background: rgba(255, 255, 255, 0.05); border-radius: 6rpx; padding: 1rpx 10rpx; }
.grp-sub { font-size: 19rpx; color: var(--xf-text-4); }
.grp-empty { display: block; font-size: 21rpx; color: var(--xf-text-4); padding: 12rpx 0; line-height: 1.6; }

/* 行 */
.row { display: flex; align-items: center; gap: 10rpx; padding: 16rpx 0; border-bottom: 1rpx solid var(--xf-line-soft); }
.row-idx { width: 40rpx; font-size: 21rpx; color: var(--xf-text-4); font-variant-numeric: tabular-nums; }
.row-info { flex: 1; min-width: 0; }
.row-name-line { display: flex; align-items: center; gap: 8rpx; }
.row-name { font-size: 25rpx; color: var(--xf-text); font-weight: 600; }
.row-meta { display: block; font-size: 20rpx; color: var(--xf-text-4); margin-top: 3rpx; }
.row-breach { font-size: 18rpx; color: #fff; background: var(--xf-danger); border-radius: 5rpx; padding: 1rpx 7rpx; }
.row-breach-tip { display: block; font-size: 19rpx; color: var(--xf-danger-text); margin-top: 4rpx; line-height: 1.5; }
.row-right { display: flex; align-items: center; gap: 8rpx; }
.row-major { width: 210rpx; font-size: 22rpx; color: var(--xf-text-2); border: 1rpx solid var(--xf-line); border-radius: var(--xf-r-sm); padding: 8rpx 12rpx; min-height: 56rpx; }
.row-actions { display: flex; flex-direction: column; gap: 2rpx; }
.row-move { width: 56rpx; height: 44rpx; display: flex; align-items: center; justify-content: center; border-radius: 8rpx; }
.row-move:active { background: rgba(255, 210, 77, 0.14); }

/* 服从调剂开关 */
.grp-adjust { display: flex; align-items: center; gap: 10rpx; min-height: 64rpx; padding-left: 12rpx; }
.adj-label { font-size: 20rpx; color: var(--xf-text-3); }
.adj-switch { min-width: 56rpx; height: 38rpx; padding: 0 6rpx; border-radius: 19rpx; display: flex; align-items: center; justify-content: center; font-size: 18rpx; }
.adj-switch.on { background: rgba(95, 216, 127, 0.18); color: var(--xf-safe); border: 1rpx solid rgba(95, 216, 127, 0.5); }
.adj-switch.off { background: rgba(229, 72, 77, 0.14); color: var(--xf-danger-text); border: 1rpx solid rgba(229, 72, 77, 0.42); }

.fill-stat { display: block; font-size: 21rpx; color: var(--xf-text-4); margin-bottom: 12rpx; }

/* 填报顺序 */
.fill-order { margin-top: 18rpx; padding: 18rpx; border-radius: var(--xf-r-sm); background: var(--xf-surface); border: 1rpx solid var(--xf-line); }
.fo-title { display: block; font-size: 24rpx; font-weight: 600; color: var(--xf-text-2); }
.fo-ref { display: flex; align-items: center; gap: 10rpx; margin: 8rpx 0; }
.fo-ref-tag { font-size: 19rpx; color: var(--xf-real); background: rgba(109, 179, 242, 0.12); border-radius: 6rpx; padding: 2rpx 10rpx; }
.fo-ref-text { font-size: 20rpx; color: var(--xf-text-3); }
.fo-basis { display: block; font-size: 20rpx; color: var(--xf-text-4); line-height: 1.6; margin: 6rpx 0 10rpx; }
.fo-row { display: flex; align-items: flex-start; padding: 7rpx 0; }
.fo-row-warn { background: rgba(240, 173, 78, 0.07); border-radius: 8rpx; }
.fo-seq { width: 44rpx; font-size: 21rpx; color: var(--xf-text-4); font-variant-numeric: tabular-nums; }
.fo-main { flex: 1; }
.fo-name { display: block; font-size: 22rpx; color: var(--xf-text-2); }
.fo-meta { display: block; font-size: 19rpx; color: var(--xf-text-4); margin-top: 2rpx; }
.fo-warn { display: inline-block; font-size: 18rpx; color: var(--xf-reach); background: rgba(240, 173, 78, 0.12); border-radius: 6rpx; padding: 1rpx 8rpx; margin-top: 4rpx; }
.fo-note { display: block; font-size: 19rpx; color: var(--xf-text-4); line-height: 1.6; margin-top: 8rpx; }
.fo-note.warn { color: var(--xf-reach); }

.disclaimer { display: flex; align-items: flex-start; gap: 10rpx; margin-top: 22rpx; }
.disclaimer-t { flex: 1; font-size: 20rpx; color: var(--xf-text-4); line-height: 1.7; }

/* ---------------- 打印：A4 浅色版式 ---------------- */
@media print {
  .no-print { display: none !important; }
  .page { padding: 0; background: #ffffff; }
  .print-head { display: block; margin-bottom: 18rpx; padding-bottom: 10rpx; border-bottom: 2px solid #111; }
  .print-title { display: block; font-size: 20pt; font-weight: 700; color: #111; }
  .print-meta { display: block; margin-top: 4rpx; font-size: 9pt; color: #444; }

  .xf-card, .cap-card, .safe-net, .fill-order {
    background: #fff !important; border: 1px solid #bbb !important;
    border-radius: 0 !important; box-shadow: none !important;
    break-inside: avoid; page-break-inside: avoid;
  }
  .meta-line, .cap-title, .cap-num, .safe-count, .grp-title,
  .row-name, .fo-title, .fo-name { color: #111 !important; }
  .meta-time, .cap-sub, .cap-note, .cap-suggest, .safe-desc, .row-meta,
  .row-idx, .fo-meta, .fo-basis, .fo-note, .disclaimer-t, .grp-count { color: #555 !important; }
  .row { border-bottom: 1px solid #ddd; break-inside: avoid; page-break-inside: avoid; }
  .row-major { border: none !important; border-bottom: 1px solid #999 !important; border-radius: 0 !important; width: 150px; }
  .grp { break-inside: avoid-page; }
  .cap-bar { height: 6px; }
  @page { size: A4; margin: 14mm 12mm; }
}
</style>
