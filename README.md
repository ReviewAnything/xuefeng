# 志愿决策助手 v2 · 跨端应用（uni-app + Python）

把张雪峰「普通家庭 + 就业导向」的务实框架，与开源社区资源结合的**志愿决策助手**。
v2 在 v1 纯前端 PWA 基础上做了两件事：

1. **架构重构**：前端用 **uni-app (Vue3)** 实现一套代码跨 H5 / 微信小程序 / App；后端引入 **Python FastAPI** 承载数据层。
2. **完成 P2（观点 × 数据 交叉核验）**：定性观点（推荐/慎选/避坑）与定量录取数据（位次 / 冲稳保）做一致性校验，强化偏见校正。

> 内容来源：张雪峰公开观点（社区整理）+ 开源资源核实。**仅供学习参考，正式填报以各省考试院官方数据为准。**

---

## 一、目录结构

```
zhiyuan-app-v2/
├── shared/
│   └── content.json          # 单一数据源：majors / resources / questions / 版本（前端与后端共用）
├── backend/                  # Python FastAPI 后端（P2 数据层）
│   ├── main.py               # 路由与 API（/api/health, /api/majors, /api/verify, /api/admission/search ...）
│   ├── services/
│   │   ├── content.py        # 读取 shared/content.json
│   │   ├── admission.py      # 录取位次模型 + 冲稳保 + 真实/样例基线自动切换
│   │   └── verify.py         # P2 核心：观点×数据 交叉核验
│   ├── scripts/
│   │   ├── ingest_gaokao_advisor.py       # 由 gaokao-advisor 生成 31 省真实录取基线
│   │   └── build_universities_national.py # 由教育部官方 xls 生成全国院校总表
│   ├── data/
│   │   ├── admission_real_baseline.json  # 真实基线（31 省，脚本生成，后端优先使用）
│   │   ├── admission_official_2024.json  # 6 省官方省控线 + 985/211 入门投档位次
│   │   ├── universities_national.json    # 全国普通高校静态总表（2868 所）
│   │   ├── universities.json             # 985/211 权威清单（112 所，含门类/官网）
│   │   ├── SOURCES.md                    # 录取数据来源与置信度
│   │   └── admission_sample.json         # 参数化样例录取数据（演示/fallback，非官方）
│   ├── tests/test_api.py     # 后端测试（pytest + TestClient）
│   └── requirements.txt
├── frontend/                 # uni-app (Vue3) 前端
│   ├── src/
│   │   ├── pages/            # diagnose 诊断 / majors 专业 / verify 核验(P2) / resources 资源 / about 关于
│   │   ├── utils/
│   │   │   ├── content.js    # 引入 shared/content.json
│   │   │   ├── engine.js     # 决策引擎（纯函数，可 Node 单测）
│   │   │   └── api.js        # 调用 Python 后端
│   │   ├── pages.json        # 路由 + tabBar 跨端导航
│   │   ├── manifest.json     # 多端 manifest
│   │   └── App.vue / main.js / uni.scss
│   ├── tests/engine.test.mjs # 前端引擎单测（零依赖）
│   ├── vite.config.js        # 含 @shared 别名（前后端共用数据源）
│   └── package.json
└── README.md
```

## 二、五大模块

| 模块 | 功能 | 跨端 / 后端 |
|---|---|---|
| **① 自我诊断画布** | 灵魂八连问 → 透明规则生成决策框架（策略 + 方向清单 + 偏见校正 + 避坑 + 下一步），不下录取结论 | uni-app |
| **② 专业图谱库** | 38 个专业，每条含张雪峰观点 + 理由 + 偏见校正层 + 数据核验入口 | uni-app（离线读本地数据） |
| **③ 观点×数据核验（P2）** | 输入省份/科类/位次/专业 → 后端返回 各批次门槛 + 冲稳保 + 一致性结论（一致/需谨慎/冲突） | **uni-app + Python** |
| **④ 开源资源中心** | 10 个真实仓库，按「思想/语料」「数据/工具」筛选，直达 GitHub / 在线体验 | uni-app |
| **⑤ 关于** | 架构说明 + 五个方向落地 + 免责声明 | uni-app |

## 三、运行方式

### 1) 后端（Python，必需：P2 数据层）
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
# 接口文档：http://localhost:8000/docs
```

### 2) 前端（uni-app，任选目标端）
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

### 3) 单一数据源
`shared/content.json` 同时被 `frontend/src/utils/content.js`（vite `@shared` 别名）和
`backend/services/content.py` 读取。**年度更新只改这一个文件并 bump `APP_VERSION`。**

## 四、本地测试

```bash
# 后端：pytest（FastAPI TestClient，无需起服务）
cd backend && pip install -r requirements.txt pytest && pytest -q
# 期望：8 passed

# 前端：决策引擎单测（零依赖 Node ESM）
cd frontend && node tests/engine.test.mjs
# 期望：8 通过 / 0 失败
```

## 五、P2 交叉核验逻辑

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

### 官方省控线覆盖层（6 省，2024）

在估算基线之上，仓库额外内置 `backend/data/admission_official_2024.json`：**河南/广东/四川/山东/河北/江苏**
的 **批次线**（普通一本/普通二本/专科）已替换为 2024 年各省教育考试院**官方录取控制分数线 + 官方一分一段表对应位次**。
后端 `admission.py` 自动优先采用官方批次线（接口逐层标注 `data_source: official`），并进一步接入 **6 省 985/211 真实入门投档位次**
（同样标注 `official`）：985/211 阈值不再用估算，而是各省发布的 2024 最低投档线及位次（普通类本科批），未覆盖的 25 省仍标注 `estimated`。
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

## 六、技术要点

- **跨端**：uni-app Vue3 + Vite，`pages.json` tabBar 一套代码出 H5/小程序/App。
- **前后端分离 + 单数据源**：内容零重复，避免"第十一个仓库"式同质化。
- **偏见校准层**：每个专业带反方/长期主义/官方评估提示；诊断与核验均动态提示框架边界。
- **隐私**：诊断输入仅存端侧 `uni.storage`，可导出；核验联机但只传省份/科类/位次/专业名，无个人身份信息。
- **P2 数据可插拔**：样例数据演示，真实数据一行 CSV 切换。

## 七、已知边界

- 录取数据：河南/广东/四川/山东/河北/江苏 的**批次线**与 **985/211 入门投档位次**均已用 2024 官方数据（高置信）；其余 25 省仍为 gaokao-advisor 参数推算（标注 estimated），**非官方数据**；正式填报以各省考试院为准（逐省来源见 `backend/data/SOURCES.md`）。
- 院校清单：全国 2868 所普通高校为教育部官方静态名单；军校不列入（故 985 计 38）；**不含逐年录取分数**。
- 观点侧截至公开整理时点，需年度滚动更新（见"单一数据源"）。
- 微信小程序端联调后端需配置 HTTPS 合法域名。
