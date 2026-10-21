/* 志愿决策助手 · 管理端控制台（Vue 3 + Element Plus，免构建） */
const { createApp, ref, reactive, computed, onMounted, watch } = Vue;
const { ElMessage, ElMessageBox } = ElementPlus;

const TOKEN_KEY = "xuefeng_admin_token";
const USER_KEY = "xuefeng_admin_user";

/* ------------------------------------------------------------ 图标 */
const ICONS = {
  dashboard: "M4 13h6V4H4v9Zm0 7h6v-5H4v5Zm10 0h6v-9h-6v9Zm0-16v5h6V4h-6Z",
  school: "M12 2 1 8l11 6 9-4.9V16h2V8L12 2ZM5 12.2V17c0 2.2 3.1 4 7 4s7-1.8 7-4v-4.8l-7 3.8-7-3.8Z",
  chart: "M3 3h2v16h16v2H3V3Zm4 11h3v4H7v-4Zm5-6h3v10h-3V8Zm5-4h3v14h-3V4Z",
  sync: "M12 4V1L8 5l4 4V6a6 6 0 0 1 5.2 9l1.5 1.5A8 8 0 0 0 12 4Zm0 14a6 6 0 0 1-5.2-9L5.3 7.5A8 8 0 0 0 12 20v3l4-4-4-4v3Z",
  list: "M4 5h16v2H4V5Zm0 6h16v2H4v-2Zm0 6h10v2H4v-2Z",
  settings: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm9.4 4a7.6 7.6 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7.6 7.6 0 0 0-2-1.2L16.5 2h-4l-.4 2.6a7.6 7.6 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7.6 7.6 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7.6 7.6 0 0 0 2 1.2l.4 2.6h4l.4-2.6a7.6 7.6 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2Z",
  refresh: "M17.7 6.3A8 8 0 1 0 20 12h-2a6 6 0 1 1-1.8-4.3L13 11h7V4l-2.3 2.3Z",
  download: "M11 3h2v9l3.5-3.5 1.4 1.4L12 16l-5.9-6.1 1.4-1.4L11 12V3ZM4 18h16v2H4v-2Z",
  chevron: "M7 10l5 5 5-5H7Z",
  database: "M12 2c-4.4 0-8 1.3-8 3v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5c0-1.7-3.6-3-8-3Zm0 2c3.9 0 6 .9 6 1s-2.1 1-6 1-6-.9-6-1 2.1-1 6-1Zm6 15c0 .1-2.1 1-6 1s-6-.9-6-1v-2.3c1.4.7 3.5 1.1 6 1.1s4.6-.4 6-1.1V19Zm0-5c0 .1-2.1 1-6 1s-6-.9-6-1v-2.3c1.4.7 3.5 1.1 6 1.1s4.6-.4 6-1.1V14Z",
  upload: "M11 15V7.8L8.4 10.4 7 9l5-5 5 5-1.4 1.4L13 7.8V15h-2ZM4 19h16v2H4v-2Z",
};

const AppIcon = {
  props: { name: { type: String, default: "dashboard" } },
  computed: { path() { return ICONS[this.name] || ICONS.dashboard; } },
  template: `<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
      <path :d="path" fill="currentColor" />
    </svg>`,
};

/* ------------------------------------------------------------ 折线图 */
const LineChart = {
  props: { data: { type: Array, default: () => [] } },
  setup(props) {
    const W = 640, H = 210, pad = { l: 36, r: 14, t: 14, b: 26 };
    const maxV = computed(() => Math.max(4, ...props.data.map((d) => Math.max(d.verify || 0, d.search || 0))));
    const stepX = computed(() => {
      const n = props.data.length;
      return n <= 1 ? 0 : (W - pad.l - pad.r) / (n - 1);
    });
    const px = (i) => pad.l + stepX.value * i;
    const py = (v) => pad.t + (H - pad.t - pad.b) * (1 - v / maxV.value);
    const grid = computed(() => [0, 0.25, 0.5, 0.75, 1].map((r) => ({
      y: pad.t + (H - pad.t - pad.b) * r,
      label: Math.round(maxV.value * (1 - r)),
    })));
    const line = (key) => props.data.map((d, i) => `${i === 0 ? "M" : "L"}${px(i).toFixed(1)},${py(d[key] || 0).toFixed(1)}`).join(" ");
    const pathVerify = computed(() => line("verify"));
    const pathSearch = computed(() => line("search"));
    const areaVerify = computed(() => {
      const base = H - pad.b;
      return `${pathVerify.value} L${px(props.data.length - 1)},${base} L${px(0)},${base} Z`;
    });
    const ptsVerify = computed(() => props.data.map((d, i) => ({ x: px(i), y: py(d.verify || 0) })));
    const xLabels = computed(() => props.data.map((d, i) => ({ x: px(i), label: d.date })).filter((_, i) => i % 2 === 0));
    return { W, H, pad, grid, pathVerify, pathSearch, areaVerify, ptsVerify, xLabels };
  },
  template: `
    <svg class="chart" :viewBox="'0 0 ' + W + ' ' + H" role="img">
      <defs>
        <linearGradient id="lc-verify" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#ffd24d" stop-opacity="0.35" />
          <stop offset="100%" stop-color="#ffd24d" stop-opacity="0" />
        </linearGradient>
      </defs>
      <g>
        <line v-for="(g,i) in grid" :key="'g'+i" class="grid-line" :x1="pad.l" :x2="W-pad.r" :y1="g.y" :y2="g.y" />
        <text v-for="(g,i) in grid" :key="'t'+i" :x="pad.l-8" :y="g.y+3" text-anchor="end">{{ g.label }}</text>
      </g>
      <path :d="areaVerify" fill="url(#lc-verify)" />
      <path :d="pathSearch" fill="none" stroke="#6db3f2" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
      <path :d="pathVerify" fill="none" stroke="#ffd24d" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round" />
      <circle v-for="(p,i) in ptsVerify" :key="'c'+i" :cx="p.x" :cy="p.y" r="2.6" fill="#ffd24d" />
      <text v-for="(l,i) in xLabels" :key="'x'+i" :x="l.x" :y="H-6" text-anchor="middle">{{ l.label }}</text>
    </svg>`,
};

/* ------------------------------------------------------------ 环形图 */
const DonutChart = {
  props: { data: { type: Array, default: () => [] } },
  setup(props) {
    const COLORS = ["#ffd24d", "#f0ad4e", "#6db3f2", "#5a6270"];
    const R = 54, C = 2 * Math.PI * R;
    const total = computed(() => props.data.reduce((s, d) => s + (d.value || 0), 0));
    const segments = computed(() => {
      let acc = 0;
      return props.data.map((d, i) => {
        const len = total.value ? ((d.value || 0) / total.value) * C : 0;
        const seg = { ...d, len, offset: -acc, color: COLORS[i % COLORS.length],
          percent: total.value ? ((d.value || 0) / total.value) * 100 : 0 };
        acc += len;
        return seg;
      });
    });
    return { R, C, total, segments };
  },
  template: `
    <div class="donut-wrap">
      <svg class="donut" viewBox="0 0 150 150">
        <circle cx="75" cy="75" :r="R" fill="none" stroke="#22262e" stroke-width="16" />
        <circle v-for="(s,i) in segments" :key="i" cx="75" cy="75" :r="R" fill="none"
                :stroke="s.color" stroke-width="16" stroke-linecap="butt"
                :stroke-dasharray="s.len + ' ' + (C - s.len)" :stroke-dashoffset="s.offset"
                transform="rotate(-90 75 75)" />
        <text x="75" y="71" text-anchor="middle" fill="#e6e8ec" font-size="19" font-weight="700">{{ total }}</text>
        <text x="75" y="89" text-anchor="middle" fill="#6b7280" font-size="10">所院校</text>
      </svg>
      <div class="donut-legend">
        <div v-for="(s,i) in segments" :key="'l'+i">
          <i :style="{ background: s.color }"></i>{{ s.name }}
          <b>{{ s.value }}</b><small>{{ s.percent.toFixed(1) }}%</small>
        </div>
      </div>
    </div>`,
};

/* ------------------------------------------------------------ 条形榜 */
const BarList = {
  props: { data: { type: Array, default: () => [] } },
  setup(props) {
    const max = computed(() => Math.max(1, ...props.data.map((d) => d.value || 0)));
    return { max };
  },
  template: `
    <div class="bars">
      <div class="bar-row" v-for="d in data" :key="d.name">
        <span>{{ d.name }}</span>
        <div class="bar-track"><div class="bar-fill" :style="{ width: (d.value / max * 100) + '%' }"></div></div>
        <em>{{ d.value }}</em>
      </div>
      <el-empty v-if="!data.length" description="暂无数据" :image-size="60" />
    </div>`,
};

/* ------------------------------------------------------------ 主应用 */
const app = createApp({
  components: { AppIcon, LineChart, DonutChart, BarList },
  setup() {
    const token = ref(localStorage.getItem(TOKEN_KEY) || "");
    const user = ref(JSON.parse(localStorage.getItem(USER_KEY) || "null"));
    const profile = ref({});
    const loginForm = reactive({ username: "admin", password: "" });
    const loginLoading = ref(false);
    const loading = ref(false);
    const page = ref("dashboard");

    const navItems = [
      { key: "dashboard", label: "数据看板", icon: "dashboard", title: "数据看板", desc: "院校、录取基线与查询流量的整体概览" },
      { key: "universities", label: "院校库", icon: "school", title: "全国院校库", desc: "教育部普通高校名单 2868 所，可检索与导出" },
      { key: "baselines", label: "录取基线", icon: "chart", title: "录取基线", desc: "31 省估算基线 + 11 省官方省控线覆盖，支持按年份浏览与单条修正" },
      { key: "versions", label: "数据版本", icon: "database", title: "数据版本", desc: "年度更新：建草稿 → 校验 → 发布；支持补丁、审计与回滚" },
      { key: "sync", label: "数据同步", icon: "sync", title: "数据同步", desc: "静态数据源 → 数据库的幂等同步" },
      { key: "lines", label: "校线导入", icon: "upload", title: "院校投档线导入", desc: "上传各省投档表（CSV/XLSX），校名匹配后落库；先预览再入库" },
      { key: "events", label: "查询日志", icon: "list", title: "查询日志", desc: "匿名记录核验 / 检索调用，用于产品分析" },
      { key: "settings", label: "系统设置", icon: "settings", title: "系统设置", desc: "账号安全与运行环境" },
    ];
    const currentTitle = computed(() => (navItems.find((n) => n.key === page.value) || {}).title || "");
    const currentDesc = computed(() => (navItems.find((n) => n.key === page.value) || {}).desc || "");

    const overview = ref(null);
    const meta = ref(null);

    /* ---------- 请求封装 ---------- */
    async function api(path, options = {}) {
      const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
      if (token.value) headers.Authorization = `Bearer ${token.value}`;
      const res = await fetch(path, { ...options, headers });
      const data = await res.json().catch(() => ({}));
      if (res.status === 401) {
        logout(true);
        // 后端区分「过期」与「改密后失效」，直接透传更利于用户理解
        throw new Error(data.detail || "登录已过期，请重新登录");
      }
      if (res.status === 429) {
        throw new Error(data.detail || "操作过于频繁，请稍后再试");
      }
      if (!res.ok) throw new Error(data.detail || `请求失败（${res.status}）`);
      return data;
    }

    /* ---------- 登录 ---------- */
    async function doLogin() {
      if (!loginForm.username || !loginForm.password) {
        ElMessage.warning("请输入账号与密码");
        return;
      }
      loginLoading.value = true;
      try {
        const res = await api("/api/admin/login", {
          method: "POST",
          body: JSON.stringify({ username: loginForm.username, password: loginForm.password }),
        });
        token.value = res.token;
        user.value = res.user;
        localStorage.setItem(TOKEN_KEY, res.token);
        localStorage.setItem(USER_KEY, JSON.stringify(res.user));
        ElMessage.success("登录成功");
        await refreshAll();
      } catch (e) {
        ElMessage.error(e.message);
      } finally {
        loginLoading.value = false;
      }
    }

    function logout(silent = false) {
      token.value = "";
      user.value = null;
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
      if (!silent) ElMessage.success("已退出登录");
    }

    async function onUserCommand(cmd) {
      if (cmd === "settings") { page.value = "settings"; return; }
      if (cmd === "logout") {
        try {
          await ElMessageBox.confirm("确认退出当前登录？", "提示", { type: "warning" });
          logout();
        } catch (_) { /* 取消 */ }
      }
    }

    /* ---------- 看板 ---------- */
    const kpiCards = computed(() => {
      const k = overview.value ? overview.value.kpis : {};
      return [
        { label: "院校总数", value: k.universities || 0, unit: "所", icon: "school",
          sub: `本科 ${k.benke || 0} · 专科 ${k.zhuanke || 0}` },
        { label: "985 / 211", value: `${k.elite_985 || 0} / ${k.elite_211 || 0}`, icon: "chart",
          sub: `权威清单 112 所（含军校）` },
        { label: "录取基线", value: k.baseline_rows || 0, unit: "行", icon: "database",
          sub: `官方 ${k.official_rows || 0} 行 · 覆盖 ${k.official_provinces || 0} 省` },
        { label: "今日查询", value: k.queries_today || 0, unit: "次", icon: "list",
          sub: `近 7 天 ${k.queries_week || 0} 次 · 累计 ${k.queries_total || 0}` },
      ];
    });

    async function loadOverview() {
      overview.value = await api("/api/admin/overview");
      if (overview.value.admin && user.value) {
        user.value.must_change_password = overview.value.admin.must_change_password;
      }
    }

    async function loadMeta() {
      meta.value = await api("/api/admin/meta");
      if (meta.value.content && !user.value) user.value = { username: "admin" };
    }

    async function loadProfile() {
      try {
        const r = await api("/api/admin/me");
        profile.value = r.user;
        user.value = { username: r.user.username, role: r.user.role,
          must_change_password: r.user.must_change_password };
      } catch (_) { /* 401 已处理 */ }
    }

    /* ---------- 数据库配置（管理端多数据库配置） ---------- */
    const dbState = ref(null);
    const dbForm = reactive({
      dialect: "sqlite", mode: "form", host: "", port: null, database: "", username: "",
      password: "", path: "", url: "", ssl: false, seed: true,
    });
    const dbTesting = ref(false);
    const dbApplying = ref(false);
    const dbResetting = ref(false);
    const dbResult = ref(null);

    const dbDialects = computed(() => (dbState.value ? dbState.value.dialects : []));
    const dbResultTitle = computed(() => {
      const r = dbResult.value;
      if (!r) return "";
      if (r.kind === "test") return r.ok ? "连接成功" : "连接失败";
      return r.ok ? "已切换并完成初始化播种" : "切换失败（服务仍停在原数据库）";
    });

    function dbPayload() {
      return { ...dbForm };
    }

    async function loadDbConfig() {
      dbState.value = await api("/api/admin/db-config");
      const c = dbState.value.config;
      Object.assign(dbForm, {
        dialect: c.dialect, mode: c.mode, host: c.host, port: c.port, database: c.database,
        username: c.username, path: c.path, url: c.url, ssl: c.ssl,
      });
      // 口令永不回流到页面：留空即表示「沿用已保存口令」
      dbForm.password = "";
    }

    function onDialectChange(key) {
      const d = dbDialects.value.find((x) => x.key === key);
      if (!d) return;
      dbForm.port = d.default_port || null;
      if (key === "sqlite" && !dbForm.path) dbForm.path = dbState.value ? dbState.value.default_path : "";
      dbResult.value = null;
    }

    async function testDb() {
      dbTesting.value = true;
      dbResult.value = null;
      try {
        const r = await api("/api/admin/db-config/test", {
          method: "POST", body: JSON.stringify(dbPayload()),
        });
        dbResult.value = { kind: "test", ...r };
        if (r.ok) ElMessage.success(`连接成功（${r.latency_ms} ms）`);
        else ElMessage.error(r.error || "连接失败");
      } catch (e) {
        dbResult.value = { kind: "test", ok: false, error: e.message };
        ElMessage.error(e.message);
      } finally {
        dbTesting.value = false;
      }
    }

    async function applyDb() {
      try {
        await ElMessageBox.confirm(
          "将切换到该数据库并立即建表播种（数据写入新库）。切换失败会自动回滚，确认继续？",
          "切换数据库", { type: "warning" });
      } catch (_) { return; }
      dbApplying.value = true;
      dbResult.value = null;
      try {
        const r = await api("/api/admin/db-config/apply", {
          method: "POST", body: JSON.stringify(dbPayload()),
        });
        dbResult.value = { kind: "apply", ...r };
        ElMessage.success(r.message || "已切换并初始化");
        await loadDbConfig();
        await refreshAll();
      } catch (e) {
        dbResult.value = { kind: "apply", ok: false, error: e.message };
        ElMessage.error(e.message);
      } finally {
        dbApplying.value = false;
      }
    }

    async function resetDb() {
      try {
        await ElMessageBox.confirm("清除落盘配置并恢复默认 SQLite（随后重新初始化播种）？",
          "恢复默认数据库", { type: "warning" });
      } catch (_) { return; }
      dbResetting.value = true;
      dbResult.value = null;
      try {
        const r = await api("/api/admin/db-config/reset", { method: "POST", body: "{}" });
        dbResult.value = { kind: "apply", ...r };
        ElMessage.success(r.message || "已恢复默认 SQLite");
        await loadDbConfig();
        await refreshAll();
      } catch (e) {
        dbResult.value = { kind: "apply", ok: false, error: e.message };
        ElMessage.error(e.message);
      } finally {
        dbResetting.value = false;
      }
    }

    /* ---------- 院校库 ---------- */
    const uniFilters = reactive({ q: "", province: "", level: "", tier: "", nature: "" });
    const uniRows = ref([]);
    const uniTotal = ref(0);
    const uniPage = ref(1);
    const uniPages = ref(1);
    const uniPageSize = 20;
    const uniLoading = ref(false);

    async function loadUniversities(p = 1) {
      uniPage.value = p;
      uniLoading.value = true;
      try {
        const qs = new URLSearchParams({ page: String(p), page_size: String(uniPageSize) });
        Object.entries(uniFilters).forEach(([k, v]) => { if (v) qs.set(k, v); });
        const res = await api(`/api/admin/universities?${qs}`);
        uniRows.value = res.universities;
        uniTotal.value = res.total_matched;
        uniPages.value = res.pages;
      } catch (e) {
        ElMessage.error(e.message);
      } finally {
        uniLoading.value = false;
      }
    }

    function resetUniFilters() {
      Object.keys(uniFilters).forEach((k) => (uniFilters[k] = ""));
      loadUniversities(1);
    }

    /* ---------- 录取基线 ---------- */
    const baseFilters = reactive({ province: "", subject: "" });
    const baseRows = ref([]);
    const baseLoading = ref(false);
    const baselineYear = ref(null);
    const baseOfficialCount = computed(() => baseRows.value.filter((r) => r.data_source === "official").length);

    async function loadBaselines() {
      baseLoading.value = true;
      try {
        const qs = new URLSearchParams();
        if (baseFilters.province) qs.set("province", baseFilters.province);
        if (baseFilters.subject) qs.set("subject", baseFilters.subject);
        if (baselineYear.value) qs.set("year", String(baselineYear.value));
        const res = await api(`/api/admin/baselines?${qs}`);
        baseRows.value = res.rows;
        baselineYear.value = res.year;
      } catch (e) {
        ElMessage.error(e.message);
      } finally {
        baseLoading.value = false;
      }
    }

    /* ---------- 基线单条补丁 ---------- */
    const editDialog = ref(false);
    const editSaving = ref(false);
    const editForm = reactive({ id: null, label: "", min_score: 0, min_rank: 0,
      source_url: "", source_year: null, reason: "" });

    function openEdit(row) {
      editForm.id = row.id;
      editForm.label = `${row.year} · ${row.province}/${row.subject}/${row.tier}`;
      editForm.min_score = row.min_score;
      editForm.min_rank = row.min_rank;
      editForm.source_url = row.source_url || "";
      editForm.source_year = row.source_year || row.year;
      editForm.reason = "";
      editDialog.value = true;
    }

    async function saveEdit() {
      editSaving.value = true;
      try {
        await api(`/api/admin/baselines/${editForm.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            min_score: Number(editForm.min_score),
            min_rank: Number(editForm.min_rank),
            source_url: editForm.source_url,
            source_year: Number(editForm.source_year) || null,
            reason: editForm.reason || "管理端单条修正",
          }),
        });
        ElMessage.success("已保存并留痕");
        editDialog.value = false;
        await loadBaselines();
        await loadVersions();
      } catch (e) {
        ElMessage.error(e.message);
      } finally {
        editSaving.value = false;
      }
    }

    /* ---------- 数据版本 ---------- */
    const vState = reactive({ active_year: null, versions: [], pending: { total: 0, provinces: [] } });
    const changes = ref([]);
    const checkResult = ref(null);
    const checkDialog = ref(false);
    const newYearDialog = ref(false);
    const newYearForm = reactive({ from_year: null, to_year: null, note: "" });
    const vOperating = ref(false);

    async function loadVersions() {
      const res = await api("/api/admin/versions");
      vState.active_year = res.active_year;
      vState.versions = res.versions;
      vState.pending = res.pending || { total: 0, provinces: [] };
      changes.value = res.changes || [];
      if (!baselineYear.value) baselineYear.value = res.active_year;
    }

    async function loadPending(year) {
      const res = await api(`/api/admin/versions/${year || vState.active_year}/pending`);
      vState.pending = res;
    }

    async function loadChanges() {
      const res = await api("/api/admin/changes?limit=40");
      changes.value = res.rows;
    }

    function openNewYear() {
      const years = vState.versions.map((v) => v.year);
      newYearForm.from_year = vState.active_year;
      newYearForm.to_year = (Math.max(0, ...years) || new Date().getFullYear()) + 1;
      newYearForm.note = "";
      newYearDialog.value = true;
    }

    async function cloneYear() {
      vOperating.value = true;
      try {
        const res = await api("/api/admin/versions/clone", {
          method: "POST",
          body: JSON.stringify({ from_year: Number(newYearForm.from_year),
            to_year: Number(newYearForm.to_year), note: newYearForm.note }),
        });
        ElMessage.success(`已创建 ${res.year} 年草稿（${res.version.rows} 行）`);
        newYearDialog.value = false;
        await loadVersions();
      } catch (e) {
        ElMessage.error(e.message);
      } finally {
        vOperating.value = false;
      }
    }

    async function validateYear(year) {
      vOperating.value = true;
      try {
        const res = await api(`/api/admin/versions/${year}/validate`, { method: "POST" });
        checkResult.value = res;
        checkDialog.value = true;
        if (!res.ok) ElMessage.error(`存在 ${res.errors.length} 类阻塞问题`);
        else ElMessage.success("校验通过（详见提示项）");
        await loadVersions();
      } catch (e) {
        ElMessage.error(e.message);
      } finally {
        vOperating.value = false;
      }
    }

    async function publishYear(year, force = false) {
      try {
        await ElMessageBox.confirm(
          force ? "校验未通过，确认强制发布？" : `确认将 ${year} 年发布为生效版本？`,
          "发布确认", { type: force ? "warning" : "info" });
      } catch (_) { return; }
      vOperating.value = true;
      try {
        const res = await api(`/api/admin/versions/${year}/publish`, {
          method: "POST", body: JSON.stringify({ force }),
        });
        ElMessage.success(`${year} 年已发布为生效版本`);
        await loadVersions();
        await loadOverview();
      } catch (e) {
        if (/阻塞|校验未通过/.test(e.message) && !force) {
          ElMessage.warning("校验未通过，可在核对后强制发布");
        } else {
          ElMessage.error(e.message);
        }
      } finally {
        vOperating.value = false;
      }
    }

    async function rollbackYear(year) {
      try {
        await ElMessageBox.confirm(`确认回滚到 ${year} 年数据？当前生效版本将被归档。`, "回滚确认",
          { type: "warning" });
      } catch (_) { return; }
      vOperating.value = true;
      try {
        await api(`/api/admin/versions/${year}/rollback`, { method: "POST", body: JSON.stringify({}) });
        ElMessage.success(`已回滚到 ${year} 年`);
        await loadVersions();
        await loadOverview();
      } catch (e) {
        ElMessage.error(e.message);
      } finally {
        vOperating.value = false;
      }
    }

    async function undoChange(id) {
      try {
        await ElMessageBox.confirm("确认撤销该条修改？", "撤销确认", { type: "warning" });
      } catch (_) { return; }
      try {
        await api(`/api/admin/changes/${id}/undo`, { method: "POST" });
        ElMessage.success("已撤销");
        await loadChanges();
        await loadVersions();
      } catch (e) {
        ElMessage.error(e.message);
      }
    }

    const statusTag = (s) => ({ published: "success", validated: "primary", draft: "warning",
      archived: "info" }[s] || "info");
    const statusLabel = (s) => ({ published: "生效中", validated: "已校验", draft: "草稿",
      archived: "已归档" }[s] || s);
    const actionLabel = (a) => ({ clone: "建年度", patch: "补丁", create: "补录", publish: "发布",
      rollback: "回滚", import: "导入" }[a] || a);

    /* ---------- 同步 ---------- */
    const sources = ref([]);
    const syncTargets = ref(["universities", "admission", "content"]);
    const syncForce = ref(false);
    const syncRefresh = ref(false);
    const syncing = ref(false);
    const lastSync = ref(null);
    const jobs = ref([]);
    const syncTargetsCatalog = ref({});
    const pipeTargets = computed(() =>
      Object.values(syncTargetsCatalog.value).filter((t) => t.kind === "pipeline"));

    async function loadSources() {
      const res = await api("/api/admin/sources");
      sources.value = res.files;
    }

    async function loadJobs() {
      const res = await api("/api/admin/jobs?limit=20");
      jobs.value = res.rows;
    }

    async function loadSyncTargets() {
      const res = await api("/api/admin/sync/targets");
      syncTargetsCatalog.value = res.targets || {};
    }

    async function runSync(only) {
      const targets = only || syncTargets.value;
      if (!targets.length) { ElMessage.warning("请至少选择一个同步目标"); return; }
      syncing.value = true;
      lastSync.value = null;
      try {
        const res = await api("/api/admin/sync", {
          method: "POST",
          body: JSON.stringify({ targets, force: syncForce.value, refresh: syncRefresh.value }),
        });
        lastSync.value = {
          ok: res.ok !== false,
          message: res.message || "同步完成",
        };
        if (res.ok === false) ElMessage.warning(res.message || "部分目标同步失败");
        else ElMessage.success("同步完成");
        await Promise.all([loadSources(), loadJobs(), loadSyncTargets(), loadOverview()]);
        if (page.value === "universities") loadUniversities(uniPage.value);
        if (page.value === "baselines") loadBaselines();
      } catch (e) {
        lastSync.value = { ok: false, message: e.message };
        ElMessage.error(e.message);
      } finally {
        syncing.value = false;
      }
    }

    /* ---------- 日志 ---------- */
    const events = ref([]);
    const eventStats = ref({ total: 0, today: 0, week: 0, verify: 0, search: 0 });
    const eventKind = ref("");

    async function loadEvents() {
      const qs = new URLSearchParams({ limit: "60" });
      if (eventKind.value) qs.set("kind", eventKind.value);
      const res = await api(`/api/admin/events?${qs}`);
      events.value = res.rows;
      eventStats.value = res.stats;
    }

    /* ---------- 修改密码 ---------- */
    const pwdForm = reactive({ old_password: "", new_password: "", confirm: "" });
    const pwdLoading = ref(false);

    async function changePassword() {
      if (!pwdForm.old_password || !pwdForm.new_password) { ElMessage.warning("请填写完整"); return; }
      if (pwdForm.new_password.length < 8) { ElMessage.warning("新密码至少 8 位"); return; }
      if (pwdForm.new_password !== pwdForm.confirm) { ElMessage.warning("两次输入的新密码不一致"); return; }
      pwdLoading.value = true;
      try {
        const res = await api("/api/admin/change-password", {
          method: "POST",
          body: JSON.stringify({ old_password: pwdForm.old_password, new_password: pwdForm.new_password }),
        });
        // 改密后旧令牌立即失效：后端会返回新令牌，这里直接续用，避免被踢下线
        if (res.token) {
          token.value = res.token;
          localStorage.setItem(TOKEN_KEY, res.token);
        }
        if (res.user) {
          user.value = res.user;
          localStorage.setItem(USER_KEY, JSON.stringify(res.user));
        }
        ElMessage.success(res.message || "密码已更新");
        pwdForm.old_password = pwdForm.new_password = pwdForm.confirm = "";
        await loadProfile();
      } catch (e) {
        ElMessage.error(e.message);
      } finally {
        pwdLoading.value = false;
      }
    }

    /* ---------- 院校投档线导入（D1） ---------- */
    const lineForm = reactive({
      year: new Date().getFullYear() - 1, province: "河南", subject: "物理类",
      source_url: "", mode: "merge", dry_run: true,
    });
    const lineFile = ref(null);
    const lineFileName = ref("");
    const lineReport = ref(null);
    const lineLoading = ref(false);
    const lineCoverage = ref(null);

    function onLineFileChange(file) {
      lineFile.value = file.raw || file;
      lineFileName.value = file.name || (file.raw && file.raw.name) || "";
      lineReport.value = null;
    }

    function clearLineFile() {
      lineFile.value = null;
      lineFileName.value = "";
      lineReport.value = null;
    }

    async function loadLineCoverage() {
      try {
        lineCoverage.value = await api("/api/admin/school-lines/coverage");
      } catch (_) { /* 未登录/无权限时静默 */ }
    }

    async function submitLines() {
      if (!lineFile.value) { ElMessage.warning("请先选择 CSV / XLSX 文件"); return; }
      lineLoading.value = true;
      try {
        const fd = new FormData();
        fd.append("file", lineFile.value, lineFileName.value || "upload.csv");
        fd.append("year", String(lineForm.year));
        fd.append("province", lineForm.province);
        fd.append("subject", lineForm.subject);
        fd.append("source_url", lineForm.source_url || "");
        fd.append("mode", lineForm.mode);
        fd.append("dry_run", lineForm.dry_run ? "true" : "false");
        // multipart 不能用 api()（那里写死了 JSON Content-Type）
        const res = await fetch("/api/admin/school-lines/import", {
          method: "POST",
          headers: { Authorization: `Bearer ${token.value}` },
          body: fd,
        });
        const data = await res.json().catch(() => ({}));
        if (res.status === 401) { logout(true); throw new Error(data.detail || "登录已过期"); }
        if (!res.ok) throw new Error(data.detail || `导入失败（${res.status}）`);
        lineReport.value = data;
        ElMessage.success(data.dry_run
          ? "预览完成，确认无误后关闭「仅预览」再提交"
          : `导入完成：新增 ${data.inserted} / 更新 ${data.updated} / 删除 ${data.deleted}`);
        if (!data.dry_run) await loadLineCoverage();
      } catch (e) {
        ElMessage.error(e.message);
      } finally {
        lineLoading.value = false;
      }
    }

    /* ---------- 自托管种子一键落库（S6） ---------- */
    const seedStatus = ref(null);
    const seedReport = ref(null);
    const seedLoading = ref(false);

    const seedText = computed(() => {
      const r = seedReport.value;
      if (!r) return "";
      if (r.dry_run) {
        return `可落库 ${r.estimated.available} 行（真实抓取）+ ${r.official.available} 行（官方）`;
      }
      return `新增 ${r.inserted} / 更新 ${r.updated} / 未变 ${r.unchanged}`;
    });

    async function loadSeedStatus() {
      try {
        seedStatus.value = await api("/api/admin/school-lines/seed-status");
      } catch (_) { /* 未登录/无权限时静默 */ }
    }

    async function runSeedImport() {
      seedLoading.value = true;
      try {
        const data = await api("/api/admin/school-lines/import-seed", {
          method: "POST",
          body: JSON.stringify({ dry_run: false, include: ["estimated", "official"] }),
        });
        seedReport.value = data;
        ElMessage.success(`落库完成：新增 ${data.inserted} / 更新 ${data.updated} / 未变 ${data.unchanged}`);
        await Promise.all([loadLineCoverage(), loadSeedStatus()]);
      } catch (e) {
        ElMessage.error(e.message || "落库失败");
      } finally {
        seedLoading.value = false;
      }
    }

    /* ---------- 官方逐校投档线落库（S7-A） ---------- */
    const officialStatus = ref(null);
    const officialSources = ref(null);
    const officialReport = ref(null);
    const officialLoading = ref(false);
    const officialFile = ref(null);
    const officialFileName = ref("");
    const officialForm = reactive({
      source_url: "", source_org: "", year: 2024,
      province: "", subject: "物理类", dry_run: true,
    });

    const officialText = computed(() => {
      const r = officialReport.value;
      if (!r) return "";
      const base = `可落库 ${r.accepted} 行 / 拒收 ${r.rejected} 行（共 ${r.total} 行）`;
      if (r.dry_run) return base;
      return `${base}；新增 ${r.inserted} / 更新 ${r.updated} / 未变 ${r.unchanged}`;
    });

    function onOfficialFileChange(file) {
      officialFile.value = file.raw || file;
      officialFileName.value = file.name || (file.raw && file.raw.name) || "";
      officialReport.value = null;
    }

    function clearOfficialFile() {
      officialFile.value = null;
      officialFileName.value = "";
      officialReport.value = null;
    }

    async function loadOfficialStatus() {
      try {
        officialStatus.value = await api("/api/admin/school-lines/official-status");
      } catch (_) { /* 未登录/无权限时静默 */ }
    }

    // S8-A：官方文件溯源台账（哪个文件 → 哪条链接 → 多少行）
    async function loadOfficialSources() {
      try {
        officialSources.value = await api("/api/admin/school-lines/official-sources");
      } catch (_) { /* 未登录/无权限时静默 */ }
    }

    async function submitOfficial() {
      if (!officialFile.value) { ElMessage.warning("请先选择 CSV / JSON 原表"); return; }
      if (!/^https?:\/\//.test(officialForm.source_url || "")) {
        ElMessage.warning("官方数据必须填写来源链接（省考试院原表地址）");
        return;
      }
      officialLoading.value = true;
      try {
        const fd = new FormData();
        fd.append("file", officialFile.value, officialFileName.value || "official.csv");
        fd.append("year", String(officialForm.year));
        fd.append("province", officialForm.province || "");
        fd.append("subject", officialForm.subject || "");
        fd.append("source_url", officialForm.source_url || "");
        fd.append("source_org", officialForm.source_org || "");
        fd.append("dry_run", officialForm.dry_run ? "true" : "false");
        // multipart 不能用 api()（那里写死了 JSON Content-Type）
        const res = await fetch("/api/admin/school-lines/import-official-file", {
          method: "POST",
          headers: { Authorization: `Bearer ${token.value}` },
          body: fd,
        });
        const data = await res.json().catch(() => ({}));
        if (res.status === 401) { logout(true); throw new Error(data.detail || "登录已过期"); }
        if (!res.ok) throw new Error(data.detail || `官方落库失败（${res.status}）`);
        officialReport.value = data;
        ElMessage.success(data.dry_run
          ? "预览完成；确认无误后关闭「仅预览」再提交"
          : `官方落库完成：新增 ${data.inserted} / 更新 ${data.updated}`);
        await Promise.all([loadLineCoverage(), loadSeedStatus(), loadOfficialStatus(), loadOfficialSources()]);
      } catch (e) {
        ElMessage.error(e.message);
      } finally {
        officialLoading.value = false;
      }
    }

    /* ---------- 一分一段按省同步（S11） ---------- */
    const rankProvs = ref([]);
    const rankCounts = ref(null);
    const rankSyncing = ref("");
    const rankReport = ref(null);
    const rankReportText = computed(() => {
      const r = rankReport.value;
      if (!r) return "";
      const parts = (r.years || []).map((y) => (y.ok
        ? `${y.year}：${y.rows} 行（${Object.entries(y.subjects || {}).map(([k, v]) => `${k} ${v}`).join(" / ")}）`
        : `${y.year}：${y.error}`));
      if (r.db && r.db.length) {
        parts.push("写库：" + r.db.map((d) => (d.error ? `${d.year} 失败` : `${d.year} ${d.rows} 行`)).join(" / "));
      }
      return parts.join("；") || r.error || "";
    });

    function rankTagType(status) {
      return status === "ready" ? "success" : (status === "blocked" ? "danger" : "info");
    }
    function rankStatusLabel(status) {
      return { ready: "可同步", blocked: "受阻", planned: "待接" }[status] || status;
    }

    async function loadRankProvinces() {
      try {
        const data = await api("/api/admin/rank-tables/provinces");
        rankProvs.value = data.provinces || [];
        rankCounts.value = data.counts || null;
      } catch (_) { /* 未登录/无权限时静默 */ }
    }

    async function syncProvince(row) {
      rankSyncing.value = row.province;
      rankReport.value = null;
      try {
        const data = await api("/api/admin/rank-tables/sync", {
          method: "POST",
          body: JSON.stringify({ province: row.province, dry_run: false, write_db: true }),
        });
        rankReport.value = data;
        if (data.ok) ElMessage.success(`${row.province} 同步完成：${data.saved} 个年份`);
        else ElMessage.warning(`${row.province} 同步部分失败，见下方明细`);
        await Promise.all([loadRankProvinces(), loadLineCoverage(), loadSeedStatus()]);
      } catch (e) {
        ElMessage.error(e.message || "同步失败");
      } finally {
        rankSyncing.value = "";
      }
    }

    /* ---------- 通用 ---------- */
    async function refreshAll() {
      if (!token.value) return;
      loading.value = true;
      try {
        await Promise.all([loadOverview(), loadMeta(), loadProfile()]);
        if (page.value === "universities") await loadUniversities(uniPage.value);
        if (page.value === "baselines") await loadBaselines();
        if (page.value === "versions") await loadVersions();
        if (page.value === "sync") await Promise.all([loadSources(), loadJobs(), loadSyncTargets()]);
        if (page.value === "events") await loadEvents();
      } catch (e) {
        ElMessage.error(e.message);
      } finally {
        loading.value = false;
      }
    }

    function go(key) {
      page.value = key;
      window.scrollTo({ top: 0, behavior: "smooth" });
    }

    function exportCsv(kind) {
      window.open(`/api/admin/export/${kind}.csv?token=${encodeURIComponent(token.value)}`, "_blank");
    }

    function fmtTime(iso) {
      if (!iso) return "—";
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return "—";
      const p = (n) => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
    }

    const jobTag = (s) => ({ success: "success", failed: "danger", running: "warning" }[s] || "info");
    const jobLabel = (s) => ({ success: "成功", failed: "失败", running: "进行中" }[s] || s);
    const alignLabel = (a) => ({ aligned: "观点×数据一致", caution: "需谨慎", conflict: "冲突/避坑" }[a] || a);

    watch(page, async (p) => {
      if (!token.value) return;
      try {
        if (p === "universities" && !uniRows.value.length) await loadUniversities(1);
        if (p === "baselines" && !baseRows.value.length) await loadBaselines();
        if (p === "versions") await loadVersions();
        if (p === "sync") await Promise.all([loadSources(), loadJobs(), loadSyncTargets()]);
        if (p === "lines") await Promise.all([loadLineCoverage(), loadSeedStatus(), loadOfficialStatus(), loadOfficialSources(), loadRankProvinces()]);
        if (p === "events") await loadEvents();
        if (p === "settings") await Promise.all([loadProfile(), loadDbConfig()]);
      } catch (e) {
        ElMessage.error(e.message);
      }
    });

    onMounted(async () => {
      if (token.value) await refreshAll();
    });

    return {
      token, user, profile, loginForm, loginLoading, loading, page, navItems,
      currentTitle, currentDesc, overview, meta, kpiCards,
      doLogin, logout, onUserCommand, refreshAll, go,
      uniFilters, uniRows, uniTotal, uniPage, uniPages, uniPageSize, uniLoading,
      loadUniversities, resetUniFilters,
      baseFilters, baseRows, baseLoading, baseOfficialCount, loadBaselines, baselineYear,
      editDialog, editSaving, editForm, openEdit, saveEdit,
      vState, changes, checkResult, checkDialog, newYearDialog, newYearForm, vOperating,
      loadVersions, loadPending, loadChanges, openNewYear, cloneYear, validateYear,
      publishYear, rollbackYear, undoChange, statusTag, statusLabel, actionLabel,
      sources, syncTargets, syncForce, syncRefresh, syncing, lastSync, jobs,
      syncTargetsCatalog, pipeTargets, loadSources, loadJobs, loadSyncTargets, runSync,
      events, eventStats, eventKind, loadEvents,
      lineForm, lineFile, lineFileName, lineReport, lineLoading, lineCoverage,
      onLineFileChange, clearLineFile, submitLines, loadLineCoverage,
      seedStatus, seedReport, seedLoading, seedText, loadSeedStatus, runSeedImport,
      officialStatus, officialReport, officialLoading, officialForm, officialFileName,
      officialText, onOfficialFileChange, clearOfficialFile, submitOfficial, loadOfficialStatus,
      officialSources, loadOfficialSources,
      rankProvs, rankCounts, rankSyncing, rankReport, rankReportText,
      loadRankProvinces, syncProvince, rankTagType, rankStatusLabel,
      pwdForm, pwdLoading, changePassword,
      dbState, dbForm, dbDialects, dbResult, dbResultTitle, dbTesting, dbApplying, dbResetting,
      loadDbConfig, onDialectChange, testDb, applyDb, resetDb,
      exportCsv, fmtTime, jobTag, jobLabel, alignLabel,
    };
  },
});

app.use(ElementPlus);
app.mount("#app");
