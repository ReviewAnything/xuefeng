<template>
  <wd-config-provider :theme="$theme.mode" :theme-vars="themeVars" :custom-style="$theme.style">
    <view class="page">
      <view class="hero">
        <text class="h1">院校专业组</text>
        <text class="sub">新高考以「院校专业组」为志愿单元。选一所院校 + 你的选科，查看可报的专业组与专业。</text>
      </view>

      <view class="section">
        <view class="section-head"><text class="h3">你的选科</text></view>
        <wd-cell-group border>
          <wd-picker v-model="subject" label="选科方向" :columns="subjects" label-width="30%"></wd-picker>
        </wd-cell-group>
      </view>

      <view class="section">
        <view class="section-head">
          <text class="h3">选院校</text>
          <text class="bk-sub">教育部 2868 所</text>
        </view>
        <view class="search-row">
          <input class="search-input" v-model="q" placeholder="输入院校名，如 北京大学" @confirm="search" />
          <wd-button type="primary" size="small" :loading="loadingList" @click="search">搜索</wd-button>
        </view>
        <view v-if="candidates.length" class="cand-list">
          <view v-for="u in candidates" :key="u.name" class="cand" @click="pick(u)">
            <view class="cand-top">
              <text class="cand-name">{{ u.name }}</text>
              <wd-tag v-if="u.is_985" type="danger" plain>985</wd-tag>
              <wd-tag v-else-if="u.is_211" type="warning" plain>211</wd-tag>
            </view>
            <text class="cand-meta">{{ u.province }} · {{ u.category }}<text v-if="u.category_source !== 'official'">（推断）</text> · {{ u.level }}</text>
          </view>
        </view>
        <text v-if="err" class="err">{{ err }}</text>
      </view>

      <view v-if="result" class="section">
        <view class="uni-card">
          <view class="uni-top">
            <text class="uni-name">{{ result.university.name }}</text>
            <wd-tag type="warning" plain>规则估算</wd-tag>
          </view>
          <text class="uni-meta">{{ result.university.province }} · {{ result.university.category }} · {{ result.student_subject }}</text>
          <text class="uni-meta">共 {{ result.total_groups }} 个专业组，你可报 {{ result.eligible_groups }} 个</text>
        </view>

        <view v-for="g in result.groups" :key="g.group_code" class="grp" :class="{ off: !g.eligible }">
          <view class="grp-head">
            <text class="grp-name">{{ g.group_name }}</text>
            <wd-tag :type="g.eligible ? 'success' : 'info'" plain>{{ g.eligible ? "可报" : "不可报" }}</wd-tag>
          </view>
          <text class="grp-sub">{{ g.major_count }} 个专业 · 选科要求：{{ g.subject_req }}</text>
          <view class="majors">
            <text v-for="m in g.majors" :key="m.name" class="major-chip">{{ m.name }}</text>
          </view>
        </view>

        <view class="notes">
          <text v-for="(n, i) in result.notes" :key="i" class="note">· {{ n }}</text>
        </view>
      </view>
    </view>
    <wd-toast></wd-toast>
  </wd-config-provider>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { useToast } from "wot-design-uni";
import { api } from "@/utils/api";
import { themeVars } from "@/utils/theme";

const toast = useToast();

const subjects = ["物理类", "历史类", "综合/未改革"];
const subject = ref("物理类");
const q = ref("");
const candidates = ref<any[]>([]);
const result = ref(null);
const err = ref("");
const loadingList = ref(false);

onLoad(async (query) => {
  if (query && query.subject) subject.value = decodeURIComponent(query.subject);
  if (query && query.university) {
    q.value = decodeURIComponent(query.university);
    await pick({ name: q.value });
  }
});

async function search() {
  err.value = "";
  loadingList.value = true;
  try {
    const params = { limit: 20 };
    if (q.value.trim()) params.q = q.value.trim();
    const r = await api.majorGroupUniversities(params);
    candidates.value = r.items || [];
    if (!candidates.value.length) toast.show("没有匹配的院校，换个关键词试试");
  } catch (e: any) {
    err.value = (e && e.message) ? e.message : "数据服务未连接，可在「我的」开启演示模式先体验";
  } finally {
    loadingList.value = false;
  }
}

async function pick(u: any) {
  err.value = "";
  loadingList.value = true;
  try {
    result.value = await api.majorGroups(u.name, subject.value);
    candidates.value = [];
    q.value = u.name;
  } catch (e: any) {
    err.value = "查询失败：" + (e.message || e);
  } finally {
    loadingList.value = false;
  }
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
.small { font-size: 21rpx; color: #6b7280; display: block; margin-top: 10rpx; line-height: 1.6; }
.err { font-size: 22rpx; color: #ff6b6b; display: block; margin-top: 12rpx; line-height: 1.5; }

.search-row { display: flex; align-items: center; gap: 12rpx; }
.search-input {
  flex: 1; height: 72rpx; padding: 0 20rpx; border-radius: 12rpx;
  background: #1a1e26; border: 1px solid #2a2e37; color: #e6e8ec; font-size: 26rpx;
}

.cand-list { margin-top: 12rpx; border: 1px solid #22262e; border-radius: 14rpx; overflow: hidden; }
.cand { padding: 16rpx 20rpx; border-top: 1px solid #1c2027; }
.cand:first-child { border-top: none; }
.cand-top { display: flex; align-items: center; gap: 10rpx; }
.cand-name { font-size: 26rpx; color: #dfe3e9; font-weight: 500; }
.cand-meta { display: block; font-size: 20rpx; color: #6b7280; margin-top: 6rpx; }

.uni-card { border: 1px solid #2a2e37; border-radius: 16rpx; padding: 20rpx; margin-bottom: 18rpx; background: #14171d; }
.uni-top { display: flex; align-items: center; justify-content: space-between; }
.uni-name { font-size: 32rpx; font-weight: 700; color: #e6e8ec; }
.uni-meta { display: block; font-size: 22rpx; color: #8a909c; margin-top: 8rpx; line-height: 1.5; }

.grp { border: 1px solid #22262e; border-radius: 16rpx; padding: 20rpx; margin-bottom: 16rpx; }
.grp.off { opacity: 0.5; }
.grp-head { display: flex; align-items: center; justify-content: space-between; }
.grp-name { font-size: 27rpx; font-weight: 600; color: #e6e8ec; }
.grp-sub { display: block; font-size: 21rpx; color: #6b7280; margin-top: 6rpx; }
.majors { display: flex; flex-wrap: wrap; gap: 10rpx; margin-top: 14rpx; }
.major-chip {
  font-size: 21rpx; color: #c7ccd4; padding: 6rpx 14rpx;
  border: 1px solid #2a2e37; border-radius: 999rpx; background: #1a1e26;
}

.notes { margin-top: 16rpx; }
.note { display: block; font-size: 20rpx; color: #f0ad4e; line-height: 1.6; }
</style>
