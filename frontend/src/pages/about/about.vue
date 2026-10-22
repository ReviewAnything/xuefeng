<template>
  <wd-config-provider theme="dark" :theme-vars="themeVars">
    <view class="page">
      <view class="hero">
        <text class="h1">我的</text>
        <text class="sub">一次填好高考信息，所有页面自动带齐；演示模式让你没后端也能体验完整流程。</text>
      </view>

      <!-- 高考信息：全局档案 -->
      <view class="section">
        <text class="h3">我的高考信息</text>
        <text class="p small">填一次，常驻本机。打开「我能上哪 / 院校池 / 查专业」会自动带上，不用重复输入。</text>
        <wd-cell-group border>
          <wd-picker v-model="pf.province" label="高考省份" :columns="provinces" placeholder="请选择" label-width="30%" />
          <wd-picker v-model="pf.subject" label="选科方向" :columns="subjects" placeholder="请选择" label-width="30%" />
          <wd-input v-model="pf.rank" label="高考位次" type="number" placeholder="如：40000" label-width="30%" />
          <wd-picker v-model="pf.major" label="目标专业" :columns="majorOptions" placeholder="请选择" label-width="30%" />
        </wd-cell-group>
        <view class="actions">
          <wd-button type="primary" block :loading="saving" @click="saveProfile">保存我的信息</wd-button>
        </view>
      </view>

      <!-- 演示模式 -->
      <view class="section">
        <view class="switch-row">
          <view class="switch-text">
            <text class="h3">演示模式</text>
            <text class="p small">开启后使用内置样例数据，无需连接后端即可体验全部界面。关闭则连接真实后端。</text>
          </view>
          <wd-switch v-model="demoOn" @change="onDemo" />
        </view>
        <view v-if="demoOn" class="demo-note">
          <text class="p small">当前为演示数据（示意值，非真实录取信息）。关闭本开关并连接后端，即可查看真实录取数据。</text>
        </view>
      </view>

      <view class="section">
        <text class="h3">三步怎么用</text>
        <view class="steps">
          <view class="step"><text class="step-n">1</text><text class="step-t">在「我能上哪」填位次，看自己落在哪一档、冲稳保怎么分。</text></view>
          <view class="step"><text class="step-n">2</text><text class="step-t">去「院校池」看每个层次的学校清单，挑一批进志愿表。</text></view>
          <view class="step"><text class="step-n">3</text><text class="step-t">在「志愿表」里排好顺序、填拟报专业，打印或导出给家人一起看。</text></view>
        </view>
        <text class="lk" @click="goVerdict">先去「我能上哪」填位次 ›</text>
      </view>

      <view class="section">
        <text class="h3">更多工具</text>
        <wd-cell-group border>
          <wd-cell title="专业图谱" label="看专业的观点、就业与偏见校正" is-link @click="goGraph" />
          <wd-cell title="八连问 · 自我诊断" label="说不清想要什么？先回答几个问题" is-link @click="goDiagnose" />
          <wd-cell title="历年省控线" label="2022–2026 各省批次线及走势" is-link @click="goCompass" />
        </wd-cell-group>
      </view>

      <view class="section">
        <text class="h3">这是什么</text>
        <text class="p">一个把「普通家庭 + 就业导向」的务实决策框架，与开源社区资源、真实录取数据结合的<text class="strong">志愿决策助手</text>。它输出决策框架而非录取结论，并内置偏见校正层。</text>
      </view>

      <view class="section">
        <text class="h3">架构</text>
        <wd-cell-group border>
          <wd-cell title="前端" value="uni-app (Vue3) · H5 / 小程序 / App" />
          <wd-cell title="UI 组件库" value="wot-design-uni" />
          <wd-cell title="后端" value="Python FastAPI" />
          <wd-cell title="数据落库" value="SQLite + SQLAlchemy" />
          <wd-cell title="数据规模" :value="'2868 所院校 · ' + majorCount + ' 专业 · ' + schoolCount + ' 所入图谱'" />
          <wd-cell title="管理端" value="/admin" is-link @click="openAdmin" />
        </wd-cell-group>
      </view>

      <view class="section">
        <text class="h3">五个方向的落地方式</text>
        <wd-collapse v-model="open">
          <wd-collapse-item title="① 决策辅助而非答案" name="1">
            <text class="p">灵魂八连问 → 框架画布，不下定论；位次只用于数据侧核验。</text>
          </wd-collapse-item>
          <wd-collapse-item title="② 定性 × 定量" name="2">
            <text class="p">专业图谱的观点 → 后端按省/科类/位次返回录取门槛与 冲稳保 判定。</text>
          </wd-collapse-item>
          <wd-collapse-item title="③ 偏见校正" name="3">
            <text class="p">每个专业都带反方 / 长期 / 官方口径提示，避免单一口径误导。</text>
          </wd-collapse-item>
          <wd-collapse-item title="④ 本地隐私" name="4">
            <text class="p">问卷输入仅存端侧存储；后端只记录匿名查询事件（省/科类/位次）。</text>
          </wd-collapse-item>
          <wd-collapse-item title="⑤ 动态更新" name="5">
            <text class="p">内容与录取数据集中在 shared/content.json 与 backend/data，管理端一键同步入库。</text>
          </wd-collapse-item>
        </wd-collapse>
      </view>

      <view class="section">
        <text class="h3">内容可溯</text>
        <wd-cell-group border>
          <wd-cell title="观点依据" :value="src.view_basis" />
          <wd-cell title="数据依据" :value="src.data_basis" />
          <wd-cell title="整理年份" :value="src.compiled_year + ' 年（' + src.compiled_date + '）'" />
        </wd-cell-group>
        <text class="p small">{{ src.caveat }}</text>
        <text class="p small">专业图谱内每个专业均标注 source_year（观点整理年份）与 source_note（该大类证据口径）。</text>
      </view>

      <view class="section">
        <text class="h3">开源资源</text>
        <text class="p small">与志愿决策 / 升学规划相关的开源项目，均提供进入入口。</text>
        <scroll-view class="filters" scroll-x="true">
          <view class="chips">
            <wd-tag v-for="r in resCats" :key="r.key" :type="cur === r.key ? 'primary' : 'default'"
                    :plain="cur !== r.key" round @click="cur = r.key">{{ r.label }}</wd-tag>
          </view>
        </scroll-view>
        <view class="grid">
          <view v-for="item in list" :key="item.name" class="res">
            <view class="top">
              <text class="name">{{ item.name }}</text>
              <wd-tag type="default" plain>{{ item.lic }}</wd-tag>
            </view>
            <text class="meta">{{ item.meta }}</text>
            <text class="desc">{{ item.desc }}</text>
            <view class="acts">
              <wd-button v-for="l in item.links" :key="l.u" size="small"
                         :type="l.t.indexOf('GitHub') >= 0 ? 'primary' : 'default'"
                         :plain="l.t.indexOf('GitHub') < 0" @click="openLink(l.u)">
                {{ l.t }} ↗
              </wd-button>
            </view>
          </view>
        </view>
      </view>

      <view class="section warn">
        <text class="h3">免责声明</text>
        <text class="p">本应用由 AI 基于公开资料与开源社区内容整理，<text class="strong">仅供学习参考，不构成正式升学/志愿填报建议</text>。实际填报请以各省教育考试院官方数据为准。收录的开源项目多为社区自发纪念与二次创作，与商业主体无关联。录取基线中 31 省为官方省控线（2022–2026），院校级投档线为真实抓取（非官方），其余为模型推算，已在接口逐条标注来源。</text>
      </view>
    </view>
    <wd-toast />
  </wd-config-provider>
</template>

<script setup>
import { ref, computed } from "vue";
import { onShow } from "@dcloudio/uni-app";
import { useToast } from "wot-design-uni";
import { APP_VERSION, DATA_DATE, CONTENT_SOURCE, RESOURCES, RES_CATS, MAJORS, SCHOOLS } from "@/utils/content.js";
import { themeVars } from "@/utils/theme.js";
import { api } from "@/utils/api.js";
import { PROFILE_OPTIONS, getProfile, setProfile } from "@/utils/profile.js";

const version = APP_VERSION;
const date = DATA_DATE;
const majorCount = MAJORS.length;
const schoolCount = SCHOOLS.length;
const open = ref("1");
const src = CONTENT_SOURCE;

const toast = useToast();
const provinces = PROFILE_OPTIONS.provinces;
const subjects = PROFILE_OPTIONS.subjects;
const NO_MAJOR = "不限（用省份基线）";
const majorOptions = [NO_MAJOR].concat(MAJORS.map((m) => m.name));

const pf = ref({ province: "", subject: "", rank: "", major: NO_MAJOR });
const saving = ref(false);
const demoOn = ref(false);

// 进入本页即同步全局档案与演示开关，保证「我的」始终反映当前状态
onShow(() => {
  const p = getProfile();
  pf.value = {
    province: p.province || "",
    subject: p.subject || "",
    rank: p.rank || "",
    major: p.major || NO_MAJOR,
  };
  demoOn.value = api.isDemo();
});

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

/* 开源资源（原「资源」tab 已并入本页） */
const resCats = RES_CATS;
const cur = ref("all");
const list = computed(() => RESOURCES.filter((r) => cur.value === "all" || r.cat === cur.value));

function goVerdict() {
  uni.switchTab({ url: "/pages/verdict/verdict" });
}
// 非 tab 页：专业图谱 / 八连问 / 历年省控线用 navigateTo
function goGraph() {
  uni.navigateTo({ url: "/pages/graph/graph" });
}
function goDiagnose() {
  uni.navigateTo({ url: "/pages/diagnose/diagnose" });
}
function goCompass() {
  uni.navigateTo({ url: "/pages/compass/compass" });
}
function openLink(u) {
  // #ifdef H5
  window.open(u, "_blank");
  // #endif
  // #ifndef H5
  uni.setClipboardData({ data: u, success: () => toast.show("链接已复制，请在浏览器打开") });
  // #endif
}

function openAdmin() {
  // #ifdef H5
  window.open("/admin", "_blank");
  // #endif
  // #ifndef H5
  uni.setClipboardData({ data: "请在后端服务地址后访问 /admin" });
  // #endif
}
</script>

<style scoped>
.page { padding: 24rpx 24rpx 60rpx; }
.hero { padding: 16rpx 8rpx 20rpx; }
.h1 { font-size: 40rpx; font-weight: 700; color: #ffd24d; }
.sub { display: block; margin-top: 10rpx; font-size: 24rpx; color: #8a909c; line-height: 1.6; }

.section { margin-bottom: 24rpx; }
.section.warn { border: 1px solid #5a4a1a; border-radius: 16rpx; padding: 20rpx; background: #1b1811; }
.h3 { font-size: 30rpx; font-weight: 600; color: #e6e8ec; display: block; margin-bottom: 12rpx; }
.p { font-size: 24rpx; color: #c7ccd4; line-height: 1.75; }
.p.small { display: block; margin-top: 8rpx; font-size: 21rpx; color: #8a909c; }
.strong { color: #ffd24d; font-weight: 600; }
.actions { display: flex; flex-direction: column; gap: 16rpx; margin-top: 18rpx; }

/* 演示模式开关 */
.switch-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 16rpx; }
.switch-text { flex: 1; }
.demo-note { margin-top: 12rpx; padding: 12rpx 16rpx; border-radius: 12rpx; background: rgba(240, 173, 78, 0.08); border: 1px solid #5a4a1a; }

/* 三步引导 */
.steps { margin-top: 8rpx; }
.step { display: flex; align-items: flex-start; gap: 14rpx; padding: 12rpx 0; }
.step-n { flex: 0 0 auto; width: 40rpx; height: 40rpx; border-radius: 50%; background: rgba(255, 210, 77, 0.15); color: #ffd24d; font-size: 22rpx; font-weight: 700; display: flex; align-items: center; justify-content: center; }
.step-t { flex: 1; font-size: 23rpx; color: #c7ccd4; line-height: 1.7; }
.lk { display: inline-block; margin-top: 14rpx; font-size: 24rpx; color: #6db3f2; }

/* 开源资源（资源 tab 迁入） */
.filters { white-space: nowrap; margin: 14rpx 0 12rpx; }
.chips { display: inline-flex; gap: 12rpx; padding: 2rpx 2rpx 6rpx; }
.grid { display: flex; flex-direction: column; gap: 20rpx; }
.res { background: #16191f; border: 1px solid #23262e; border-radius: 16rpx; padding: 22rpx; }
.top { display: flex; justify-content: space-between; align-items: center; gap: 12rpx; }
.name { font-size: 27rpx; font-weight: 600; color: #e6e8ec; }
.meta { display: block; font-size: 21rpx; color: #6b7280; margin-top: 8rpx; }
.desc { font-size: 23rpx; color: #9aa0aa; line-height: 1.7; display: block; margin: 12rpx 0 16rpx; }
.acts { display: flex; flex-wrap: wrap; gap: 12rpx; }
</style>
