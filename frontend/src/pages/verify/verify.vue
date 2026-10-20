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
          <wd-button plain block @click="goRecommend">查看院校推荐（冲/稳/保 院校池）</wd-button>
        </view>
        <text v-if="err" class="err">{{ err }}</text>
      </view>

      <!-- C2 等位分换算：跨年换算分数/位次 -->
      <view class="section">
        <view class="section-head">
          <text class="h3">等位分换算（跨年）</text>
          <wd-tag type="primary" plain>C2</wd-tag>
        </view>
        <text class="small">用上方省份/科类，把某一年的分数或位次换算到另一年；锚点是稀疏批次线，区间外为外推值。</text>
        <text v-if="eqHint" class="small warn-text">{{ eqHint }}</text>

        <wd-cell-group border>
          <wd-picker v-model="eq.year" label="源年份" :columns="yearLabels" placeholder="请选择" label-width="30%"></wd-picker>
          <wd-picker v-model="eq.target" label="目标年份" :columns="yearLabels" placeholder="请选择" label-width="30%"></wd-picker>
          <wd-input v-model="eq.score" label="源年分数" type="digit" placeholder="可空（默认用上方位次）" label-width="30%"></wd-input>
        </wd-cell-group>

        <view class="actions">
          <wd-button type="primary" plain block :loading="eqLoading" @click="runEquiv">换算等位分</wd-button>
        </view>
        <text v-if="eqErr" class="err">{{ eqErr }}</text>

        <view v-if="eqRes" class="eq-box">
          <view class="eq-line">
            <text class="eq-k">{{ eqRes.from.year }} 年</text>
            <text class="eq-v">≈{{ eqRes.from.score }} 分 / 位次 {{ eqRes.from.rank }}</text>
          </view>
          <view class="eq-line">
            <text class="eq-k">{{ eqRes.to.year }} 年</text>
            <text class="eq-v">≈{{ eqRes.to.score }} 分 / 位次 {{ eqRes.to.rank }}</text>
          </view>
          <view class="eq-line">
            <text class="eq-k">等效分差</text>
            <text class="eq-v">{{ deltaLabel }}</text>
          </view>
          <text class="small">换算方法：{{ methodLabel }}</text>
          <text v-if="eqRes.caveat" class="small warn-text">{{ eqRes.caveat }}</text>
          <text class="dsrc">{{ eqRes.note }}</text>

          <wd-collapse v-model="eqOpen">
            <wd-collapse-item title="查看目标年锚点（位次→分数）" name="anchors">
              <view class="anchor" v-for="a in eqRes.to.anchors" :key="a.tier">
                <text class="anchor-t">{{ a.tier }}</text>
                <text class="anchor-v">{{ a.score }} 分 / 位次 {{ a.rank }}</text>
              </view>
            </wd-collapse-item>
          </wd-collapse>
        </view>
      </view>

      <!-- 批量核验：P1→P2 打通 -->
      <view class="section" v-if="batchMode">
        <view class="section-head">
          <text class="h3">批量核验（画布推荐方向）</text>
          <wd-tag type="primary" plain>一次算完</wd-tag>
        </view>
        <text class="small">点按可增删待核验专业；结果按「不可及 → 低位次 → 一本 → 高层次」排序（风险优先），先看最受限项。</text>
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
          <text class="sum-i out_of_reach">不可及 {{ batch.summary.out_of_reach }}</text>
          <text class="sum-i low">低位次 {{ batch.summary.low }}</text>
          <text class="sum-i mid">一本 {{ batch.summary.mid }}</text>
          <text class="sum-i high">高层次 {{ batch.summary.high }}</text>
        </view>
        <view class="sum align-sum">
          <text class="sum-i refuted">数据不可及 {{ batch.summary.alignment.refuted }}</text>
          <text class="sum-i unverified">数据未覆盖 {{ batch.summary.alignment.unverified }}</text>
          <text class="sum-i supported">数据可及 {{ batch.summary.alignment.supported }}</text>
        </view>
        <view v-for="r in batch.results" :key="r.major" class="brow" @click="openOne(r.major)">
          <view class="brow-head">
            <text class="brow-name">{{ r.major }}</text>
            <view class="brow-tags">
              <wd-tag :type="alignType(r.alignment)" plain>{{ r.alignment_label }}</wd-tag>
              <wd-tag :type="reachType(r.reachability)" plain>{{ r.reachability_label }}</wd-tag>
            </view>
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

        <view class="align unverified">
          <text class="align-label">{{ res.alignment_label }}</text>
          <text class="align-sub">{{ res.alignment_message }}</text>
        </view>

        <!-- S2 对置版式：观点 × 真实校线，双来源 + 原始数据点击可达 -->
        <view class="oppo" v-if="res.sources && res.sources.length">
          <view class="section-head">
            <text class="h3">对置核验 · 两种来源</text>
            <wd-tag type="primary" plain>真实校线已接入</wd-tag>
          </view>
          <view class="oppo-grid">
            <view class="oppo-col">
              <text class="oppo-tag opinion">① 观点来源</text>
              <text class="oppo-src">{{ res.sources[0].source }}</text>
              <text v-if="res.sources[0].evidence_grade" class="oppo-g">证据等级：{{ res.sources[0].evidence_grade }}</text>
              <text class="oppo-note">{{ res.sources[0].note }}</text>
              <text v-if="res.sources[0].url" class="dsrc link" @click="openRaw(res.sources[0].url)">查看观点出处 ↗</text>
            </view>
            <view class="oppo-col data">
              <text class="oppo-tag data">② 数据来源（真实校线）</text>
              <text class="oppo-src">{{ res.sources[1].source }}</text>
              <text class="oppo-note">{{ res.sources[1].note }}</text>
              <view class="oppo-tiers" v-if="res.sources[1].tiers">
                <text class="ot">985 {{ res.sources[1].tiers['985'] }}</text>
                <text class="ot">211 {{ res.sources[1].tiers['211'] }}</text>
                <text class="ot">本科 {{ res.sources[1].tiers['benke'] }}</text>
                <text class="ot">专科 {{ res.sources[1].tiers['zhuanke'] }}</text>
              </view>
              <text v-if="res.sources[1].url" class="dsrc link" @click="openRaw(res.sources[1].url)">查看数据入口 ↗</text>
            </view>
          </view>

          <!-- 原始数据点击可达：逐条真实校线 -->
          <view class="raw" v-if="res.raw_records && res.raw_records.length">
            <view class="section-head">
              <text class="h3">真实校线（逐条 · 点开即原始数据）</text>
              <text class="bk-sub" v-if="res.real_data">共 {{ res.real_data.total_lines }} 条 / 可触及 {{ res.real_data.reachable }}</text>
            </view>
            <view class="raw-row" v-for="(rec, i) in res.raw_records" :key="i" @click="openRaw(rec.source_url)">
              <text class="raw-u">{{ rec.university }}</text>
              <text class="raw-t" v-if="rec.tier">{{ rec.tier }}</text>
              <text class="raw-r">位次 {{ rec.min_rank }} · {{ rec.min_score }}分</text>
              <text class="raw-go">原始↗</text>
            </view>
            <text class="dsrc">每条均为掌上高考 2025 真实录取记录（data_source=estimated_real）；点击任意行打开该院校原始 JSON 核验（GitHub 公开仓库，MIT）。</text>
          </view>
          <view class="data-missing" v-else-if="res.real_data && !res.real_data.has_data">
            <text class="dm-label">⚠ 数据未覆盖（单侧降级）</text>
            <text class="dm-sub">该 (省/科类) 暂无真实校线，仅展示观点侧；不出现「一致/冲突」横幅，不编造数据。</text>
          </view>
        </view>

        <view class="reach" :class="res.reachability">
          <text class="reach-label">{{ res.reachability_label }}</text>
          <text class="reach-sub">{{ res.reachability_message }}</text>
        </view>

        <view class="block meta">
          <text class="bk">证据等级（双向置信）</text>
          <view class="chips">
            <text class="chip">观点 {{ res.evidence_grade || "—" }}</text>
            <text class="chip">数据 {{ dataGradeLabel(res.data_source) }}</text>
          </view>
          <text v-if="res.view_source" class="dsrc">观点来源：{{ res.view_source }}</text>
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
import { computed, reactive, ref, watch } from "vue";
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

// —— C2 等位分换算 ——
const eq = reactive({ year: "", target: "", score: "" });
const years = ref([]);
const eqRes = ref(null);
const eqErr = ref("");
const eqLoading = ref(false);
const eqOpen = ref("");

const yearLabels = computed(() => years.value.map((y) => y.year + " · " + dsLabel(y.data_source)));
// 等位分可用性提示（抽成 computed：模板里写复合 v-else-if 会编译失败，是踩过的坑）
const eqHint = computed(() => {
  if (!p.province || !p.subject) return "";
  if (years.value.length === 1) {
    return `该省/科类目前只有 ${years.value[0].year} 年有可用锚点（${dsLabel(years.value[0].data_source)}），暂无法跨年换算。`;
  }
  if (!years.value.length) return "该省/科类暂无可用锚点（后端未连接或数据未覆盖），无法跨年换算。";
  return "";
});
const deltaLabel = computed(() => {
  const r = eqRes.value;
  if (!r) return "";
  const d = r.delta_score;
  const word = d > 0 ? "更高" : d < 0 ? "更低" : "持平";
  return (d > 0 ? "+" : "") + d + " 分（目标年" + word + "）";
});
const methodLabel = computed(() => {
  const m = eqRes.value && eqRes.value.method;
  return m === "percentile" ? "按考生规模归一（percentile）" : "同位次等效分（rank）";
});

function dsLabel(ds) {
  if (ds === "official") return "官方";
  if (ds === "official_table") return "一分一段表";
  if (ds === "estimated") return "估算";
  return "样例";
}

// picker 的值是 "2024 · 官方" 这类标签，取前四位年份数字
function yearOf(v) {
  const m = String(v || "").match(/\d{4}/);
  return m ? Number(m[0]) : 0;
}

async function loadYears() {
  if (!p.province || !p.subject) return;
  try {
    const j = await api.equivYears(p.province, p.subject);
    years.value = j.years || [];
    if (years.value.length >= 2 && !eq.year) {
      eq.year = yearLabels.value[0];
      eq.target = yearLabels.value[1];
    }
  } catch (e) {
    years.value = [];   // 后端未连接时静默，不打断主流程
  }
}

async function runEquiv() {
  eqErr.value = "";
  if (!p.province || !p.subject) {
    toast.show("请先选择省份 / 科类");
    return;
  }
  const y = yearOf(eq.year);
  const t = yearOf(eq.target);
  if (!y || !t) {
    toast.show("请先选择源年份与目标年份");
    return;
  }
  const params = { province: p.province, subject: p.subject, year: y, target_year: t };
  if (eq.score) params.score = Number(eq.score);
  else if (p.user_rank) params.rank = Number(p.user_rank);
  else {
    toast.show("请填写位次或分数");
    return;
  }
  eqLoading.value = true;
  try {
    eqRes.value = await api.equivConvert(params);
  } catch (e) {
    eqErr.value = "换算失败（后端未连接？）：" + (e.message || e);
  } finally {
    eqLoading.value = false;
  }
}

// 省份/科类变化后刷新可用年份
watch(() => p.province + "|" + p.subject, loadYears);

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

function reachType(reach) {
  return { out_of_reach: "danger", low: "warning", mid: "primary", high: "success" }[reach] || "default";
}

function alignType(alignment) {
  return { refuted: "danger", unverified: "warning", supported: "success" }[alignment] || "default";
}

function dataGradeLabel(ds) {
  if (ds === "official_overlay" || ds === "real") return "官方/真实";
  if (ds === "estimated") return "估算";
  return "样例";
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

// 带着省份/科类/位次进入「院校推荐」页
function goRecommend() {
  if (!p.province || !p.subject || !p.user_rank) {
    toast.show("请先填写省份 / 科类 / 位次");
    return;
  }
  const q = `province=${encodeURIComponent(p.province)}&subject=${encodeURIComponent(p.subject)}&user_rank=${encodeURIComponent(p.user_rank)}`;
  uni.navigateTo({ url: `/pages/recommend/recommend?${q}` });
}

// S2：原始数据点击可达——跳应用内 web-view 承载真实源（GitHub 原始 JSON / 观点出处）
function openRaw(url) {
  if (!url) {
    toast.show("该来源暂无可点击的原始链接");
    return;
  }
  uni.navigateTo({
    url: "/pages/webview/webview?src=" + encodeURIComponent(url),
    fail: () => {
      // 兜底：复制到剪贴板，便于在浏览器核验
      uni.setClipboardData({ data: url });
      toast.show("原始数据链接已复制到剪贴板");
    },
  });
}

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

.align { border-radius: 12rpx; padding: 14rpx 16rpx; margin: 6rpx 0 14rpx; background: #1c1f26; border: 1px solid #2a2e37; }
.align-label { display: block; font-size: 26rpx; font-weight: 700; color: #8a909c; }
.align-sub { display: block; margin-top: 6rpx; font-size: 21rpx; color: #6b7280; line-height: 1.6; }

.reach { border-radius: 12rpx; padding: 14rpx 16rpx; margin-bottom: 16rpx; border: 1px solid #2a2e37; }
.reach-label { display: block; font-size: 26rpx; font-weight: 700; }
.reach-sub { display: block; margin-top: 6rpx; font-size: 21rpx; color: #c7ccd4; line-height: 1.7; }
.reach.out_of_reach { background: #2a1414; border-color: #4a2222; }
.reach.out_of_reach .reach-label { color: #ff6b6b; }
.reach.low { background: #2a2214; border-color: #4a3a18; }
.reach.low .reach-label { color: #f0ad4e; }
.reach.mid { background: #15233a; border-color: #243a55; }
.reach.mid .reach-label { color: #6db3f2; }
.reach.high { background: #142a1a; border-color: #224a2c; }
.reach.high .reach-label { color: #5fd87f; }

/* S2 对置版式：观点 × 真实校线 */
.oppo { margin-bottom: 20rpx; background: #16191f; border: 1px solid #23262e; border-radius: 12rpx; padding: 16rpx; }
.oppo-grid { display: flex; gap: 14rpx; margin-bottom: 14rpx; }
.oppo-col { flex: 1; background: #0f1115; border: 1px solid #2a2e37; border-radius: 12rpx; padding: 14rpx; display: flex; flex-direction: column; }
.oppo-col.data { border-color: #243a55; }
.oppo-tag { font-size: 23rpx; font-weight: 700; padding: 4rpx 10rpx; border-radius: 8rpx; align-self: flex-start; margin-bottom: 10rpx; }
.oppo-tag.opinion { color: #ffd24d; background: #2a2410; }
.oppo-tag.data { color: #6db3f2; background: #15233a; }
.oppo-src { font-size: 22rpx; color: #e6e8ec; line-height: 1.6; }
.oppo-g { font-size: 20rpx; color: #5fd87f; margin-top: 6rpx; }
.oppo-note { font-size: 20rpx; color: #8a909c; line-height: 1.6; margin-top: 8rpx; }
.oppo-tiers { display: flex; flex-wrap: wrap; gap: 8rpx; margin-top: 10rpx; }
.ot { font-size: 19rpx; padding: 4rpx 10rpx; border-radius: 999rpx; border: 1px solid #2a3a55; color: #6db3f2; background: #0f1115; }
.link { text-decoration: underline; cursor: pointer; }

.raw { margin-top: 6rpx; }
.raw-row { display: flex; align-items: center; gap: 10rpx; padding: 10rpx 12rpx; background: #0f1115; border: 1px solid #2a2e37; border-radius: 10rpx; margin-bottom: 8rpx; }
.raw-row:active { border-color: #6db3f2; }
.raw-u { font-size: 23rpx; color: #e6e8ec; font-weight: 600; flex: 1; }
.raw-t { font-size: 19rpx; color: #ffd24d; padding: 2rpx 8rpx; border-radius: 6rpx; background: #2a2410; }
.raw-r { font-size: 20rpx; color: #8a909c; }
.raw-go { font-size: 20rpx; color: #6db3f2; }
.data-missing { margin-top: 6rpx; padding: 14rpx 16rpx; background: #1c1f26; border: 1px dashed #4a3a18; border-radius: 12rpx; }
.dm-label { display: block; font-size: 24rpx; color: #f0ad4e; font-weight: 700; }
.dm-sub { display: block; margin-top: 6rpx; font-size: 21rpx; color: #8a909c; line-height: 1.6; }

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
.sum { display: flex; flex-wrap: wrap; gap: 12rpx; margin-bottom: 14rpx; }
.sum-i { font-size: 22rpx; padding: 6rpx 16rpx; border-radius: 999rpx; border: 1px solid #2a2e37; }
.sum-i.out_of_reach { color: #ff6b6b; border-color: #4a2222; background: #2a1414; }
.sum-i.low { color: #f0ad4e; border-color: #4a3a18; background: #2a2214; }
.sum-i.mid { color: #6db3f2; border-color: #243a55; background: #15233a; }
.sum-i.high { color: #5fd87f; border-color: #224a2c; background: #142a1a; }
.sum-i.refuted { color: #ff6b6b; border-color: #4a2222; background: #2a1414; }
.sum-i.unverified { color: #f0ad4e; border-color: #4a3a18; background: #2a2214; }
.sum-i.supported { color: #5fd87f; border-color: #224a2c; background: #142a1a; }
.align-sum { margin-top: -6rpx; }
.brow { background: #16191f; border: 1px solid #23262e; border-radius: 12rpx; padding: 14rpx 16rpx; margin-bottom: 10rpx; }
.brow-head { display: flex; align-items: center; justify-content: space-between; gap: 12rpx; }
.brow-name { font-size: 26rpx; color: #e6e8ec; font-weight: 600; }
.brow-tags { display: flex; gap: 8rpx; }
.brow-meta { display: block; margin-top: 8rpx; font-size: 21rpx; color: #8a909c; line-height: 1.6; }

/* C2 等位分换算 */
.eq-box { margin-top: 18rpx; background: #16191f; border: 1px solid #23262e; border-radius: 12rpx; padding: 16rpx; }
.eq-line { display: flex; align-items: center; justify-content: space-between; padding: 8rpx 0; }
.eq-k { font-size: 23rpx; color: #8a909c; }
.eq-v { font-size: 25rpx; color: #e6e8ec; font-weight: 600; }
.warn-text { color: #f0ad4e; }
.anchor { display: flex; align-items: center; justify-content: space-between; padding: 6rpx 0; }
.anchor-t { font-size: 22rpx; color: #8a909c; }
.anchor-v { font-size: 22rpx; color: #c7ccd4; }

.dsrc { font-size: 21rpx; color: #6db3f2; display: block; margin-top: 8rpx; line-height: 1.6; }
.meta { background: #16191f; border: 1px solid #23262e; border-radius: 12rpx; padding: 14rpx 16rpx; }
.chips { display: flex; flex-wrap: wrap; gap: 12rpx; margin: 8rpx 0 4rpx; }
.chip { font-size: 21rpx; padding: 6rpx 16rpx; border-radius: 999rpx; border: 1px solid #2a2e37; color: #c7ccd4; background: #1c1f26; }
.uni-wrap { display: flex; flex-wrap: wrap; gap: 10rpx; padding: 4rpx 0 10rpx; }
.msg { background: #1c1f26; border-radius: 12rpx; padding: 16rpx; }
.sg { font-size: 23rpx; color: #c7ccd4; line-height: 1.8; }
.err { display: block; font-size: 22rpx; color: #ff6b6b; margin-top: 12rpx; line-height: 1.5; }
</style>
