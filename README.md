# 志愿决策助手 v2 · 跨端应用（uni-app + Python）

把张雪峰「普通家庭 + 就业导向」的务实框架，与开源社区资源结合的**志愿决策助手**。
v2 在 v1 纯前端 PWA 基础上做了三件事：

1. **架构重构**：前端用 **uni-app (Vue3)** 实现一套代码跨 H5 / 微信小程序 / App；后端引入 **Python FastAPI** 承载数据层。
2. **完成 P2（观点 × 数据 交叉核验）**：定性观点（推荐/慎选/避坑）与定量录取数据（位次 / 冲稳保）做一致性校验，强化偏见校正。
3. **数据落库 + 运营管理端**：2868 所院校与 31 省录取基线落 SQLite（可切 PostgreSQL），提供 `/admin` 数据看板、数据浏览、同步与导出。

> 内容来源：公开观点（社区整理）+ 开源资源核实 + 各省考试院公开数据。**仅供学习参考，正式填报以各省考试院官方数据为准。**

---

## 一、目录结构

```
zhiyuan-app-v2/
├── docs/
│   └── data-management.md     # 后端数据管理方案（数据分层 / 年度更新 SOP / 校验规则）
├── shared/
│   └── content.json          # 单一数据源：majors / resources / questions / 版本 / CONTENT_SOURCE（前端与后端共用）
├── backend/                  # Python FastAPI 后端（P2 数据层 + 管理端 API）
│   ├── main.py               # 路由与 API（health / content / majors / verify / verify/batch / admission / universities / admin）
│   ├── db/                   # 数据落库层（SQLAlchemy）
│   │   ├── database.py       # 引擎/会话（默认 SQLite，可切 PostgreSQL）
│   │   ├── models.py         # 院校 / 录取基线 / 精英院校 / 内容 / 查询事件 / 同步任务 / 管理员
│   │   ├── seed.py           # JSON → DB 幂等播种（SHA-256 签名，未变则跳过）
│   │   └── repository.py     # 业务查询 + 短 TTL 缓存
│   ├── routers/
│   │   └── admin.py          # /api/admin/* 登录、看板、浏览、同步、导出
│   ├── services/
│   │   ├── content.py        # 读取 shared/content.json
│   │   ├── admission.py      # 录取位次模型（DB 优先、JSON 兜底）+ 冲稳保
│   │   ├── verify.py         # P2 核心：观点×数据 交叉核验（含批量 verify_many）
│   │   └── admin_auth.py     # PBKDF2 密码 + HMAC 令牌
│   ├── admin/                # 管理端控制台（Vue3 + Element Plus，免构建）
│   │   ├── index.html / app.js / styles.css
│   │   └── vendor/           # 本地化 vue / element-plus（不依赖 CDN）
│   ├── services/
│   │   └── data_versions.py   # 数据版本：年度更新 / 补丁 / 校验 / 发布 / 回滚 / 审计
│   ├── scripts/
│   │   ├── ingest_gaokao_advisor.py       # 由 gaokao-advisor 生成 31 省真实录取基线
│   │   ├── build_universities_national.py # 由教育部官方 xls 生成全国院校总表
│   │   └── manage_data.py                 # 数据管理 CLI（年度更新 / 补丁 / 发布 / 回滚）
│   ├── data/
│   │   ├── admission_real_baseline.json  # 真实基线（31 省，脚本生成）
│   │   ├── admission_official_2024.json  # 11 省官方省控线 + 6 省 985/211 入门投档位次
│   │   ├── universities_national.json    # 全国普通高校静态总表（2868 所）
│   │   ├── universities.json             # 985/211 权威清单（112 所，含门类/官网）
│   │   ├── xuefeng.db                    # SQLite 数据库（运行时生成，已 gitignore）
│   │   ├── SOURCES.md                    # 录取数据来源与置信度
│   │   └── admission_sample.json         # 参数化样例录取数据（演示/fallback，非官方）
│   ├── tests/                # pytest：API / 落库 / 管理端
│   └── requirements.txt
├── frontend/                 # uni-app (Vue3) + wot-design-uni
│   ├── src/
│   │   ├── pages/            # diagnose 诊断 / majors 专业 / verify 核验(P2) / resources 资源 / about 关于
│   │   ├── utils/
│   │   │   ├── content.js    # 引入 shared/content.json
│   │   │   ├── engine.js     # 决策引擎（纯函数，可 Node 单测）
│   │   │   ├── theme.js      # wot-design-uni 深色主题 token
│   │   │   └── api.js        # 调用 Python 后端
│   │   ├── pages.json        # 路由 + tabBar + wot easycom
│   │   ├── manifest.json     # 多端 manifest
│   │   └── App.vue / main.js / uni.scss
│   ├── tests/
│   │   ├── engine.test.mjs    # 前端引擎单测（零依赖）
│   │   └── template.test.mjs  # SFC 模板编译校验（零依赖，复用管理端 vendor 的 Vue）
│   ├── vite.config.js        # 含 @shared 别名（前后端共用数据源）
│   └── package.json
└── README.md
```

## 二、功能模块

| 模块 | 功能 | 跨端 / 后端 |
|---|---|---|
| **① 自我诊断画布** | 灵魂八连问 → 透明规则生成决策框架（策略 + 方向清单 + 偏见校正 + 避坑 + 下一步），不下录取结论 | uni-app |
| **② 专业图谱库** | 38 个专业，每条含张雪峰观点 + 理由 + 偏见校正层 + 数据核验入口 + **内容可溯**（source_year / source_note） | uni-app（离线读本地数据） |
| **③ 观点×数据核验（P2）** | 输入省份/科类/位次/专业 → 后端返回 各批次门槛 + 冲稳保 + 一致性结论（一致/需谨慎/冲突）；支持**批量核验**（诊断画布的推荐方向一次算完，按「冲突→需谨慎→一致」排序） | **uni-app + Python** |
| **④ 开源资源中心** | 10 个真实仓库，按「思想/语料」「数据/工具」筛选，直达 GitHub / 在线体验 | uni-app |
| **⑤ 关于** | 架构说明 + 五个方向落地 + 免责声明 | uni-app |
| **⑥ 等位分换算（C2）** | 分数 ⇄ 位次跨年换算：今年 600 分相当于去年多少分？支持 rank / percentile 两法，附锚点表与外推提示 | **Python + uni-app** |
| **⑦ 院校推荐（A3）** | 按位次给出 985/211/普通本科/专科 各层次的 冲/稳/保 判定 + 教育部 2868 所名单的院校池 | **Python + uni-app** |
| **⑧ 志愿表草稿（C3）** | 冲/稳/保 三档成表，可填拟报专业 → H5 打印/另存为 PDF，或复制为文本（仅存本机） | uni-app |
| **⑨ 院校专业组（P4）** | 新高考志愿单元：按「专业选科要求 × 院校类别专业池」推导专业组，标注可报/不可报；规则估算，非官方分组 | **Python + uni-app** |

### 公开 API（摘要）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 + 数据源 + CORS 白名单 |
| GET | `/api/content` | 单一数据源（版本/问卷/专业/资源） |
| GET | `/api/admission/search` | 按位次筛 冲/稳/保 可达专业 |
| GET | `/api/universities` | 全国 2868 所院校静态表 |
| POST | `/api/verify` | 观点×数据交叉核验 |
| POST | `/api/verify/batch` | 批量核验（最多 20 个专业） |
| GET | `/api/equiv/years` | 等位分：可用年份与数据源 |
| GET | `/api/equiv/curve` | 等位分：某年位次→分数锚点曲线 |
| GET | `/api/equiv/convert` | 等位分：跨年分数/位次换算（rank / percentile） |
| GET | `/api/recommend/schools` | 院校推荐：冲/稳/保 院校池（A3） |
| GET | `/api/major-groups/universities` | 院校选择器（省/层次/985·211/关键字） |
| GET | `/api/major-groups` | 院校专业组推导（P4，规则估算） |

## 三、运行方式

### 1) 后端（Python，必需：P2 数据层 + 管理端）
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
# 接口文档：http://localhost:8000/docs
# 管理端：  http://localhost:8000/admin
```
首次启动会自动建表并播种（2868 所院校 + 280 行录取基线 + 38 专业），耗时约 5–10 秒；之后按文件签名跳过。

### 2) 管理端（数据看板 / 数据版本 / 数据同步 / 院校库）
浏览器打开 `http://localhost:8000/admin`。
- 初始账号：`admin` / `xuefeng@2026`（可用 `XUEFENG_ADMIN_USER` / `XUEFENG_ADMIN_PASSWORD` 覆盖）
- **首次登录请立即在「系统设置」修改密码**；管理端会持续提示未改密状态。
- 功能：数据看板（院校/基线/查询趋势/健康检查）、**数据版本（年度更新：建草稿→校验→发布→回滚）**、
  院校库检索与 CSV 导出、录取基线浏览与单条修正、数据同步（含外部数据源管道与任务记录）、查询日志、账号安全。

### 3) 前端（uni-app，任选目标端）
```bash
cd frontend
npm install
npm run dev:h5          # 浏览器预览（默认 http://localhost:5173）
npm run build:h5        # 产出 H5 静态包（dist）
npm run dev:mp-weixin   # 微信小程序（用微信开发者工具打开 frontend/dist/dev/mp-weixin）
npm run build:app       # App 包（需 HBuilderX / 云端打包）
```
> 前端通过 `src/utils/api.js` 的 `API_BASE` 调用后端。本地 H5 默认 `http://localhost:8000`。
> 生产/小程序请改为你的后端域名（HTTPS + 小程序后台配置 request 合法域名）。

### 4) 单一数据源
`shared/content.json` 同时被 `frontend/src/utils/content.js`（vite `@shared` 别名）和
`backend/services/content.py` 读取。**年度更新只改这一个文件并 bump `APP_VERSION`**，
再在管理端点「数据同步 → 内容数据」即写入数据库。

### 4.1) P1 → P2 一键批量核验

诊断画布算出的推荐方向，可一键带入核验页批量计算，不再逐个手填：

1. 诊断页填好省份 / 科类 / 位次 → 生成决策画布；
2. 点「**批量核验全部 N 个方向**」（画布结果写入端侧 `zhiyuan_canvas_v2`，仅存本机）；
3. 核验页自动进入批量模式，可增删待核验专业 → `POST /api/verify/batch` 一次算完；
4. 结果按 **冲突 → 需谨慎 → 一致** 排序，先看风险项；点任一条展开完整核验详情。

```bash
curl -X POST http://localhost:8000/api/verify/batch -H 'Content-Type: application/json' \
  -d '{"province":"河南","subject":"物理类","user_rank":40000,
       "major_names":["计算机科学与技术","临床医学","法学","土木工程"]}'
# → {count, summary:{aligned,caution,conflict}, results:[...], unknown:[...]}
```

单次最多 20 个专业；未收录的专业放进 `unknown` 而不失败。**入口校验**：位次必须是 1 ~ 2,000,000 的整数
（早期只判 >0，位次填 0 会被误判成「保」）。

### 4.2) 内容可溯

`shared/content.json` 新增 `CONTENT_SOURCE`（观点依据 / 数据依据 / 整理年份 / 口径提示），
38 个专业逐个带 `source_year`（观点整理年份）与 `source_note`（该大类证据口径），
专业图谱页与「关于」页可见；`/api/content` 一并返回 `content_source`。

### 5) 数据版本与年度更新
录取基线以「年份」为版本：多年数据并存，只有**生效版本**对外提供服务。完整方案见
[`docs/data-management.md`](docs/data-management.md)。

```bash
cd backend
python scripts/manage_data.py status                       # 版本总览
python scripts/manage_data.py new-year --from 2026 --to 2027  # 建新年度草稿（沿用行自动标记）
python scripts/manage_data.py pending 2027                  # 待更新清单
python scripts/manage_data.py patch --year 2027 --province 河南 --subject 物理类 \
    --tier 普通一本 --min-rank 150000 --min-score 520 --source-url https://... --operator alice
python scripts/manage_data.py validate 2027                 # 校验（有阻塞问题则退出码 1）
python scripts/manage_data.py publish  2027 --operator alice # 发布为生效版本
python scripts/manage_data.py rollback 2026                 # 回滚到历史版本
```

管理端「数据版本」页提供同样的能力（建年度 / 校验 / 发布 / 回滚 / 待更新清单 / 变更审计 / 撤销）。

### 6) 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `XUEFENG_DB_PATH` | `backend/data/xuefeng.db` | SQLite 文件路径 |
| `XUEFENG_DATABASE_URL` | — | 完整 SQLAlchemy URL，设置后优先（如 `postgresql+psycopg://...`） |
| `XUEFENG_ADMIN_USER` | `admin` | 初始管理员账号（仅首次建库生效） |
| `XUEFENG_ADMIN_PASSWORD` | `xuefeng@2026` | 初始管理员密码（仅首次建库生效） |
| `XUEFENG_AUTH_SECRET` | 自动生成并存入 DB | 令牌签名密钥，多实例部署时应固定 |
| `XUEFENG_TOKEN_TTL` | `43200` | 管理端登录有效期（秒） |
| `XUEFENG_CORS_ORIGINS` | 本地开发端口白名单 | 逗号分隔的允许来源；设为 `*` 恢复全开（**生产环境请显式配置**） |

## 四、本地测试

```bash
# 后端：pytest（FastAPI TestClient，无需起服务）
cd backend && pip install -r requirements.txt pytest && pytest -q
# 期望：45 passed（API / 落库 / 管理端 / 数据版本 / 批量核验 / 输入校验 / CORS / 内容可溯）

# 前端：决策引擎单测 + SFC 模板编译校验（均零依赖，无需 npm install）
cd frontend && node tests/engine.test.mjs && node tests/template.test.mjs
# 期望：8 通过 / 0 失败；模板 6 通过 / 0 失败（复用管理端 vendor 的 Vue 编译器在 Node 内编译）
```

## 五、数据落库与管理端

### 1) 为什么要落库
此前录取基线/院校清单是「每次请求读 JSON」，无法支撑筛选、分页、统计与运营。现在统一落库：

| 表 | 内容 | 规模 |
|---|---|---|
| `universities` | 教育部全国普通高校 | 2868 |
| `elite_universities` | 985/211 权威清单（含军校） | 112 |
| `admission_baselines` | (省, 科类, 批次) 录取门槛，官方值已合并 | 280 行（官方 48） |
| `majors` / `resources` | 专业图谱 / 开源资源 | 38 / 10 |
| `query_events` | 匿名查询事件（省/科类/位次/结论） | 持续增长 |
| `sync_jobs` | 同步任务与结果 | 持续增长 |
| `admin_users` / `settings` | 管理员（PBKDF2）与配置 | — |

设计要点：
- **幂等播种**：`db/seed.py` 以源文件 SHA-256 为签名，未变化则跳过；重复同步只 upsert，不产生重复行。
- **单一事实源**：官方省控线/985·211 入门位次在播种时**合并进同一行**并标注 `data_source=official`，查询侧不再分支。
- **DB 优先、JSON 兜底**：`services/admission.py` 优先查库；数据库不可用时自动回落 JSON，服务不中断。
- **短 TTL 缓存**：录取基线缓存 30s，院校计数缓存 60s；管理端同步后立即失效。
- **可切 PostgreSQL**：设置 `XUEFENG_DATABASE_URL` 即可，无需改代码。

### 2) 管理端能力
- **登录鉴权**：PBKDF2-HMAC-SHA256（20 万次）+ HMAC-SHA256 签名令牌（默认 12h），无第三方 JWT 依赖。
- **数据看板**：院校/985·211/基线/今日查询 4 张 KPI、14 天查询趋势、层次分布、省份 Top10、数据健康检查、最近同步。
- **院校库**：按省/层次/性质/校名筛选 + 分页 + CSV 导出（带 BOM，Excel 直接打开）。
- **录取基线**：逐行查看分数/位次/来源，官方与估算用徽标区分，可导出。
- **数据同步**：展示 5 个数据源文件的条数/大小/更新时间；选择目标（院校/录取/内容）+ 可选「强制重灌」「拉取上游最新」；
  另有「外部数据源管道」：一键重跑 `ingest_gaokao_advisor.py` / `build_universities_national.py` 重新生成 L1 静态数据并自动播种。
  同步按目标逐个写入 `sync_jobs`（状态/行数/耗时/操作人），可在「同步历史」回看。
- **查询日志**：核验/检索的匿名片省、科类、位次、结论，用于产品分析。
- **系统设置**：修改密码、运行环境、数据规模。

管理端为 **Vue 3 + Element Plus** 的免构建 SPA，`vendor/` 内已本地化依赖，部署不依赖 CDN。

### 3) 管理端 API（摘要）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/admin/login` | 登录，返回 Bearer token |
| GET | `/api/admin/overview` | 看板数据（KPI/趋势/分布/健康检查） |
| GET | `/api/admin/universities` | 院校分页检索 |
| GET | `/api/admin/baselines` | 录取基线 |
| GET | `/api/admin/sources` | 数据源文件状态 + 待同步项 |
| POST | `/api/admin/sync` | 执行同步（记录 SyncJob） |
| GET | `/api/admin/events` | 查询日志 |
| GET | `/api/admin/export/*.csv` | 导出院校/基线 |
| POST | `/api/admin/change-password` | 修改密码 |

## 六、P2 交叉核验逻辑

`/api/verify` 把专业 `view`（recommend/caution/avoid）与用户位次可达批次做一致性判定：

- **aligned（一致）**：推荐专业且能摸到较优质批次 → 可作重点候选。
- **caution（需谨慎）**：推荐但只能摸到低位次批次（普通二本/专科）→ 提示原 bias 风险被放大；或避坑专业但能摸到较好批次 → 仅在满足例外条件时考虑。
- **conflict（冲突）**：避坑专业却正好落在低位次批次 → 建议坚决规避；或专业在所有批次都够不到 → 提示不可及。

录取门槛默认由 `backend/data/admission_real_baseline.json`（已覆盖 **31 省**，由 ingestion 脚本基于 [chenxuyaun/gaokao-advisor](https://github.com/chenxuyaun/gaokao-advisor) 生成）给出，回退到 `admission_sample.json` 样例；两者结构一致，均为「省份×科类×批次基线 + 专业难度系数」。

### 接入真实录取数据（可插拔，已默认开启）

仓库已内置由 [chenxuyaun/gaokao-advisor](https://github.com/chenxuyaun/gaokao-advisor)（MIT）生成的
`backend/data/admission_real_baseline.json`，**覆盖全国 31 省**，后端自动优先使用（`/api/health` 可见 `admission_data_source: "real"`）。

如需重新生成 / 拉取最新参数：

```bash
cd backend
python scripts/ingest_gaokao_advisor.py            # 用内置参数生成（离线）
python scripts/ingest_gaokao_advisor.py --sync     # 先拉取 gaokao-advisor 最新参数再生成
```

脚本复用 gaokao-advisor 的「31 省一分一段表 + 院校层次」确定性参数，计算各省各批次录取门槛，
写出与 `admission_sample.json` 同构的基线文件；删除该文件即回退到样例数据。
> 说明：位次门槛为模型推算；分数为锚点区间插值、区间外按斜率外推（顶尖/末端为估算），专科为估算值。

### 官方省控线覆盖层（11 省，2024）

在估算基线之上，仓库额外内置 `backend/data/admission_official_2024.json`：**河南/四川/山东/广东/江苏/河北/安徽/湖南/湖北/福建/重庆**
的 **批次线**（普通一本/普通二本/专科）已替换为 2024 年各省教育考试院**官方录取控制分数线 + 官方一分一段表对应位次**。
合并本科批的新高考省统一口径：**普通一本 ← 特殊类型招生控制线（特招线，≈原一本线）**，**普通二本 ← 本科批线**，专科 ← 专科批线；
河南/四川沿用本科一批/二批口径，山东为一段线/二段线。
后端 `admission.py` 自动优先采用官方批次线（接口逐层标注 `data_source: official`），并进一步接入 **6 省 985/211 真实入门投档位次**
（同样标注 `official`）：985/211 阈值不再用估算，而是各省发布的 2024 最低投档线及位次（普通类本科批），未覆盖的省份仍标注 `estimated`。
`/api/health` 的 `admission_data_source` 为 `official_overlay`，并新增 `official_provinces` 字段。

- 逐省来源、位次与置信度见 `backend/data/SOURCES.md`。
- 官方口径为 2024 年；新高考改革省份逐年微调，使用时应以当年省考试院公布数据为准。

### 全国普通高等学校静态总表（2868 所）

仓库内置两份院校数据，均来自教育部官方名单，**权威、静态、可离线**：

- `backend/data/universities_national.json`：**教育部《全国普通高等学校名单》（截至 2024-06-20）全部 2868 所**
  （本科 1308 + 高职专科 1560，31 省全覆盖）。每所带 `省份/城市/办学层次(本科|专科)/办学性质(公办|民办|中外合作办学)/
  主管部门/学校标识码/is_985/is_211/is_dfc` 等静态属性。
- `backend/data/universities.json`：教育部「211 工程」全部 112 所（含 39 所 985），带 `门类/主管单位/官网` 等更细属性，
  用于核验页按层次展示可触及院校。

**接口**：
- `GET /api/universities`：可按 `province` / `level(本科|专科)` / `tier(985|211|dfc)` / `category` / `q(校名)` 筛选，
  返回 `total`、`count_benke`、`count_zhuanke`、`count_985`（38，教育部名单不含军校）、`count_211`（112）。
- `GET /api/verify` 仍返回用户位次**可触及层次**的 985/211 院校清单（`reachable_tier` / `reachable_tier_schools`）。

**构建脚本**：`python scripts/build_universities_national.py --xls 名单.xls`（不传 `--xls` 则自动下载教育部官方 xls）。
> 说明：军校（国防科技大学、海军/空军军医大学等）不列入教育部「普通高等学校」名单，故 985 计 38、211 计 112；
> 清单为院校元数据，**不含逐年录取分数**，具体以各校招生网/考试院为准。

## 七、技术要点

- **UI 组件库（客户端）**：选用 **wot-design-uni**（Vue3 原生、uni-app 跨端、70+ 组件、按需 easycom、支持深色主题变量）。
  五个页面统一使用 `wd-config-provider` + `theme.js` 品牌 token；表单/选择器/标签/折叠面板/搜索/Toast 均来自组件库，
  不再手写原生控件样式。
- **UI 组件库（管理端）**：**Element Plus**（Vue3 生态最成熟的桌面端组件库），本地 vendor 免构建、免 CDN。
- **跨端**：uni-app Vue3 + Vite，`pages.json` tabBar 一套代码出 H5/小程序/App。
- **前后端分离 + 单数据源**：内容零重复，避免"第十一个仓库"式同质化。
- **偏见校准层**：每个专业带反方/长期主义/官方评估提示；诊断与核验均动态提示框架边界。
- **隐私**：诊断输入仅存端侧 `uni.storage`，可导出；核验联机但只传省份/科类/位次/专业名，无个人身份信息。
- **数据可插拔**：JSON 静态数据为源，数据库为运行时事实源；同步幂等、可回放。

## 八、已知边界

- 录取数据：**11 省**（河南/四川/山东/广东/江苏/河北/安徽/湖南/湖北/福建/重庆）的**批次线**与 **6 省 985/211 入门投档位次**均已用 2024 官方数据（高置信）；其余省份仍为 gaokao-advisor 参数推算（标注 estimated），**非官方数据**；正式填报以各省考试院为准（逐省来源见 `backend/data/SOURCES.md`）。
- 院校清单：全国 2868 所普通高校为教育部官方静态名单；军校不列入（故 985 计 38）；**不含逐年录取分数**。
- **院校专业组（P4）**：为规则推导（专业选科要求 × 院校类别专业池），**非各省考试院官方专业组划分**；同一院校在不同省份的专业组可能不同，本模型未区分省份，仅用于结构演示。
- 观点侧截至公开整理时点，需年度滚动更新（见"单一数据源"）。
- 微信小程序端联调后端需配置 HTTPS 合法域名；H5 公开 demo 部署见 `docs/deployment.md`。
