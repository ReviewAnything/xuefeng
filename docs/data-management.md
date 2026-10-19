# 后端数据管理方案（Data Management v1）

> 目标：让「年份」成为系统的一等公民——多年数据可并存、可校验、可发布、可回滚，
> 年度更新不再是一次性覆盖式改库，而是一条有审批、有留痕、有回退的流水线。

---

## 1. 现状与问题

改造前 `admission_baselines` 的唯一键是 `(province, subject, tier)`：

| 问题 | 后果 |
| --- | --- |
| 年份只是普通字段，不是主键的一部分 | 2024/2025/2026 无法共存，年度更新只能覆盖 |
| 覆盖即生效 | 改错一个数就直接影响线上，无法回退 |
| 无草稿态 | 更新过程中处于「半成品」，对外同样可见 |
| 无审计 | 谁在什么时候把河南/物理类/一本从 13 万改到 15 万，不可追溯 |
| 官方线与估算线混在一起 | 无法回答「哪些行还是沿用往年的旧官方线」 |

## 2. 数据分层

```
L0 原始源 raw/       官方 xls / pdf / 网页快照 + 抓取时间 + 来源 URL      （只读存档，不参与服务）
   ↓ 解析脚本 scripts/ingest_*.py
L1 结构化 staging/   backend/data/*.json（人工核对后可 diff、可 review）
   ↓ 播种 db/seed.py（源文件 SHA-256 幂等）
L2 服务层 serving/   SQLite/PostgreSQL：admission_baselines（按 year 分版本）
   ↓ 版本发布 services/data_versions.py
对外 API             只读取「当前生效年份」settings.data_active_year
```

- **L0 必须留档**：任何官方数据先落 `backend/data/raw/<year>/`，命名 `来源_省份_批次_年份.ext`；
- **L1 是唯一需要 code review 的数据**：JSON 里必须带 `meta.year / meta.sources / meta.coverage`；
- **L2 不再手工改**：一切变更走「补丁 / 发布 / 回滚」API 或 CLI，自动留痕。

## 3. 年份的两个语义

同一行数据有两个年份，必须分开存：

| 字段 | 含义 | 例子 |
| --- | --- | --- |
| `year` | **版本年份**：这行属于哪个年度的数据集 | 2026 |
| `source_year` | **出处年份**：这个数值的真实发布年份 | 2024（沿用 2024 官方省控线） |
| `carried` | 是否沿用往年（`source_year < year` 自动置位） | True → 管理端标记「待更新」 |

这样管理端可以精确回答：*2026 版本里还有多少行用的是 2024 的官方线？*

## 4. 版本模型与生命周期

`data_versions` 表：一个 `(dataset, year)` 一条记录。

```
   clone/import          validate            publish
      ───────▶ draft ──────────▶ validated ──────────▶ published
                  ▲                                        │
                  │        补丁（revision+1）               │ 新版本发布
                  └────────────────────────────────────────┴──▶ archived
                                    rollback 可把任意历史版本重新置为 published
```

- `dataset`：`admission`（录取基线）/ `universities`（院校总表）/ `content`（专业与资源）；
- `status`：`draft` → `validated` → `published` → `archived`；
- `revision`：每次补丁自增，用于判断「发布后又被改过几次」；
- `checksum`：行内容 SHA-256 指纹，判断版本是否发生实质变化；
- `coverage`：该版本覆盖的省份列表；`check_result`：最近一次校验结论（JSON）。

**生效规则**：`settings.data_active_year` 指定当前对外生效年份，缺省取最新 `published` 版本。
业务读取（`repository.thresholds()`）一律带 `year` 条件，杜绝多年数据串味。

## 5. 年度更新 SOP

高考数据的自然节奏决定了更新时间线：

| 时间 | 数据 | 动作 |
| --- | --- | --- |
| 6 月下旬 | 各省控制分数线（批次线） | `new-year` 建草稿 → 回填 11 省官方批次线 |
| 6 月底 | 一分一段表 | 回填位次（985/211 入门位次优先） |
| 7–8 月 | 投档线陆续公布 | 分批 `patch`，每批后 `validate` |
| 8 月底 | 数据基本齐全 | `validate` → 无 error → `publish` |
| 全年 | 个别勘误 | `patch` + `reason`，发布后 `revision+1` |

命令流（等价于管理端按钮）：

```bash
# 1) 以 2026 为蓝本建 2027 草稿（沿用行自动标记 carried=True）
python scripts/manage_data.py new-year --from 2026 --to 2027 --operator alice

# 2) 查看待更新清单（按省份聚合的沿用行）
python scripts/manage_data.py pending 2027

# 3) 回填官方数据（逐条或脚本批量）
python scripts/manage_data.py patch --year 2027 --province 河南 --subject 物理类 \
    --tier 一本 --min-rank 130000 --min-score 540 \
    --source-url https://www.haeea.cn/... --operator alice

# 4) 校验（有 error 则退出码 1，CI 可直接卡住）
python scripts/manage_data.py validate 2027

# 5) 发布（旧版本自动归档，生效年份切换，缓存失效）
python scripts/manage_data.py publish 2027 --operator alice
```

### 5.1 自动化：GitHub Actions 年度更新工作流

`.github/workflows/data-annual.yml` 每年 **7 月 1 日 11:00（北京时间）**自动执行，也可手动触发：

1. 从静态数据源重建数据库（幂等播种）；
2. **以当前生效年份为蓝本创建下一年度草稿**（已存在则跳过）；
3. 跑 `validate`，把结论写进 Job Summary；
4. 导出「待更新清单 + 校验报告」为 Artifact；
5. 在仓库开（或追加评论到）`data-update` 标签的提醒 Issue，列出待回填省份与阻断项。

> 自动化只做「建草稿 + 校验 + 催办」，**不自动发布**——官方数据需要人工核对来源，
> 发布动作留给维护者（`workflow_dispatch` 时勾选 `publish` 才会在校验通过后自动发布）。

所有命令支持 `--json`（单行紧凑输出），方便 CI/脚本消费：

```bash
python scripts/manage_data.py status --json
python scripts/manage_data.py new-year --to 2027 --operator github-actions --json
python scripts/manage_data.py validate 2027 --json
python scripts/manage_data.py pending --year 2027 --json
```

## 6. 单年/局部更新（补丁）

- **单条修正**：管理端基线表格直接改，或 `PATCH /api/admin/baselines/{id}`；
  body 支持 `min_score / min_rank / data_source / line / school / source_url / source_year / carried / reason`；
- **补录缺失行**：`POST /api/admin/baselines`（年份下已存在同键则拒绝，避免脏数据）；
- **批量导入**：改 L1 的 `admission_official_<year>.json` → 管理端点「同步数据源」重新播种，
  播种按 `year` 写入并刷新版本统计，**不会**误删其他年份；
- **撤销**：`POST /api/admin/changes/{id}/undo`，按审计记录把该字段还原（只支持字段级补丁）；
- 补丁后该行 `carried` 自动置 `False`（不再是「沿用往年」），`revision` +1。

## 7. 发布前校验规则

| 编号 | 规则 | 级别 |
| --- | --- | --- |
| R1 | 覆盖完整性：上一版本的每个 (省 × 科类 × 批次) 组合都必须存在 | error |
| R2 | 数值范围：`0 < 分数 ≤ 750`，`1 ≤ 位次 ≤ 3,000,000` | error |
| R3 | 层次单调性：沿 `985 → 211 → 一本 → 二本 → 专科`，位次递增、分数递减 | error |
| R4 | 官方行必须带 `source_url`（可追溯） | error |
| R5 | 同比波动：位次变化 > 40% 的行列出 | warning |
| R6 | 沿用占比：仍标记为「沿用往年」的行 > 50% | warning |

- 有 error 时 `publish` 默认拒绝，`--force` 可强制发布（会记入审计备注）；
- warning 不阻断发布，但会展示在管理端，提醒回填官方数据。

## 8. 发布、回滚与审计

- **发布**：校验通过 → 目标版本 `published` → 旧生效版本 `archived` → `data_active_year` 切换 → 缓存失效；
- **回滚**：`rollback <year>` 把任意还有数据的历史版本重新置为 `published`，秒级生效；
- **审计**：`data_changes` 记录 `clone / patch / create / publish / rollback / import`，
  含 `entity`（如 `河南/物理类/一本`）、`field`、`old_value`、`new_value`、`operator`、`reason`；
- 管理端「变更审计」页可按年份/数据集过滤，并支持按条 undo。

## 9. 自动化与调度

| 层级 | 机制 | 说明 |
| --- | --- | --- |
| 数据校验 | CI：`pytest` + `python scripts/manage_data.py validate <当前年>` | 结构性问题进不了主干 |
| 年度提醒 | 定时任务（每年 6 月 20 日） | 生成「上一版本沿用行清单」，提醒回填 |
| 抓取 | `scripts/ingest_*.py`（半自动） | 官方站点结构多变，保留人工核对环节 |
| 兜底 | JSON 文件 | 数据库不可用时服务仍可读 `backend/data/*.json` |

## 10. 目录与文件规范

```
backend/data/
├── raw/<year>/                     # L0 原始件（只增不改）
├── admission_real_baseline.json    # L1 31 省推算基线（meta.year = 版本年份）
├── admission_official_<year>.json  # L1 官方覆盖层（meta.sources 必填）
├── universities_national.json      # L1 教育部全国高校名单
└── xuefeng.db                      # L2 服务库
```

新增年份的官方覆盖层按 `admission_official_<year>.json` 命名，
播种时以 `meta.year` 作为版本年份写入，旧年份文件保留可随时回滚。

## 11. 命令 / API 对照

| 操作 | CLI | API | 管理端 |
| --- | --- | --- | --- |
| 版本总览 | `status` | `GET /api/admin/versions` | 数据版本页 |
| 建新年度 | `new-year` | `POST /api/admin/versions/clone` | 「新建年度」 |
| 校验 | `validate` | `POST /api/admin/versions/{year}/validate` | 「校验」 |
| 发布 | `publish` | `POST /api/admin/versions/{year}/publish` | 「发布」 |
| 回滚 | `rollback` | `POST /api/admin/versions/{year}/rollback` | 「回滚」 |
| 待更新 | `pending` | `GET /api/admin/versions/{year}/pending` | 待更新清单 |
| 单条补丁 | `patch` | `PATCH /api/admin/baselines/{id}` | 表格内联编辑 |
| 变更审计 | `changes` | `GET /api/admin/changes` | 变更审计页 |
| 撤销 | — | `POST /api/admin/changes/{id}/undo` | 「撤销」 |

## 12. 演进路线

- [ ] 院校总表 / 内容数据集接入同一套版本机制（`dataset` 字段已预留）；
- [ ] 版本间差异报告：发布前可预览「相对上一年哪些行变了、变了多少」；
- [ ] 官方数据抓取自动化（先做省控线，投档线仍需人工核对）；
- [ ] 多人协作：草稿态下支持「提交审核」，审核通过才能发布。
