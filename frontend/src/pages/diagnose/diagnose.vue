<template>
  <wd-config-provider :theme="$theme.mode" :theme-vars="themeVars" :style="$theme.style">
    <view class="page">
      <view class="hero">
        <text class="h1">自我诊断画布</text>
        <text class="sub">灵魂八连问 → 输出决策框架，不是录取结论。所有输入仅存于本机。</text>
      </view>

      <view class="section">
        <view class="section-head">
          <text class="h3">① 填写你的现实条件</text>
          <text class="badge">仅本机存储</text>
        </view>

        <wd-cell-group border>
          <template v-for="q in questions" :key="q.id">
            <wd-picker v-if="q.type === 'select'" v-model="form[q.id]" :label="q.label"
                       :columns="q.options" placeholder="请选择" label-width="46%" />
            <wd-input v-else v-model="form[q.id]" :label="q.label"
                      :placeholder="q.placeholder" label-width="30%" />
            <view class="hint-row">{{ q.hint }}</view>
          </template>
          <wd-input v-model="rankInput" label="高考位次" type="number"
                    placeholder="如：40000" label-width="30%" />
        </wd-cell-group>

        <text class="tip">填了位次，可一键拉取后端按位次筛出的 冲/稳/保 可达专业；位次仅用于本次计算。</text>

        <view class="actions">
          <wd-button type="primary" block size="large" @click="run">生成决策画布</wd-button>
          <wd-button plain block @click="clear">清空</wd-button>
        </view>
        <text class="tip muted">本工具体现「就业确定性优先（普通家庭+就业导向）」视角，并已加入偏见校正层，请结合自身判断。</text>
      </view>

      <view class="section" v-if="canvas">
        <view class="section-head">
          <text class="h3">② 决策画布</text>
          <wd-tag type="success" plain>框架 · 非定论</wd-tag>
        </view>

        <view class="cv-block">
          <text class="cv-k">首要策略</text>
          <rich-text :nodes="canvas.strategy"></rich-text>
        </view>
        <view class="cv-block">
          <text class="cv-k">推荐方向（框架，非定论）</text>
          <view class="tags">
            <wd-tag v-for="p in canvas.picks" :key="p.name"
                    :type="p.view === 'recommend' ? 'success' : 'primary'" plain
                    @click="goVerify(p.name)">{{ p.name }}</wd-tag>
          </view>
          <view class="pick-actions">
            <wd-button size="small" type="primary" plain @click="goVerifyBatch">批量核验全部 {{ canvas.picks.length }} 个方向</wd-button>
          </view>
          <text class="small">点击任一专业可单独带入「核验」页；点上方按钮可把全部推荐方向一次性批量核验（需先填省份/科类/位次）。</text>
        </view>
        <view class="cv-block warn">
          <text class="cv-k">偏见校正</text>
          <rich-text :nodes="canvas.biasWarn"></rich-text>
        </view>
        <view class="cv-block">
          <text class="cv-k">重点避坑</text>
          <text class="cv-t">同条件下建议谨慎：{{ canvas.avoidHint.join("、") }} 等（详见专业图谱与开源资源核验）。</text>
        </view>
        <view class="cv-block">
          <text class="cv-k">下一步动作</text>
          <view v-for="(n, i) in canvas.next" :key="i" class="next">· {{ n }}</view>
        </view>
        <view class="cv-foot">⚠️ 这是决策框架，不是录取结论。请以各省考试院官方数据为准。</view>
      </view>

      <view class="section" v-if="form.province && form.subject && rankInput">
        <view class="section-head">
          <text class="h3">③ 数据侧：按位次拉取可达专业</text>
          <wd-tag type="primary" plain>Python 后端</wd-tag>
        </view>
        <wd-button type="primary" plain block :loading="loading" @click="enrich">
          {{ loading ? "核验中…" : "调用后端核验可达专业" }}
        </wd-button>

        <view v-if="search" class="verify-box">
          <text class="dsrc">数据源：{{ search.data_source === "official_overlay" ? "31 省官方省控线 + 其余估算" : (search.data_source === "real" ? "真实录取记录（估算）" : "参数化样例（演示）") }}</text>
          <view class="tier-group" v-for="g in groups" :key="g.key">
            <text class="tg-title" :class="g.key">{{ g.title }}</text>
            <view class="tg-items">
              <wd-tag v-for="m in search[g.key]" :key="m.major" type="default" plain>
                {{ m.major }} · {{ m.best_tier }} · 约{{ m.best_rank }}名
              </wd-tag>
              <text v-if="!search[g.key].length" class="tg-empty">—</text>
            </view>
          </view>
          <text class="small">该列表由后端按你的位次实时计算，是"观点→数据"打通的第一步。</text>
        </view>
        <text v-if="searchErr" class="err">{{ searchErr }}</text>
        <view class="actions">
          <wd-button plain block @click="goRecommend">查看院校推荐（冲/稳/保 院校池）</wd-button>
          <wd-button plain block @click="goGroups">院校专业组（新高考选科）</wd-button>
        </view>
      </view>
    </view>
    <wd-toast />
  </wd-config-provider>
</template>

<script setup>
import { reactive, ref } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { useToast } from "wot-design-uni";
import { QUESTIONS, MAJORS } from "@/utils/content.js";
import { buildCanvas } from "@/utils/engine.js";
import { api } from "@/utils/api.js";
import { themeVars } from "@/utils/theme.js";
import { getProfile, setProfile } from "@/utils/profile.js";

const toast = useToast();
const questions = QUESTIONS;
const form = reactive({});
const rankInput = ref("");
const canvas = ref(null);
const search = ref(null);
const searchErr = ref("");
const loading = ref(false);

const groups = [
  { key: "reach", title: "冲（够一够）" },
  { key: "match", title: "稳（大概率）" },
  { key: "safe", title: "保（兜底）" },
];

QUESTIONS.forEach((q) => (form[q.id] = ""));

onLoad(() => {
  const saved = uni.getStorageSync("zhiyuan_profile_v2") || {};
  Object.assign(form, saved);
  rankInput.value = saved._rank || "";
  // 从全局档案带入省份/科类/位次：用户在「我的」页只填一次，
  // 八连问不再要求重复填写（自身 zhiyuan_profile_v2 已有时以自身为准）。
  const gp = getProfile();
  if (gp.province && !form.province) form.province = gp.province;
  if (gp.subject && !form.subject) form.subject = gp.subject;
  if (gp.rank && !rankInput.value) rankInput.value = gp.rank;
  if (form.province && form.subject && rankInput.value) {
    canvas.value = buildCanvas(form, MAJORS);
  }
});

function run() {
  uni.setStorageSync("zhiyuan_profile_v2", { ...form, _rank: rankInput.value });
  // 同步省份/科类/位次回全局档案，保证「我的 / 我能上哪 / 院校池」等页共享同一份条件
  setProfile({ province: form.province, subject: form.subject, rank: rankInput.value, major: "" });
  canvas.value = buildCanvas(form, MAJORS);
  toast.show("已生成决策画布");
}

function clear() {
  QUESTIONS.forEach((q) => (form[q.id] = ""));
  rankInput.value = "";
  canvas.value = null;
  search.value = null;
  uni.removeStorageSync("zhiyuan_profile_v2");
  toast.show("已清空");
}

// 条件齐备性检查：省份/科类/位次是数据侧计算的必需输入
function requireConditions() {
  if (!form.province || !form.subject || !rankInput.value) {
    toast.show("请先填写省份 / 科类 / 位次");
    return false;
  }
  return true;
}

// 把「画布推荐方向」落盘，供核验页读取（P1→P2 打通的桥梁，仍仅存本机）
function persistPicks() {
  uni.setStorageSync("zhiyuan_canvas_v2", {
    province: form.province,
    subject: form.subject,
    user_rank: rankInput.value,
    picks: (canvas.value && canvas.value.picks ? canvas.value.picks : []).map((x) => x.name),
    at: Date.now(),
  });
}

// 一键把诊断画布里的专业带入「查专业」页（观点×数据交叉核验）
// 条件写入全局档案；「查专业」是 tab 页，用 switchTab 跳转，专业名经 profile.major 带入。
function goVerify(name) {
  if (!requireConditions()) return;
  persistPicks();
  setProfile({ province: form.province, subject: form.subject, rank: rankInput.value, major: name });
  try { uni.removeStorageSync("zhiyuan_pending_batch"); } catch (e) {}
  uni.switchTab({ url: "/pages/verify/verify" });
}

// 批量：把画布全部推荐方向带入核验页，一次算完 一致/需谨慎/冲突
function goVerifyBatch() {
  if (!requireConditions()) return;
  if (!canvas.value || !canvas.value.picks || !canvas.value.picks.length) {
    toast.show("画布暂无推荐方向");
    return;
  }
  persistPicks();
  setProfile({ province: form.province, subject: form.subject, rank: rankInput.value, major: "" });
  // 批量标记存端侧，由「查专业」页 onShow 读取并自动开跑
  try { uni.setStorageSync("zhiyuan_pending_batch", 1); } catch (e) {}
  uni.switchTab({ url: "/pages/verify/verify" });
}

// 带着省份/科类/位次进入「院校池」页，看 冲/稳/保 三个档位的院校池
function goRecommend() {
  if (!requireConditions()) return;
  setProfile({ province: form.province, subject: form.subject, rank: rankInput.value, major: "" });
  uni.switchTab({ url: "/pages/recommend/recommend" });
}

// 进入「院校专业组」页，按当前选科查看专业组结构
function goGroups() {
  const q = form.subject ? `?subject=${encodeURIComponent(form.subject)}` : "";
  uni.navigateTo({ url: `/pages/majorGroup/majorGroup${q}` });
}

async function enrich() {
  loading.value = true;
  searchErr.value = "";
  try {
    search.value = await api.search(form.province, form.subject, Number(rankInput.value));
  } catch (e) {
    searchErr.value = (e && e.message) ? e.message : "数据服务未连接，可在「我的」开启演示模式先体验";
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

.section { margin-bottom: 24rpx; }
.section-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14rpx; }
.h3 { font-size: 30rpx; font-weight: 600; color: #e6e8ec; }
.badge { font-size: 20rpx; color: #6b7280; border: 1px solid #2a2e37; border-radius: 999rpx; padding: 2rpx 12rpx; }

.hint-row { padding: 0 16rpx 14rpx; font-size: 20rpx; color: #6b7280; line-height: 1.5; }
.tip { display: block; font-size: 21rpx; color: #6b7280; margin-top: 14rpx; line-height: 1.6; }
.tip.muted { margin-top: 10rpx; }
.actions { display: flex; flex-direction: column; gap: 16rpx; margin-top: 18rpx; }

.cv-block { border-left: 4rpx solid #2a2e37; padding: 8rpx 0 8rpx 18rpx; margin-bottom: 18rpx; }
.cv-block.warn { border-left-color: #f0ad4e; }
.cv-k { font-size: 24rpx; color: #ffd24d; font-weight: 600; display: block; margin-bottom: 6rpx; }
.cv-t { font-size: 24rpx; color: #c7ccd4; line-height: 1.6; }
.tags { display: flex; flex-wrap: wrap; gap: 12rpx; margin: 6rpx 0; }
.pick-actions { margin: 14rpx 0 2rpx; }
.small { font-size: 21rpx; color: #6b7280; display: block; margin-top: 10rpx; line-height: 1.6; }
.next { font-size: 24rpx; color: #c7ccd4; line-height: 1.8; }
.cv-foot { font-size: 21rpx; color: #f0ad4e; margin-top: 6rpx; }

.verify-box { margin-top: 18rpx; }
.dsrc { font-size: 21rpx; color: #6db3f2; display: block; margin-bottom: 12rpx; }
.tier-group { margin-bottom: 16rpx; }
.tg-title { font-size: 24rpx; font-weight: 600; display: block; margin-bottom: 8rpx; }
.tg-title.reach { color: #f0ad4e; }
.tg-title.match { color: #6db3f2; }
.tg-title.safe { color: #5fd87f; }
.tg-items { display: flex; flex-wrap: wrap; gap: 10rpx; }
.tg-empty { font-size: 23rpx; color: #6b7280; }
.err { font-size: 22rpx; color: #ff6b6b; display: block; margin-top: 12rpx; line-height: 1.5; }
</style>
