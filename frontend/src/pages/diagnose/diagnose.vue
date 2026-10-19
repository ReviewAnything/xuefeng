<template>
  <view class="page">
    <view class="hero">
      <text class="h1">自我诊断画布</text>
      <text class="sub">灵魂八连问 → 输出决策框架，不是录取结论。所有输入仅存于本机。</text>
    </view>

    <view class="card">
      <text class="h3">① 填写你的现实条件</text>
      <view v-for="q in questions" :key="q.id" class="field">
        <text class="fl">{{ q.label }}</text>
        <picker v-if="q.type === 'select'" class="picker" mode="selector" :range="q.options" @change="onPick(q.id, $event)">
          <view class="picker-text">{{ form[q.id] || '请选择' }}</view>
        </picker>
        <input v-else class="input" v-model="form[q.id]" :placeholder="q.placeholder" />
        <text class="hint">{{ q.hint }}</text>
      </view>

      <view class="field">
        <text class="fl">高考位次（选填，用于数据侧核验）</text>
        <input class="input" v-model="rankInput" type="number" placeholder="如：40000" />
        <text class="hint">填了位次，可一键拉取后端按位次筛出的 冲/稳/保 可达专业。</text>
      </view>

      <view class="row gap">
        <button class="btn primary" @click="run">生成决策画布</button>
        <button class="btn" @click="clear">清空</button>
      </view>
      <text class="tip">本工具体现张雪峰"普通家庭+就业导向"视角，并已加入偏见校正层，请结合自身判断。</text>
    </view>

    <view class="card" v-if="canvas">
      <text class="h3">② 决策画布</text>
      <view class="cv-block">
        <text class="cv-k">首要策略</text>
        <rich-text :nodes="canvas.strategy"></rich-text>
      </view>
      <view class="cv-block">
        <text class="cv-k">推荐方向（框架，非定论）</text>
        <view class="tags">
          <text v-for="p in canvas.picks" :key="p.name" class="tagx" :class="p.view === 'recommend' ? 'good' : 'info'">{{ p.name }}</text>
        </view>
        <text class="small">以上由你的条件过滤得出，需到「专业图谱」逐条核对理由与偏见校正。</text>
      </view>
      <view class="cv-block warn">
        <text class="cv-k">偏见校正</text>
        <rich-text :nodes="canvas.biasWarn"></rich-text>
      </view>
      <view class="cv-block">
        <text class="cv-k">重点避坑</text>
        <text>同条件下建议谨慎：{{ canvas.avoidHint.join("、") }} 等（详见专业图谱与开源资源核验）。</text>
      </view>
      <view class="cv-block">
        <text class="cv-k">下一步动作</text>
        <view v-for="(n, i) in canvas.next" :key="i" class="next">· {{ n }}</view>
      </view>
      <view class="cv-foot">⚠️ 这是决策框架，不是录取结论。请以各省考试院官方数据为准。</view>
    </view>

    <view class="card" v-if="form.province && form.subject && rankInput">
      <text class="h3">③ 数据侧：按位次拉取可达专业</text>
      <button class="btn" :disabled="loading" @click="enrich">{{ loading ? "核验中…" : "调用后端核验可达专业" }}</button>
      <view v-if="search" class="verify-box">
        <text class="dsrc">数据源：{{ search.data_source === 'real' ? '真实录取记录' : '参数化样例（演示）' }}</text>
        <view class="tier-group">
          <text class="tg-title">冲（够一够）</text>
          <text v-for="m in search.reach" :key="'r'+m.major" class="tg-item">· {{ m.major }}（{{ m.best_tier }} · 约{{ m.best_rank }}名）</text>
          <text v-if="!search.reach.length" class="tg-empty">—</text>
        </view>
        <view class="tier-group">
          <text class="tg-title">稳（大概率）</text>
          <text v-for="m in search.match" :key="'m'+m.major" class="tg-item">· {{ m.major }}（{{ m.best_tier }} · 约{{ m.best_rank }}名）</text>
          <text v-if="!search.match.length" class="tg-empty">—</text>
        </view>
        <view class="tier-group">
          <text class="tg-title">保（兜底）</text>
          <text v-for="m in search.safe" :key="'s'+m.major" class="tg-item">· {{ m.major }}（{{ m.best_tier }} · 约{{ m.best_rank }}名）</text>
          <text v-if="!search.safe.length" class="tg-empty">—</text>
        </view>
        <text class="small">该列表由 Python 后端按你的位次实时计算，是"观点→数据"打通的第一步。</text>
      </view>
      <text v-if="searchErr" class="err">{{ searchErr }}</text>
    </view>
  </view>
</template>

<script setup>
import { reactive, ref } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { QUESTIONS, MAJORS } from "@/utils/content.js";
import { buildCanvas } from "@/utils/engine.js";
import { api } from "@/utils/api.js";

const questions = QUESTIONS;
const form = reactive({});
const rankInput = ref("");
const canvas = ref(null);
const search = ref(null);
const searchErr = ref("");
const loading = ref(false);

QUESTIONS.forEach((q) => (form[q.id] = ""));

onLoad(() => {
  const saved = uni.getStorageSync("zhiyuan_profile_v2");
  if (saved) {
    Object.assign(form, saved);
    rankInput.value = saved._rank || "";
    canvas.value = buildCanvas(form, MAJORS);
  }
});

function onPick(id, e) {
  form[id] = questions.find((q) => q.id === id).options[e.detail.value];
}

function run() {
  uni.setStorageSync("zhiyuan_profile_v2", { ...form, _rank: rankInput.value });
  canvas.value = buildCanvas(form, MAJORS);
}

function clear() {
  QUESTIONS.forEach((q) => (form[q.id] = ""));
  rankInput.value = "";
  canvas.value = null;
  search.value = null;
  uni.removeStorageSync("zhiyuan_profile_v2");
}

async function enrich() {
  loading.value = true;
  searchErr.value = "";
  try {
    search.value = await api.search(form.province, form.subject, Number(rankInput.value));
  } catch (e) {
    searchErr.value = "后端未连接（请先启动 Python 后端 uvicorn main:app --port 8000）：" + (e.message || e);
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.page { padding: 24rpx 24rpx 60rpx; }
.hero { padding: 16rpx 8rpx 24rpx; }
.h1 { font-size: 40rpx; font-weight: 700; color: #ffd24d; }
.sub { display: block; margin-top: 10rpx; font-size: 24rpx; color: #8a909c; line-height: 1.6; }
.card { background: #16191f; border: 1px solid #23262e; border-radius: 20rpx; padding: 26rpx; margin-bottom: 24rpx; }
.h3 { font-size: 30rpx; font-weight: 600; color: #e6e8ec; display: block; margin-bottom: 18rpx; }
.field { margin-bottom: 20rpx; }
.fl { font-size: 26rpx; color: #c7ccd4; display: block; margin-bottom: 8rpx; }
.picker, .input { background: #0f1115; border: 1px solid #2a2e37; border-radius: 12rpx; padding: 18rpx 20rpx; font-size: 26rpx; color: #e6e8ec; }
.picker-text { font-size: 26rpx; color: #e6e8ec; }
.hint { display: block; font-size: 21rpx; color: #6b7280; margin-top: 6rpx; }
.row { display: flex; }
.gap { gap: 18rpx; }
.btn { flex: 1; background: #23262e; color: #e6e8ec; border-radius: 12rpx; font-size: 26rpx; padding: 18rpx 0; border: none; }
.btn.primary { background: #ffd24d; color: #1a1a1a; font-weight: 600; }
.btn[disabled] { opacity: 0.6; }
.tip { display: block; font-size: 21rpx; color: #6b7280; margin-top: 16rpx; line-height: 1.5; }
.cv-block { border-left: 4rpx solid #2a2e37; padding: 8rpx 0 8rpx 18rpx; margin-bottom: 18rpx; }
.cv-block.warn { border-left-color: #f0ad4e; }
.cv-k { font-size: 24rpx; color: #ffd24d; font-weight: 600; display: block; margin-bottom: 6rpx; }
.tags { display: flex; flex-wrap: wrap; gap: 12rpx; margin: 6rpx 0; }
.tagx { font-size: 22rpx; padding: 6rpx 16rpx; border-radius: 999rpx; background: #23262e; color: #c7ccd4; }
.tagx.good { background: #16361f; color: #5fd87f; }
.tagx.info { background: #1c2a3a; color: #6db3f2; }
.small { font-size: 21rpx; color: #6b7280; display: block; margin-top: 8rpx; }
.next { font-size: 24rpx; color: #c7ccd4; line-height: 1.8; }
.cv-foot { font-size: 21rpx; color: #f0ad4e; margin-top: 6rpx; }
.verify-box { margin-top: 16rpx; }
.dsrc { font-size: 21rpx; color: #6db3f2; display: block; margin-bottom: 10rpx; }
.tier-group { margin-bottom: 14rpx; }
.tg-title { font-size: 24rpx; color: #ffd24d; font-weight: 600; display: block; margin-bottom: 4rpx; }
.tg-item { font-size: 23rpx; color: #c7ccd4; display: block; line-height: 1.7; }
.tg-empty { font-size: 23rpx; color: #6b7280; }
.err { font-size: 22rpx; color: #ff6b6b; display: block; margin-top: 10rpx; line-height: 1.5; }
</style>
