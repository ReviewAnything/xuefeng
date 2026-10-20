<template>
  <wd-config-provider theme="dark" :theme-vars="themeVars">
    <view class="page">
      <view class="hero">
        <text class="h1">关于本应用</text>
        <text class="sub">v{{ version }} · 数据日期 {{ date }}</text>
        <view class="hero-tags">
          <wd-tag type="primary" plain>uni-app + Vue3</wd-tag>
          <wd-tag type="success" plain>FastAPI</wd-tag>
          <wd-tag type="default" plain>SQLite 落库</wd-tag>
        </view>
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
                         :plain="l.t.indexOf('GitHub') < 0" @click="open(l.u)">
                {{ l.t }} ↗
              </wd-button>
            </view>
          </view>
        </view>
      </view>

      <view class="section warn">
        <text class="h3">免责声明</text>
        <text class="p">本应用由 AI 基于公开资料与开源社区内容整理，<text class="strong">仅供学习参考，不构成正式升学/志愿填报建议</text>。实际填报请以各省教育考试院官方数据为准。收录的开源项目多为社区自发纪念与二次创作，与商业主体无关联。录取基线中 11 省为官方省控线/投档位次，其余为模型推算，已在接口逐条标注来源。</text>
      </view>
    </view>
  </wd-config-provider>
</template>

<script setup>
import { ref, computed } from "vue";
import { useToast } from "wot-design-uni";
import { APP_VERSION, DATA_DATE, CONTENT_SOURCE, RESOURCES, RES_CATS, MAJORS, SCHOOLS } from "@/utils/content.js";
import { themeVars } from "@/utils/theme.js";

const version = APP_VERSION;
const date = DATA_DATE;
const majorCount = MAJORS.length;
const schoolCount = SCHOOLS.length;
const open = ref("1");
const src = CONTENT_SOURCE;

/* 开源资源（原「资源」tab 已并入本页） */
const toast = useToast();
const resCats = RES_CATS;
const cur = ref("all");
const list = computed(() => RESOURCES.filter((r) => cur.value === "all" || r.cat === cur.value));

function open(u) {
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
.hero-tags { display: flex; flex-wrap: wrap; gap: 10rpx; margin-top: 14rpx; }

.section { margin-bottom: 24rpx; }
.section.warn { border: 1px solid #5a4a1a; border-radius: 16rpx; padding: 20rpx; background: #1b1811; }
.h3 { font-size: 30rpx; font-weight: 600; color: #e6e8ec; display: block; margin-bottom: 12rpx; }
.p { font-size: 24rpx; color: #c7ccd4; line-height: 1.75; }
.p.small { display: block; margin-top: 12rpx; font-size: 21rpx; color: #8a909c; }
.strong { color: #ffd24d; font-weight: 600; }

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
