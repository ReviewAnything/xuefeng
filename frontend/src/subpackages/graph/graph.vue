<template>
  <wd-config-provider :theme="$theme.mode" :theme-vars="themeVars" :style="$theme.style">
    <view class="page">
      <view class="hero">
        <text class="h1">图谱库</text>
        <text class="sub">专业图谱（观点 + 偏见校正）、学校图谱（层次圈层 × 高校联盟）、术语图谱（领域名词 ↔ 系统落点）三者合一。</text>
      </view>

      <view class="seg">
        <view v-for="s in segs" :key="s.key" class="seg-item" :class="{ on: view === s.key }"
              @click="view = s.key">
          <text class="seg-text">{{ s.name }}</text>
        </view>
      </view>

      <!-- ---------------- 专业图谱 ---------------- -->
      <block v-if="view === 'major'">
        <wd-search v-model="kw" placeholder="搜索专业名 / 标签，如：电气、天坑、考公" hide-cancel />

        <scroll-view class="filters" scroll-x="true">
          <view class="chips">
            <wd-tag v-for="c in cats" :key="c" :type="cur === c ? 'primary' : 'default'"
                    :plain="cur !== c" round @click="setCat(c)">{{ c }}</wd-tag>
          </view>
        </scroll-view>

        <view class="count">共 {{ majors.length }} 个专业</view>

        <view class="grid">
          <view v-for="m in majors" :key="m.name" class="mcard" :class="'view-' + m.view">
            <view class="mhead">
              <text class="mname">{{ m.name }}</text>
              <wd-tag :type="tagType(m.view)" plain>{{ vlabel(m.view) }}</wd-tag>
            </view>
            <text class="mcat">{{ m.cat }}</text>
            <view class="mbody">
              <text class="k">定性观点：</text>
              <text class="t">{{ m.reason }}</text>
            </view>
            <view class="tags">
              <wd-tag v-for="t in m.tags" :key="t" type="default" plain>{{ t }}</wd-tag>
            </view>
            <view class="bias">
              <text class="k">⚖ 偏见校正：</text>
              <text class="t">{{ m.bias }}</text>
            </view>
            <view class="src">
              <text class="src-y">{{ m.source_year }} 年整理</text>
              <text class="src-n">{{ m.source_note }}</text>
            </view>
            <view class="verify" @click="copyVerify(m.verify)">
              <text>🔗 核验口径：{{ shortVerify(m.verify) }}</text>
              <text class="copy">复制</text>
            </view>
          </view>
        </view>

        <view v-if="!majors.length" class="empty">没有匹配的专业，试试其他关键词。</view>
      </block>

      <!-- ---------------- 学校图谱 ---------------- -->
      <block v-if="view === 'school'">
        <view class="panel">
          <view class="panel-h">
            <text class="h3">层次圈层</text>
            <text class="rel">985 ⊂ 211 ⊂ 双一流（本图谱标注口径）</text>
          </view>
          <view v-for="t in tiers" :key="t.key" class="tier" @click="pick(t.key)">
            <view class="tier-top">
              <text class="tier-name">{{ t.name }}</text>
              <view class="tier-tags">
                <text class="tag" :class="'tag-' + natClass(t.nature)">{{ t.nature }}</text>
                <text v-if="t.incomplete" class="tag tag-warn">标注不完整</text>
              </view>
            </view>
            <text class="tier-desc">{{ t.desc }}</text>
            <text class="tier-note">{{ t.note }}</text>
            <text class="tier-count">{{ t.count }} 所</text>
          </view>
        </view>

        <scroll-view class="filters" scroll-x="true">
          <view class="chips">
            <wd-tag v-for="g in groups" :key="g.key" :type="curGroup === g.key ? 'primary' : 'default'"
                    :plain="curGroup !== g.key" round @click="curGroup = g.key">{{ g.name }} {{ g.count }}</wd-tag>
          </view>
        </scroll-view>

        <view v-if="activeGroup" class="panel">
          <view class="panel-h">
            <text class="h3">{{ activeGroup.name }}</text>
            <text class="tag" :class="'tag-' + natClass(activeGroup.nature)">{{ activeGroup.nature }}</text>
          </view>
          <text class="p">{{ activeGroup.desc }}</text>
          <text v-if="activeGroup.composition_text" class="p dim">构成：{{ activeGroup.composition_text }}</text>
          <text v-if="activeGroup.source_note" class="p dim">{{ activeGroup.source_note }}</text>
          <view class="acts">
            <wd-button size="small" plain @click="open(activeGroup.source_url || meta.source_url)">
              查看来源 ↗
            </wd-button>
          </view>
        </view>

        <wd-search v-model="skw" placeholder="搜索校名 / 省份 / 主管部门" hide-cancel />

        <scroll-view class="filters" scroll-x="true">
          <view class="chips">
            <wd-tag v-for="p in provinces" :key="p" :type="curProv === p ? 'primary' : 'default'"
                    :plain="curProv !== p" round @click="curProv = p">{{ p }}</wd-tag>
          </view>
        </scroll-view>

        <view class="count">共 {{ schools.length }} 所院校</view>

        <view class="grid">
          <view v-for="s in schools" :key="s.name" class="scard">
            <view class="shead">
              <text class="sname">{{ s.name }}</text>
              <text class="sloc">{{ s.province }} · {{ s.city }}</text>
            </view>
            <view class="stags">
              <text v-for="g in groupNames(s)" :key="g.key" class="stag" :class="'stag-' + g.cls">{{ g.name }}</text>
            </view>
            <text class="smeta">{{ s.level }} · {{ s.nature }} · {{ s.supervisor }}<text v-if="s.category"> · {{ s.category }}</text></text>
          </view>
        </view>

        <view v-if="!schools.length" class="empty">没有匹配的院校，换个圈层或关键词试试。</view>

        <view class="panel warn">
          <text class="h3">口径提醒</text>
          <text class="p">{{ meta.caveat }}</text>
          <text class="p dim">底表：{{ meta.source }}</text>
          <view class="acts">
            <wd-button size="small" plain @click="open(meta.source_url)">教育部名单 ↗</wd-button>
            <wd-button size="small" plain @click="open(meta.dfc_source_url)">第二轮双一流名单 ↗</wd-button>
          </view>
        </view>
      </block>

      <!-- ---------------- 术语图谱 ---------------- -->
      <block v-if="view === 'term'">
        <wd-search v-model="tkw" placeholder="搜索术语 / 别名 / 释义" hide-cancel />

        <scroll-view class="filters" scroll-x="true">
          <view class="chips">
            <wd-tag v-for="c in termCats" :key="c" :type="curTermCat === c ? 'primary' : 'default'"
                    :plain="curTermCat !== c" round @click="curTermCat = c">{{ c }}</wd-tag>
          </view>
        </scroll-view>

        <view class="seg">
          <view v-for="s in termSegs" :key="s.key" class="seg-item" :class="{ on: termView === s.key }"
                @click="termView = s.key">
            <text class="seg-text">{{ s.name }}</text>
          </view>
        </view>

        <!-- 术语 -->
        <template v-if="termView === 'terms'">
          <view class="count">共 {{ filteredTerms.length }} 个术语</view>
          <view class="grid">
            <view v-for="n in filteredTerms" :key="n.id" class="tcard">
              <view class="mhead">
                <text class="mname">{{ n.term }}</text>
                <wd-tag plain>{{ n.category }}</wd-tag>
              </view>
              <text v-if="n.aka && n.aka.length" class="aka">别名：{{ n.aka.join('、') }}</text>
              <text class="mcat">{{ n.definition }}</text>
              <view v-if="n.system" class="sys" @click="toggleSys(n.id)">
                <text class="k">⚙ 系统落点（点击{{ openSys[n.id] ? '收起' : '展开' }}）</text>
                <text v-if="openSys[n.id]" class="sys-body">{{ sysText(n.system) }}</text>
              </view>
            </view>
          </view>
          <view v-if="!filteredTerms.length" class="empty">没有匹配的术语，换个关键词试试。</view>
        </template>

        <!-- 关系网络 -->
        <template v-else>
          <view class="count">共 {{ filteredEdges.length }} 条关系</view>
          <view class="grid">
            <view v-for="(e, i) in filteredEdges" :key="i" class="ecard" @click="jumpTo(e.source)">
              <text class="eterm">{{ termName(e.source) }}</text>
              <text class="erel">{{ e.relation }}</text>
              <text class="eterm">{{ termName(e.target) }}</text>
            </view>
          </view>
          <view v-if="!filteredEdges.length" class="empty">没有匹配的关系。</view>
        </template>
      </block>
    </view>
    <wd-toast />
  </wd-config-provider>
</template>

<script setup lang="ts">
import { ref, computed, reactive } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { useToast } from "wot-design-uni";
import { CATS, VIEW_LABEL, ensureContent } from "@/utils/content";
import { themeVars } from "@/utils/theme";

const toast = useToast();

// P1 分包瘦身：SCHOOL_GRAPH / GLOSSARY / MAJORS 等大体积数据按需懒加载（见 onLoad），
// 不进主包初始体积。以下用 ref 承接，确保 ensureContent() 后响应式刷新（computed 依赖这些 ref）。
const meta = ref<Record<string, any>>({});
const tiers = ref<any[]>([]);
const leagues = ref<any[]>([]);
const allSchools = ref<any[]>([]);
const MAJORS_DATA = ref<any[]>([]);
const glossaryNodes = ref<any[]>([]);
const glossaryEdges = ref<any[]>([]);
const termCatData = ref<any[]>([]);

const segs = [
  { key: "major", name: "专业图谱" },
  { key: "school", name: "学校图谱" },
  { key: "term", name: "术语图谱" },
];
const view = ref("major");

/* ---------- 专业图谱 ---------- */
const cats = ["全部", ...CATS];
const cur = ref("全部");
const kw = ref("");
const majors = computed(() =>
  MAJORS_DATA.value.filter(
    (m) =>
      (cur.value === "全部" || m.cat === cur.value) &&
      (!kw.value || (m.name + m.tags.join("") + m.reason).includes(kw.value))
  )
);
function setCat(c: any) { cur.value = c; }
function vlabel(v: any) { return VIEW_LABEL[v]; }
function tagType(v: any) { return { recommend: "success", caution: "warning", avoid: "danger" }[v] || "default"; }
function shortVerify(s: any) { return s.length > 32 ? s.slice(0, 32) + "…" : s; }
function copyVerify(s: any) {
  uni.setClipboardData({
    data: s,
    success: () => toast.show("核验口径已复制"),
  });
}

/* ---------- 学校图谱 ---------- */
const curGroup = ref("all");
const curProv = ref("全部省份");
const skw = ref("");

const groupIndex = computed(() => {
  const map: Record<string, any> = {};
  tiers.value.forEach((t) => { map[t.key] = { ...t, kind: "tier" }; });
  leagues.value.forEach((l) => { map[l.key] = { ...l, kind: "league" }; });
  return map;
});
const groups = computed(() => [
  { key: "all", name: "全部", count: allSchools.value.length },
  ...tiers.value.map((t) => ({ key: t.key, name: t.name, count: t.count })),
  ...leagues.value.map((l) => ({ key: l.key, name: l.name, count: l.count })),
]);
const activeGroup = computed(() =>
  curGroup.value === "all" ? null : groupIndex.value[curGroup.value] || null
);
const schools = computed(() =>
  allSchools.value.filter(
    (s) =>
      (curGroup.value === "all" || s.groups.indexOf(curGroup.value) >= 0) &&
      (curProv.value === "全部省份" || s.province === curProv.value) &&
      (!skw.value ||
        (s.name + s.province + s.city + s.supervisor + s.category).indexOf(skw.value) >= 0)
  )
);
const provinces = computed(() => {
  const set: any[] = [];
  schools.value.forEach((s) => { if (s.province && set.indexOf(s.province) < 0) set.push(s.province); });
  return ["全部省份", ...set.sort()];
});

function pick(key: any) {
  curGroup.value = key;
  curProv.value = "全部省份";
}
function natClass(nature: any) {
  if (nature === "官方工程" || nature === "官方口径") return "official";
  if (nature === "高校联盟") return "league";
  return "folk";
}
function groupNames(s: any) {
  const out: any[] = [];
  ["985", "211", "dfc"].forEach((k) => {
    if (s.groups.indexOf(k) >= 0) {
      const t = groupIndex.value[k];
      out.push({ key: k, name: k === "dfc" ? "双一流" : t.name.replace(" 工程", ""), cls: "tier" });
    }
  });
  leagues.value.forEach((l) => {
    if (s.groups.indexOf(l.key) >= 0) out.push({ key: l.key, name: l.name, cls: "league" });
  });
  return out;
}
function open(u: any) {
  // #ifdef H5
  window.open(u, "_blank");
  // #endif
  // #ifndef H5
  uni.setClipboardData({ data: u, success: () => toast.show("链接已复制，请在浏览器打开") });
  // #endif
}

/* ---------- 术语图谱 ---------- */
const termCats = computed(() => ["全部", ...termCatData.value]);
const curTermCat = ref("全部");
const tkw = ref("");
const termView = ref("terms");
const termSegs = [
  { key: "terms", name: "术语" },
  { key: "edges", name: "关系网络" },
];
const openSys = reactive<Record<string, any>>({});
const termIndex = computed(() => {
  const m: Record<string, any> = {};
  glossaryNodes.value.forEach((n) => { m[n.id] = n; });
  return m;
});
const filteredTerms = computed(() =>
  glossaryNodes.value.filter(
    (n) =>
      (curTermCat.value === "全部" || n.category === curTermCat.value) &&
      (!tkw.value || (n.term + (n.aka || []).join("") + n.definition).includes(tkw.value))
  )
);
const filteredEdges = computed(() =>
  glossaryEdges.value.filter((e) => {
    const s = termIndex.value[e.source];
    const t = termIndex.value[e.target];
    if (curTermCat.value !== "全部") {
      const okS = s && s.category === curTermCat.value;
      const okT = t && t.category === curTermCat.value;
      if (!okS && !okT) return false;
    }
    if (tkw.value) {
      const hay = (s ? s.term : e.source) + (t ? t.term : e.target) + e.relation;
      if (!hay.includes(tkw.value)) return false;
    }
    return true;
  })
);
function toggleSys(id: any) { openSys[id] = !openSys[id]; }
function sysText(sys: any) {
  if (!sys) return "";
  const parts: any[] = [];
  const push = (k: any, v: any) => { if (v != null) parts.push(k + "：" + (Array.isArray(v) ? v.join("、") : v)); };
  push("表", sys.tables);
  push("文件", sys.files);
  push("字段", sys.fields);
  push("模块", sys.modules);
  push("接口", sys.api);
  push("取值", sys.values);
  push("来源", sys.data_source);
  push("实践", sys.practice);
  push("规则", sys.rule);
  push("工具", sys.tool);
  push("缓解", sys.mitigation);
  push("计数", sys.counts);
  if (sys.note) parts.push("注：" + sys.note);
  return parts.join("；");
}
function termName(id: any) { const n = termIndex.value[id]; return n ? n.term : id; }
function jumpTo(id: any) {
  curTermCat.value = "全部";
  tkw.value = termName(id);
  termView.value = "terms";
}

/* ---------- 懒加载：进入页面后按需拉取大体积内容数据（分包瘦身核心） ---------- */
onLoad(async () => {
  const data = await ensureContent();
  const sg = data.SCHOOL_GRAPH || {};
  meta.value = sg.meta || {};
  tiers.value = sg.tiers || [];
  leagues.value = sg.leagues || [];
  allSchools.value = sg.schools || [];
  const gl = data.GLOSSARY || {};
  glossaryNodes.value = gl.nodes || [];
  glossaryEdges.value = gl.edges || [];
  termCatData.value = (gl.meta && gl.meta.categories) || [];
  MAJORS_DATA.value = data.MAJORS || [];
});
</script>

<style scoped>
.page { padding: 24rpx 24rpx 60rpx; }
.hero { padding: 16rpx 8rpx 20rpx; }
.h1 { font-size: 40rpx; font-weight: 700; color: #ffd24d; }
.sub { display: block; margin-top: 10rpx; font-size: 24rpx; color: #8a909c; line-height: 1.6; }

.seg { display: flex; gap: 12rpx; margin-bottom: 18rpx; }
.seg-item {
  flex: 1; text-align: center; padding: 16rpx 0; border-radius: 999rpx;
  background: #16191f; border: 1px solid #23262e;
}
.seg-item.on { background: #2a2413; border-color: #6b5a1c; }
.seg-text { font-size: 26rpx; color: #8a909c; }
.seg-item.on .seg-text { color: #ffd24d; font-weight: 600; }

.filters { white-space: nowrap; margin: 18rpx 0 14rpx; }
.chips { display: inline-flex; gap: 12rpx; padding: 2rpx 2rpx 6rpx; }
.count { font-size: 22rpx; color: #6b7280; margin: 6rpx 0 14rpx; }
.grid { display: flex; flex-direction: column; gap: 20rpx; }
.empty { margin-top: 40rpx; text-align: center; font-size: 24rpx; color: #6b7280; }

/* 专业卡（沿用原专业图谱样式） */
.mcard { background: #16191f; border: 1px solid #23262e; border-radius: 16rpx; padding: 22rpx; }
.mhead { display: flex; justify-content: space-between; align-items: center; gap: 12rpx; }
.mname { font-size: 28rpx; font-weight: 600; color: #e6e8ec; }
.mcat { display: block; font-size: 21rpx; color: #6b7280; margin-top: 6rpx; }
.mbody { margin-top: 14rpx; }
.k { font-size: 23rpx; color: #ffd24d; }
.t { font-size: 23rpx; color: #c7ccd4; line-height: 1.7; }
.tags { display: flex; flex-wrap: wrap; gap: 10rpx; margin: 14rpx 0; }
.bias { background: #12151a; border-radius: 12rpx; padding: 14rpx; }
.src { display: flex; justify-content: space-between; margin-top: 14rpx; gap: 12rpx; }
.src-y { font-size: 20rpx; color: #8a909c; }
.src-n { font-size: 20rpx; color: #6b7280; flex: 1; text-align: right; }
.verify {
  display: flex; justify-content: space-between; align-items: center; gap: 12rpx;
  margin-top: 14rpx; padding-top: 14rpx; border-top: 1px solid #23262e;
  font-size: 21rpx; color: #6db3f2;
}
.copy { color: #ffd24d; }

/* 学校图谱 */
.panel { background: #16191f; border: 1px solid #23262e; border-radius: 16rpx; padding: 22rpx; margin-bottom: 20rpx; }
.panel.warn { border-color: #5a4a1a; background: #1b1811; }
.panel-h { display: flex; align-items: center; justify-content: space-between; gap: 12rpx; margin-bottom: 12rpx; }
.h3 { font-size: 28rpx; font-weight: 600; color: #e6e8ec; }
.rel { font-size: 20rpx; color: #6b7280; }
.p { display: block; font-size: 23rpx; color: #c7ccd4; line-height: 1.7; }
.p.dim { color: #8a909c; font-size: 21rpx; margin-top: 8rpx; }

.tier { padding: 16rpx 0; border-top: 1px solid #23262e; }
.tier:first-of-type { border-top: none; }
.tier-top { display: flex; align-items: center; justify-content: space-between; gap: 12rpx; }
.tier-name { font-size: 26rpx; font-weight: 600; color: #e6e8ec; }
.tier-tags { display: flex; gap: 8rpx; }
.tier-desc { display: block; margin-top: 8rpx; font-size: 22rpx; color: #9aa0aa; line-height: 1.65; }
.tier-note { display: block; margin-top: 6rpx; font-size: 20rpx; color: #6b7280; line-height: 1.6; }
.tier-count { display: block; margin-top: 8rpx; font-size: 22rpx; color: #ffd24d; }

.tag { font-size: 19rpx; padding: 3rpx 10rpx; border-radius: 999rpx; border: 1px solid #2a2e37; color: #8a909c; }
.tag-official { color: #5fd87f; border-color: #274a33; }
.tag-league { color: #6db3f2; border-color: #24405c; }
.tag-folk { color: #f0ad4e; border-color: #55411d; }
.tag-warn { color: #ff6b6b; border-color: #5c2626; }

.scard { background: #16191f; border: 1px solid #23262e; border-radius: 16rpx; padding: 20rpx; }
.shead { display: flex; align-items: baseline; justify-content: space-between; gap: 12rpx; }
.sname { font-size: 27rpx; font-weight: 600; color: #e6e8ec; }
.sloc { font-size: 21rpx; color: #6b7280; }
.stags { display: flex; flex-wrap: wrap; gap: 8rpx; margin: 12rpx 0; }
.stag { font-size: 19rpx; padding: 3rpx 10rpx; border-radius: 999rpx; }
.stag-tier { background: #2a2413; color: #ffd24d; }
.stag-league { background: #16222e; color: #6db3f2; }
.smeta { font-size: 21rpx; color: #6b7280; }

.acts { display: flex; flex-wrap: wrap; gap: 12rpx; margin-top: 14rpx; }

/* 术语图谱 */
.tcard { background: #16191f; border: 1px solid #23262e; border-radius: 16rpx; padding: 22rpx; }
.aka { display: block; margin-top: 8rpx; font-size: 21rpx; color: #6db3f2; }
.sys { margin-top: 14rpx; padding-top: 14rpx; border-top: 1px solid #23262e; }
.sys .sys-body { display: block; margin-top: 10rpx; font-size: 21rpx; color: #9aa0aa; line-height: 1.7; }
.ecard {
  background: #16191f; border: 1px solid #23262e; border-radius: 16rpx;
  padding: 18rpx 20rpx; display: flex; flex-direction: column; gap: 8rpx;
}
.eterm { font-size: 25rpx; font-weight: 600; color: #e6e8ec; }
.erel { font-size: 21rpx; color: #ffd24d; line-height: 1.6; }
</style>
