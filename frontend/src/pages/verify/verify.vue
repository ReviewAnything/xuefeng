<template>
  <view class="page">
    <view class="hero">
      <text class="h1">观点 × 数据 交叉核验</text>
      <text class="sub">P2 核心：把张雪峰定性观点与后端定量录取数据做一致性校验，强化偏见校正。</text>
    </view>

    <view class="card">
      <view class="field">
        <text class="fl">高考省份</text>
        <picker class="picker" mode="selector" :range="provinces" @change="p.province = provinces[$event.detail.value]">
          <view class="picker-text">{{ p.province || '请选择' }}</view>
        </picker>
      </view>
      <view class="field">
        <text class="fl">选科方向</text>
        <picker class="picker" mode="selector" :range="subjects" @change="p.subject = subjects[$event.detail.value]">
          <view class="picker-text">{{ p.subject || '请选择' }}</view>
        </picker>
      </view>
      <view class="field">
        <text class="fl">高考位次</text>
        <input class="input" v-model="p.user_rank" type="number" placeholder="如：40000" />
      </view>
      <view class="field">
        <text class="fl">目标专业</text>
        <picker class="picker" mode="selector" :range="majorNames" @change="p.major_name = majorNames[$event.detail.value]">
          <view class="picker-text">{{ p.major_name || '请选择' }}</view>
        </picker>
      </view>
      <button class="btn primary" :disabled="loading" @click="run">开始交叉核验</button>
      <text v-if="err" class="err">{{ err }}</text>
    </view>

    <view class="card" v-if="res">
      <view class="head">
        <text class="mname">{{ res.major }}</text>
        <text class="vbadge" :class="res.view">{{ res.view_label }}</text>
      </view>
      <view class="align" :class="res.alignment">
        <text class="align-label">{{ res.alignment_label }}</text>
      </view>

      <view class="block">
        <text class="bk">张雪峰视角</text>
        <text class="bt">{{ res.reason }}</text>
      </view>
      <view class="block">
        <text class="bk">⚖ 偏见校正</text>
        <text class="bt">{{ res.bias }}</text>
      </view>

      <view class="block">
        <text class="bk">各批次录取门槛（{{ res.province }} · {{ res.subject }}）</text>
        <view class="tier" v-for="t in res.tiers" :key="t.tier" :class="{ best: res.best_reachable && res.best_reachable.tier === t.tier }">
          <text class="tt">{{ t.tier }}</text>
          <text class="ts">≈{{ t.min_score }}分 / 位次{{ t.min_rank }}</text>
          <text class="tl" :class="t.level">{{ t.level }}</text>
        </view>
        <text class="dsrc">数据源：{{ res.data_source === 'real' ? '真实录取记录' : '参数化样例（演示）' }}</text>
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
</template>

<script setup>
import { reactive, ref } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { MAJORS } from "@/utils/content.js";
import { api } from "@/utils/api.js";

// 全国 31 省（与 admission_real_baseline.json 覆盖一致）
const provinces = ["北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆"];
const subjects = ["物理类", "历史类", "综合/未改革"];
const majorNames = MAJORS.map((m) => m.name);

const p = reactive({ province: "", subject: "", user_rank: "", major_name: "" });
const res = ref(null);
const err = ref("");
const loading = ref(false);

// 支持从「诊断画布」一键带入（省份/科类/位次/专业）
onLoad((q) => {
  if (q) {
    if (q.province) p.province = q.province;
    if (q.subject) p.subject = q.subject;
    if (q.user_rank) p.user_rank = q.user_rank;
    if (q.major_name) p.major_name = q.major_name;
  }
});

async function run() {
  if (!p.province || !p.subject || !p.user_rank || !p.major_name) {
    err.value = "请完整填写省份 / 科类 / 位次 / 专业";
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
.hero { padding: 16rpx 8rpx 18rpx; }
.h1 { font-size: 40rpx; font-weight: 700; color: #ffd24d; }
.sub { display: block; margin-top: 10rpx; font-size: 24rpx; color: #8a909c; line-height: 1.6; }
.card { background: #16191f; border: 1px solid #23262e; border-radius: 20rpx; padding: 26rpx; margin-bottom: 24rpx; }
.field { margin-bottom: 18rpx; }
.fl { font-size: 26rpx; color: #c7ccd4; display: block; margin-bottom: 8rpx; }
.picker, .input { background: #0f1115; border: 1px solid #2a2e37; border-radius: 12rpx; padding: 18rpx 20rpx; font-size: 26rpx; color: #e6e8ec; }
.picker-text { font-size: 26rpx; color: #e6e8ec; }
.btn { background: #23262e; color: #e6e8ec; border-radius: 12rpx; font-size: 28rpx; padding: 20rpx 0; border: none; }
.btn.primary { background: #ffd24d; color: #1a1a1a; font-weight: 600; }
.btn[disabled] { opacity: 0.6; }
.err { display: block; font-size: 22rpx; color: #ff6b6b; margin-top: 12rpx; }
.head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14rpx; }
.mname { font-size: 32rpx; font-weight: 700; color: #e6e8ec; }
.vbadge { font-size: 22rpx; padding: 4rpx 14rpx; border-radius: 999rpx; }
.vbadge.recommend { background: #16361f; color: #5fd87f; }
.vbadge.caution { background: #3a2f12; color: #f0ad4e; }
.vbadge.avoid { background: #3a1a1a; color: #ff6b6b; }
.align { border-radius: 12rpx; padding: 14rpx; text-align: center; margin-bottom: 16rpx; }
.align-label { font-size: 28rpx; font-weight: 700; }
.align.aligned { background: #16361f; }
.align.aligned .align-label { color: #5fd87f; }
.align.caution { background: #3a2f12; }
.align.caution .align-label { color: #f0ad4e; }
.align.conflict { background: #3a1a1a; }
.align.conflict .align-label { color: #ff6b6b; }
.block { margin-bottom: 16rpx; }
.bk { font-size: 24rpx; color: #ffd24d; font-weight: 600; display: block; margin-bottom: 6rpx; }
.bt { font-size: 24rpx; color: #c7ccd4; line-height: 1.6; }
.tier { display: flex; align-items: center; justify-content: space-between; background: #0f1115; border: 1px solid #23262e; border-radius: 10rpx; padding: 12rpx 16rpx; margin-bottom: 8rpx; }
.tier.best { border-color: #ffd24d; }
.tt { font-size: 24rpx; color: #e6e8ec; }
.ts { font-size: 22rpx; color: #8a909c; flex: 1; margin-left: 12rpx; }
.tl { font-size: 22rpx; padding: 2rpx 12rpx; border-radius: 999rpx; }
.tl.保 { background: #16361f; color: #5fd87f; }
.tl.稳 { background: #1c2a3a; color: #6db3f2; }
.tl.冲 { background: #3a2f12; color: #f0ad4e; }
.tl.不可及 { background: #23262e; color: #6b7280; }
.dsrc { font-size: 21rpx; color: #6db3f2; display: block; margin-top: 6rpx; }
.msg { background: #1c1f26; border-radius: 12rpx; padding: 16rpx; }
.sg { font-size: 23rpx; color: #c7ccd4; line-height: 1.8; }
</style>
