<template>
  <wd-config-provider :theme="$theme.mode" :theme-vars="themeVars" :style="$theme.style">
    <view class="page">
      <view class="xf-hero">
        <view class="avatar">
          <app-icon name="user" color="#ffd24d" :size="44"></app-icon>
        </view>
        <view class="xf-hero-body">
          <text class="xf-h1">我的</text>
          <text class="xf-sub">填一次高考信息，全站自动带齐。演示模式下没后端也能走完整流程。</text>
        </view>
      </view>

      <!-- 我的档案：有档案先给摘要，要改再展开表单（默认收起，减少每次进页面的输入压力） -->
      <view class="xf-card profile-card">
        <view class="pf-head">
          <text class="xf-h3">我的高考信息</text>
          <view v-if="hasProfile && !editing" class="pf-edit" @click="editing = true">
            <app-icon name="refresh" color="#8f96a2" :size="24"></app-icon>
            <text class="pf-edit-t">修改</text>
          </view>
        </view>

        <view v-if="hasProfile && !editing" class="pf-summary">
          <view class="pf-main">
            <text class="pf-rank">{{ pf.rank }}</text>
            <text class="pf-rank-unit">名</text>
          </view>
          <text class="pf-cond">{{ pf.province }} · {{ pf.subject }}<text v-if="pf.major !== NO_MAJOR"> · {{ pf.major }}</text></text>
          <view class="pf-go" @click="goVerdict">
            <text class="pf-go-t">去看我能上哪</text>
            <app-icon name="chevron-right" color="#c9a53a" :size="24"></app-icon>
          </view>
        </view>

        <block v-else>
          <text class="xf-tiny">填一次常驻本机；「我能上哪 / 院校池 / 查专业 / 志愿表」都会自动带入。</text>
          <view class="pf-fields">
            <wd-picker v-model="pf.province" label="高考省份" :columns="provinces" placeholder="请选择" label-width="30%" />
            <wd-picker v-model="pf.subject" label="选科方向" :columns="subjects" placeholder="请选择" label-width="30%" />
            <wd-input v-model="pf.rank" label="高考位次" type="number" placeholder="如：40000" label-width="30%" />
            <wd-picker v-model="pf.major" label="目标专业" :columns="majorOptions" placeholder="请选择" label-width="30%" />
          </view>
          <view class="pf-actions">
            <wd-button type="primary" block :loading="saving" @click="saveProfile">保存我的信息</wd-button>
            <text v-if="hasProfile" class="pf-cancel" @click="cancelEdit">取消</text>
          </view>
        </block>
      </view>

      <!-- 演示模式 -->
      <view class="xf-card demo-card">
        <view class="demo-row">
          <view class="xf-tile xf-tile--reach">
            <app-icon name="sparkle" color="#f0ad4e" :size="30"></app-icon>
          </view>
          <view class="demo-body">
            <text class="xf-h3">演示模式</text>
            <text class="xf-tiny">开启后用内置样例数据，无需后端即可体验全部界面；关闭则连真实后端。</text>
          </view>
          <wd-switch v-model="demoOn" @change="onDemo" />
        </view>
        <view v-if="demoOn" class="demo-note">
          <app-icon name="info" color="#f0ad4e" :size="24"></app-icon>
          <text class="demo-note-t">当前为演示数据（示意值，非真实录取信息）。</text>
        </view>
      </view>

      <!-- 外观主题 -->
      <view class="xf-card theme-card">
        <view class="th-head">
          <view class="xf-tile">
            <app-icon name="theme" color="#c2c8d0" :size="30"></app-icon>
          </view>
          <view class="th-body">
            <text class="xf-h3">外观主题</text>
            <text class="xf-tiny">随时切换明暗与配色，选择会记住</text>
          </view>
        </view>
        <view class="th-grid">
          <view
            v-for="t in THEMES"
            :key="t.id"
            class="th-opt"
            :class="{ on: $theme.id === t.id }"
            @click="pick(t.id)"
          >
            <view class="th-swatch">
              <view class="th-bg" :style="{ background: t.swatch.bg }"></view>
              <view class="th-surface" :style="{ background: t.swatch.surface, borderColor: t.vars['--xf-line'] }"></view>
              <view class="th-dot" :style="{ background: t.swatch.accent }"></view>
            </view>
            <text class="th-name">{{ t.name }}</text>
          </view>
        </view>
      </view>

      <!-- 三步怎么用 -->
      <view class="xf-card steps-card">
        <text class="xf-h3">三步怎么用</text>
        <view class="steps">
          <view class="step">
            <view class="step-n">1</view>
            <view class="step-body">
              <text class="step-t">在「我能上哪」填位次</text>
              <text class="step-d">看自己落在哪一档、冲稳保怎么分</text>
            </view>
            <app-icon name="target" color="#6f7683" :size="26"></app-icon>
          </view>
          <view class="step">
            <view class="step-n">2</view>
            <view class="step-body">
              <text class="step-t">去「院校池」挑学校</text>
              <text class="step-d">每个层次有哪些院校、去年多少分</text>
            </view>
            <app-icon name="school" color="#6f7683" :size="26"></app-icon>
          </view>
          <view class="step">
            <view class="step-n">3</view>
            <view class="step-body">
              <text class="step-t">在「志愿表」排顺序</text>
              <text class="step-d">填拟报专业，打印或导出给家人看</text>
            </view>
            <app-icon name="list" color="#6f7683" :size="26"></app-icon>
          </view>
        </view>
      </view>

      <!-- 更多工具 -->
      <view class="sec">
        <text class="sec-title">更多工具</text>
        <view class="tool-list">
          <view class="xf-action" @click="goGraph">
            <view class="xf-tile">
              <app-icon name="graph" color="#c2c8d0" :size="30"></app-icon>
            </view>
            <view class="xf-action-label">
              <text class="xf-action-title">专业图谱</text>
              <text class="xf-action-desc">看专业的观点、就业与偏见校正</text>
            </view>
            <app-icon name="chevron-right" color="#6f7683" :size="26"></app-icon>
          </view>
          <view class="xf-action" @click="goDiagnose">
            <view class="xf-tile">
              <app-icon name="bulb" color="#c2c8d0" :size="30"></app-icon>
            </view>
            <view class="xf-action-label">
              <text class="xf-action-title">八连问 · 自我诊断</text>
              <text class="xf-action-desc">说不清想要什么？先回答几个问题</text>
            </view>
            <app-icon name="chevron-right" color="#6f7683" :size="26"></app-icon>
          </view>
          <view class="xf-action" @click="goCompass">
            <view class="xf-tile">
              <app-icon name="calendar" color="#c2c8d0" :size="30"></app-icon>
            </view>
            <view class="xf-action-label">
              <text class="xf-action-title">历年省控线</text>
              <text class="xf-action-desc">2022–2026 各省批次线及走势</text>
            </view>
            <app-icon name="chevron-right" color="#6f7683" :size="26"></app-icon>
          </view>
        </view>
      </view>

      <!-- 关于（默认折叠：需要时才展开，避免一屏几千字） -->
      <view class="sec">
        <text class="sec-title">关于这个工具</text>
        <view class="xf-card">
          <wd-collapse v-model="open">
            <wd-collapse-item title="这是什么" name="what">
              <text class="p">一个把「普通家庭 + 就业导向」的务实决策框架，与开源社区资源、真实录取数据结合的<text class="strong">懂分帝</text>。它输出决策框架而非录取结论，并内置偏见校正层。</text>
            </wd-collapse-item>
            <wd-collapse-item title="技术与数据规模" name="arch">
              <text class="p kv">前端 · uni-app (Vue3)，H5 / 小程序 / App</text>
              <text class="p kv">后端 · Python FastAPI</text>
              <text class="p kv">数据 · SQLite + SQLAlchemy</text>
              <text class="p kv">规模 · 2868 所院校 · {{ majorCount }} 专业 · {{ schoolCount }} 所入图谱</text>
              <text class="p kv">管理端 · {{ adminPath }}</text>
            </wd-collapse-item>
            <wd-collapse-item title="五个方向的落地方式" name="five">
              <text class="p kv">① 决策辅助而非答案：八连问 → 框架画布，不下定论。</text>
              <text class="p kv">② 定性 × 定量：图谱观点 → 后端按省/科类/位次返回门槛与冲稳保。</text>
              <text class="p kv">③ 偏见校正：每个专业带反方 / 长期 / 官方口径提示。</text>
              <text class="p kv">④ 本地隐私：问卷输入仅存端侧；后端只记录匿名查询事件。</text>
              <text class="p kv">⑤ 动态更新：内容与录取数据集中管理，管理端一键同步入库。</text>
            </wd-collapse-item>
            <wd-collapse-item title="内容可溯" name="src">
              <text class="p kv">观点依据 · {{ src.view_basis }}</text>
              <text class="p kv">数据依据 · {{ src.data_basis }}</text>
              <text class="p kv">整理年份 · {{ src.compiled_year }} 年（{{ src.compiled_date }}）</text>
              <text class="p small">{{ src.caveat }}</text>
            </wd-collapse-item>
          </wd-collapse>
        </view>
      </view>

      <!-- 开源资源 -->
      <view class="sec">
        <text class="sec-title">开源资源</text>
        <scroll-view class="filters" scroll-x="true">
          <view class="chips">
            <view v-for="r in resCats" :key="r.key" class="chip" :class="{ on: cur === r.key }" @click="cur = r.key">{{ r.label }}</view>
          </view>
        </scroll-view>
        <view class="grid">
          <view v-for="item in list" :key="item.name" class="xf-card res">
            <view class="res-top">
              <text class="res-name">{{ item.name }}</text>
              <text class="res-lic">{{ item.lic }}</text>
            </view>
            <text class="res-meta">{{ item.meta }}</text>
            <text class="res-desc">{{ item.desc }}</text>
            <view class="res-acts">
              <view v-for="l in item.links" :key="l.u" class="res-link" @click="openLink(l.u)">
                <text class="res-link-t">{{ l.t }}</text>
                <app-icon name="external" :color="l.t.indexOf('GitHub') >= 0 ? '#6db3f2' : '#8f96a2'" :size="22"></app-icon>
              </view>
            </view>
          </view>
        </view>
      </view>

      <!-- 免责 -->
      <view class="xf-card disclaimer">
        <view class="dis-head">
          <app-icon name="shield" color="#f0ad4e" :size="28"></app-icon>
          <text class="dis-title">免责声明</text>
        </view>
        <text class="p">本应用由 AI 基于公开资料与开源社区内容整理，<text class="strong">仅供学习参考，不构成正式升学 / 志愿填报建议</text>。实际填报请以各省教育考试院官方数据为准。</text>
        <text class="p small">录取基线中 31 省为官方省控线（2022–2026），院校级投档线为真实抓取（非官方），其余为模型推算，已在接口逐条标注来源。</text>
      </view>

      <text class="ver">v{{ version }} · 数据 {{ date }}</text>
    </view>
    <wd-toast />
  </wd-config-provider>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import { onShow } from "@dcloudio/uni-app";
import { useToast } from "wot-design-uni";
import { APP_VERSION, DATA_DATE, CONTENT_SOURCE, RESOURCES, RES_CATS, MAJORS, SCHOOLS, ensureContent } from "@/utils/content";
import { themeVars, THEMES, setTheme } from "@/utils/theme";
import { api } from "@/utils/api";
import { PROFILE_OPTIONS, getProfile, setProfile } from "@/utils/profile";

const version = ref("");
const date = ref("");
const majorCount = ref(0);
const schoolCount = ref(0);
const open = ref("");
const src = ref<Record<string, any>>({});

const toast = useToast();
const provinces = PROFILE_OPTIONS.provinces;
const subjects = PROFILE_OPTIONS.subjects;
const NO_MAJOR = "不限（用省份基线）";
const majorOptions = ref<any[]>([]);

const pf = ref({ province: "", subject: "", rank: "", major: NO_MAJOR });
const saving = ref(false);
const demoOn = ref(false);
const editing = ref(false);

const hasProfile = computed(() => !!(pf.value.province && pf.value.subject && pf.value.rank));

// 管理端入口：H5 与后端同源时是 /admin，小程序端只能提示拼地址
const adminPath = "/admin（后端服务地址后）";

// 进入本页即同步全局档案与演示开关，保证「我的」始终反映当前状态
onShow(async () => {
  await ensureContent();
  const p = getProfile();
  pf.value = {
    province: p.province || "",
    subject: p.subject || "",
    rank: p.rank || "",
    major: p.major || NO_MAJOR,
  };
  demoOn.value = api.isDemo();
  // 已有档案就默认收起表单（进页面先看摘要，不先看输入框）
  editing.value = !(p.province && p.subject && p.rank);
  // 内容数据按需懒加载，onShow 里拿到后再填充（分包瘦身：避免主包打进 234KB JSON）
  version.value = APP_VERSION;
  date.value = DATA_DATE;
  majorCount.value = MAJORS.length;
  schoolCount.value = SCHOOLS.length;
  src.value = CONTENT_SOURCE;
  majorOptions.value = [NO_MAJOR].concat(MAJORS.map((m) => m.name));
  resources.value = RESOURCES;
});

function cancelEdit() {
  const p = getProfile();
  pf.value = {
    province: p.province || "",
    subject: p.subject || "",
    rank: p.rank || "",
    major: p.major || NO_MAJOR,
  };
  editing.value = false;
}

function saveProfile() {
  if (!pf.value.province || !pf.value.subject || !pf.value.rank) {
    toast.show("省份 / 科类 / 位次都要填");
    return;
  }
  if (!(Number(pf.value.rank) > 0)) {
    toast.show("位次填正整数");
    return;
  }
  saving.value = true;
  try {
    setProfile({
      province: pf.value.province,
      subject: pf.value.subject,
      rank: pf.value.rank,
      major: pf.value.major === NO_MAJOR ? "" : pf.value.major,
    });
    editing.value = false;
    toast.show("已保存，去「我能上哪」看看吧");
  } finally {
    saving.value = false;
  }
}

function onDemo() {
  // v-model 已先更新 demoOn，这里直接读当前值最稳（不同版本 change 参数形态不一致）
  const on = !!demoOn.value;
  api.setDemo(on);
  toast.show(on ? "已开启演示模式（内置样例数据）" : "已关闭演示模式（连接真实后端）");
}

function pick(id: any) {
  setTheme(id);
  const t = THEMES.find((x) => x.id === id);
  toast.show("已切换至「" + (t ? t.name : id) + "」");
}

/* 开源资源（原「资源」tab 已并入本页） */
const resCats = RES_CATS;
const cur = ref("all");
const resources = ref<any[]>([]);
const list = computed(() => resources.value.filter((r) => cur.value === "all" || r.cat === cur.value));

function goVerdict() {
  uni.switchTab({ url: "/pages/verdict/verdict" });
}
// 非 tab 页：专业图谱 / 八连问 / 历年省控线用 navigateTo
function goGraph() {
  uni.navigateTo({ url: "/subpackages/graph/graph" });
}
function goDiagnose() {
  uni.navigateTo({ url: "/subpackages/diagnose/diagnose" });
}
function goCompass() {
  uni.navigateTo({ url: "/subpackages/compass/compass" });
}
function openLink(u: any) {
  // #ifdef H5
  window.open(u, "_blank");
  // #endif
  // #ifndef H5
  uni.setClipboardData({ data: u, success: () => toast.show("链接已复制，请在浏览器打开") });
  // #endif
}
</script>

<style scoped>
.page { padding: 24rpx 24rpx 80rpx; min-height: 100vh; background: var(--xf-bg); }

.avatar {
  flex: 0 0 auto; width: 88rpx; height: 88rpx; border-radius: 28rpx;
  display: flex; align-items: center; justify-content: center;
  background: rgba(255, 210, 77, 0.12); border: 1rpx solid rgba(255, 210, 77, 0.3);
}

/* 档案卡 */
.profile-card { margin-top: 6rpx; }
.pf-head { display: flex; align-items: center; justify-content: space-between; }
.pf-edit { display: flex; align-items: center; gap: 6rpx; min-height: 64rpx; padding-left: 12rpx; }
.pf-edit-t { font-size: 21rpx; color: var(--xf-text-3); }
.pf-summary { margin-top: 10rpx; }
.pf-main { display: flex; align-items: baseline; gap: 6rpx; }
.pf-rank { font-size: 56rpx; font-weight: 700; color: var(--xf-gold); line-height: 1.1; font-variant-numeric: tabular-nums; }
.pf-rank-unit { font-size: 22rpx; color: var(--xf-text-3); }
.pf-cond { display: block; margin-top: 4rpx; font-size: 23rpx; color: var(--xf-text-3); }
.pf-go {
  display: flex; align-items: center; justify-content: space-between;
  margin-top: 18rpx; padding: 0 18rpx; min-height: 84rpx;
  border-radius: var(--xf-r-md);
  background: linear-gradient(135deg, rgba(255, 210, 77, 0.14), rgba(255, 210, 77, 0.03));
  border: 1rpx solid rgba(255, 210, 77, 0.34);
}
.pf-go-t { font-size: 25rpx; font-weight: 600; color: var(--xf-gold); }
.pf-fields { margin: 14rpx 0 18rpx; border: 1rpx solid var(--xf-line); border-radius: var(--xf-r-sm); overflow: hidden; }
.pf-actions { display: flex; flex-direction: column; gap: 10rpx; }
.pf-cancel { display: block; text-align: center; padding: 16rpx 0; font-size: 23rpx; color: var(--xf-text-3); }

/* 演示模式 */
.demo-card { margin-top: 18rpx; }
.demo-row { display: flex; align-items: flex-start; gap: 14rpx; }
.demo-body { flex: 1; min-width: 0; }
.demo-note { display: flex; align-items: center; gap: 8rpx; margin-top: 14rpx; padding: 12rpx 14rpx; border-radius: var(--xf-r-sm); background: rgba(240, 173, 78, 0.08); border: 1rpx solid rgba(240, 173, 78, 0.28); }
.demo-note-t { flex: 1; font-size: 20rpx; color: var(--xf-demo); line-height: 1.5; }

/* 三步 */
.steps-card { margin-top: 18rpx; }
.steps { margin-top: 8rpx; }
.step { display: flex; align-items: center; gap: 14rpx; padding: 14rpx 0; border-top: 1rpx solid var(--xf-line-soft); }
.step:first-child { border-top: none; }
.step-n {
  flex: 0 0 auto; width: 44rpx; height: 44rpx; border-radius: 50%;
  background: rgba(255, 210, 77, 0.14); color: var(--xf-gold);
  font-size: 22rpx; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
}
.step-body { flex: 1; min-width: 0; }
.step-t { display: block; font-size: 24rpx; color: var(--xf-text-2); }
.step-d { display: block; margin-top: 3rpx; font-size: 20rpx; color: var(--xf-text-4); }

/* 分区 */
.sec { margin-top: 30rpx; }
.sec-title { display: block; font-size: 22rpx; color: var(--xf-text-4); margin-bottom: 12rpx; letter-spacing: 1rpx; }
.tool-list { display: flex; flex-direction: column; gap: 12rpx; }

.p { display: block; font-size: 23rpx; color: var(--xf-text-2); line-height: 1.75; }
.p.kv { margin-bottom: 8rpx; }
.p.small { margin-top: 8rpx; font-size: 20rpx; color: var(--xf-text-4); line-height: 1.7; }
.strong { color: var(--xf-gold); font-weight: 600; }

/* 资源 */
.filters { white-space: nowrap; margin-bottom: 12rpx; }
.chips { display: inline-flex; gap: 12rpx; padding: 2rpx 2rpx 8rpx; }
.chip { padding: 12rpx 24rpx; border-radius: 999rpx; font-size: 22rpx; background: var(--xf-surface); border: 1rpx solid var(--xf-line); color: var(--xf-text-3); }
.chip.on { background: rgba(255, 210, 77, 0.12); border-color: rgba(255, 210, 77, 0.42); color: var(--xf-gold); font-weight: 600; }
.grid { display: flex; flex-direction: column; gap: 16rpx; }
.res-top { display: flex; align-items: center; justify-content: space-between; gap: 12rpx; }
.res-name { font-size: 26rpx; font-weight: 600; color: var(--xf-text); }
.res-lic { font-size: 19rpx; color: var(--xf-text-4); border: 1rpx solid var(--xf-line); border-radius: 6rpx; padding: 2rpx 8rpx; }
.res-meta { display: block; margin-top: 8rpx; font-size: 20rpx; color: var(--xf-text-4); }
.res-desc { display: block; margin: 10rpx 0 14rpx; font-size: 22rpx; color: var(--xf-text-3); line-height: 1.7; }
.res-acts { display: flex; flex-wrap: wrap; gap: 10rpx; }
.res-link { display: flex; align-items: center; gap: 6rpx; padding: 10rpx 18rpx; min-height: 64rpx; border-radius: 999rpx; border: 1rpx solid var(--xf-line); background: rgba(255, 255, 255, 0.03); }
.res-link-t { font-size: 21rpx; color: var(--xf-real); }

/* 免责 */
.disclaimer { margin-top: 30rpx; border-color: rgba(240, 173, 78, 0.3); background: rgba(240, 173, 78, 0.05); }
.dis-head { display: flex; align-items: center; gap: 10rpx; margin-bottom: 8rpx; }
.dis-title { font-size: 24rpx; font-weight: 600; color: var(--xf-demo); }

/* 外观主题 */
.theme-card { margin-top: 18rpx; }
.th-head { display: flex; align-items: center; gap: 14rpx; margin-bottom: 16rpx; }
.th-body { flex: 1; min-width: 0; }
.th-grid { display: flex; gap: 14rpx; }
.th-opt {
  flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: center; gap: 10rpx;
  padding: 14rpx 8rpx; border-radius: var(--xf-r-md);
  border: 1rpx solid var(--xf-line); background: var(--xf-fill);
  transition: border-color var(--xf-ease) 140ms;
}
.th-opt.on { border-color: var(--xf-gold); background: rgba(255, 210, 77, 0.06); }
.th-swatch { position: relative; width: 100%; height: 84rpx; border-radius: 12rpx; overflow: hidden; display: flex; border: 1rpx solid var(--xf-line); }
.th-bg { flex: 1; }
.th-surface { flex: 1; border-left: 1rpx solid; }
.th-dot { position: absolute; right: 10rpx; bottom: 10rpx; width: 22rpx; height: 22rpx; border-radius: 50%; box-shadow: 0 1rpx 4rpx rgba(0, 0, 0, 0.3); }
.th-name { font-size: 21rpx; color: var(--xf-text-2); }
.th-opt.on .th-name { color: var(--xf-gold); font-weight: 600; }

.ver { display: block; margin-top: 26rpx; text-align: center; font-size: 19rpx; color: var(--xf-text-4); }
</style>
