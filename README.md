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
│   │   ├── admission.py      # 录取位次模型 + 冲稳保 + 真实数据可插拔
│   │   └── verify.py         # P2 核心：观点×数据 交叉核验
│   ├── data/
│   │   └── admission_sample.json   # 参数化样例录取数据（演示用，非官方）
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

录取门槛由 `backend/data/admission_sample.json` 的参数化模型给出（省份×科类×批次基线 + 专业难度系数）。

### 接入真实录取数据（可插拔）
把 `chenxuyaun/gaokao-advisor` 导出的 CSV 放到 `backend/data/gaokao_advisor.csv`，
列：`province,subject,tier,school,major,min_score,min_rank`。服务会自动从 sample 切换为 real（`/api/health` 可见 `admission_data_source`）。

## 六、技术要点

- **跨端**：uni-app Vue3 + Vite，`pages.json` tabBar 一套代码出 H5/小程序/App。
- **前后端分离 + 单数据源**：内容零重复，避免"第十一个仓库"式同质化。
- **偏见校准层**：每个专业带反方/长期主义/官方评估提示；诊断与核验均动态提示框架边界。
- **隐私**：诊断输入仅存端侧 `uni.storage`，可导出；核验联机但只传省份/科类/位次/专业名，无个人身份信息。
- **P2 数据可插拔**：样例数据演示，真实数据一行 CSV 切换。

## 七、已知边界

- 样例录取数据为参数化估算（演示），**非官方数据**；正式填报以各省考试院为准。
- 观点侧截至公开整理时点，需年度滚动更新（见"单一数据源"）。
- 微信小程序端联调后端需配置 HTTPS 合法域名。
