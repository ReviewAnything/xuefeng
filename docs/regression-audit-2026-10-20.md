# 全量回归审计报告（2026-10-20）

> 触发背景：上一轮 E1/E2 规划未获批准，改为对已落地实现做一次「功能 / 设计 / 实现」三层回归，
> 目标是找出**测试通过但行为错误**的地方，并逐条修复 + 补回归用例。
> 审计方式：通读后端 6 个 service + 3 个数据层 + 管理端路由、前端 8 个页面 + 4 个工具模块；
> 用真实数据启动服务，对 24 个接口做冒烟与边界探测；对可疑点写脚本复现后再改代码。

## 一、结论速览

| 项 | 审计前 | 审计后 |
|---|---|---|
| 后端 pytest | 102 passed | **114 passed**（新增 12 条回归用例） |
| 前端引擎 / 志愿表 / 模板 | 8 / 27 / 9 | **9 / 35 / 9** |
| 发现实质缺陷 | — | **9 个**（P0 级 2 个、P1 级 4 个、P2 级 3 个） |
| 接口冒烟（含管理端） | — | 24/24 返回 200 |
| 数据校验 `validate_year(2026)` | 通过 | 通过（0 error，2 warning，均为已知口径提示） |

所有 P0/P1 已修复并有回归用例；P2 中 2 项已修，1 项转为「已知边界」写入 README。

## 二、P0：会让用户拿到错误结论

### 1. 院校推荐池被 1000 行上限截断（数据缺失 + 数量谎报）

- **症状**：广东考生的「普通本科池」显示 911 所、「专科池」1000 所；而实际是 1196 / 1560 所。
- **根因**：`recommend._pick_pool()` 按档各查一次，传 `limit=3000`；仓储层 `repo.universities()`
  为保护接口把 `limit` 钳到 1000。于是按 `province, id` 排序的前 1000 行之外，
  云南/西藏/甘肃等排序靠后的院校**永远不会出现在推荐里**，`pool_total` 也系统性偏小。
- **修复**：仓储层支持 `limit=None` 表示不分页取全量（对外 API 仍封顶 1000）；
  推荐侧改为**一次取全量 2868 所 + 内存分组**，5 次查询降为 1 次。
- **验证**：`test_recommend_pool_not_truncated_at_1000`、`test_recommend_benke_pool_full_size`。
  复测：专科 1560、本科 1196、211 74、985 38。

### 2. 「普通一本」和「普通二本」把同一批院校重复列两遍

- **症状**：广东/河南/北京三地实测，两档 `pool_total` 完全相同，前 3 所院校一模一样；
  进入志愿表后**同一所学校出现两次**（分属“保”和另一个“保”档）。
- **根因**：新高考合并本科批后，一本=特殊类型招生控制线、二本=本科批线，二者本就共用
  「本科院校池」；实现却给每档独立展开院校。
- **修复**：引入 `POOL_KEY` / `pool_key`，同一院校池只由**一档**展开院校：
  优先可达档，其次门槛更严（更靠上）的那档；另一档返回 `pool_shared_with` 并在
  `basis` 里说明「与『X』同一院校池」。志愿表因此不再出现重复院校。
- **验证**：`test_shared_pool_expands_once`（两档校名集合不相交，且恰好一档为空）。

## 三、P1：口径误导与功能形同虚设

### 3. 官方数据「沿用往年」却不告诉用户年份

- **症状**：界面给 2026 年的门槛打「官方」标签，实际是 **2024 年**省控线/投档位次
  （数据库 84 行 `data_source=official` 全部 `carried=true, source_year=2024`）。
- **根因**：`repo.thresholds()` 返回了 `carried`，但 `admission.major_thresholds()` 组装响应时
  把 `carried`、`source_year` 丢了；推荐/核验接口自然无从展示。
- **修复**：三处透传——`repo.thresholds()` 补 `source_year`；`major_thresholds()` 两个分支
  （DB / JSON 兜底）都输出 `source_year` + `carried`；推荐接口每档带上这两个字段。
  前端标签改为「官方·沿用2024」，README「已知边界」补口径说明。
- **验证**：`test_official_source_year_surfaced`、`test_api_recommend_exposes_carried_flag`。

### 4. 校线数据导入后，前端根本看不到

- **症状**：D1 声称导入后院校行会显示「去年最低分」，实际推荐页没有任何字段渲染它；
  志愿表里有「去年 X 分」的模板，但永远为空。
- **根因**：两处断链——① `recommend.vue` 只渲染 `province/city/category`，没渲染
  `min_score/min_rank/line_year`；② `savePlan()` 落盘时只挑了 `name/province/nature`，
  把校线字段整段丢掉。
- **修复**：推荐页新增「去年最低 xx 分 · 位次 xxx（YYYY 年投档线）」行，缺数据时明确提示
  「该省未导入该校投档线，仅按层次估算」；`savePlan()` 透传 4 个校线字段；
  `flattenPlan()` 增加 `line_rank/line_year`，导出文本带年份。
- **验证**：前端 `plan.test.mjs` 新增 8 条断言；后端端到端实测：导入 4 行（1 行校名不存在）
  → `hits=3`，三所院校正确挂上 552/68000/2024 等值，未匹配行被拒绝入库。

### 5. 等位分换算把「参数化样例年」当真实年份

- **症状**：`/api/equiv/years` 返回 2026 估算、2025 样例、2024 官方三年；前端默认选中
  2026→2025，等于拿虚构样例年做换算，结果看似精确。
- **修复**：`available_years()` 过滤 `sample`；前端在可用年份 <2 时给出明确提示
  （「该省/科类目前只有 X 年有可用锚点，暂无法跨年换算」），不再让按钮空转。
- **验证**：`test_available_years_excludes_sample`。

### 6. 登录锁定到期后计数不清零 → 一次输错再锁 15 分钟

- **症状（实测）**：连续 5 次错误 → 锁定；15 分钟到期后，输错 1 次立即重新锁定，
  **连正确密码也进不来**（因为再次进入锁定分支）。
- **根因**：`login()` 只在成功时清零 `failed_attempts`；锁定期过期分支没有重置。
- **修复**：锁定期已过时先清零 `failed_attempts` 与 `locked_until`，再校验密码。
- **验证**：`test_lock_expiry_resets_failed_attempts`（过期后单次错误 → `bad_credentials`，
  再输正确密码 → 登录成功）。

## 四、P2：体验与工程一致性

### 7. 档位排序按门槛位次 → 211 排到「一本」后面

- **根因**：`tiers.sort(key=(level, min_rank))`。广东 211 入门位次（100604）大于特控线位次
  （96443），于是 211 被排到一本之后，违反批次直觉。
- **修复**：同档位内按固定批次序 `985→211→一本→二本→专科`（`TIER_INDEX`）；
  跨档仍按 冲→稳→保→不可及（不可及的 985 排最后，是有意为之）。
- **验证**：`test_tier_order_is_batch_order`。

### 8. 等位分在「恰好落锚点」时被误标为外推

- **症状**：输入正好是省控线位次（如广东 96443）时，`extrapolated=true`，前端提示
  「落在锚点区间之外」——其实正好在锚点上。
- **根因**：边界判断用了 `<=` / `>=`。
- **修复**：改为严格不等，等值走插值分支（结果精确且 `extrapolated=false`）；
  同时给跨源换算（官方 ↔ 估算）加 caveat，提示两年口径不同、偏差可能较大。
- **验证**：`test_exact_anchor_is_not_extrapolated`、`test_convert_warns_on_mixed_sources`。

### 9. 管理端 CLI 在全新 checkout 上直接崩

- **症状**：`python scripts/import_school_lines.py --coverage` 报
  `sqlite3.OperationalError: no such table: school_lines`（仓库不提交 `*.db`）。
- **修复**：CLI 启动先 `init_db(seed=False)` 建表（幂等、不触发全量播种）。
- **验证**：`test_cli_schema_helper_creates_tables` + 空库实跑 `--coverage` 返回 0 行。

### 附：顺带修掉的三个一致性问题

| 问题 | 处理 |
|---|---|
| 决策引擎把「军校/定向士官」推荐给历史类考生，而专业组模块标记为「物理」必选 | 引擎加 `PHYSICS_ONLY` 过滤，与 `major_groups.SUBJECT_REQ` 对齐；新增用例 |
| 校线 `replace` 模式的 keep 集合是全局的，跨年 scope 会漏删旧行 | 改为按 (年,省,科类) 分别维护 keep；新增用例 |
| 管理端看板每次请求整读 2.5MB JSON 算签名（/sources 1.19s） | 签名按 (路径, mtime, size) 缓存，并避免一次请求内算两遍；实测 1191ms → ~350ms |

## 五、设计层复核（没有改代码，但确认成立的部分）

- **数据分层**：JSON 源 → SQLite 事实源 → API，DB 不可用回落 JSON，`invalidate_cache()` 串起
  播种/同步/版本切换三处；未发现缓存不一致路径。
- **版本状态机**：draft → validated → published → archived，`publish/rollback` 同事务切
  `data_active_year`；`validate_year(2026)` 实测 0 error（COVERAGE/RANGE/MONOTONIC/SOURCE_URL 全过）。
- **单调性校验**：985/211 属「院校层级」，位次倒挂只 warning（中外合作/异地校区确实会倒挂），
  批次层级同源倒挂才 error——这个分级判断是对的。
- **鉴权**：PBKDF2 + HMAC、令牌内嵌微秒级密码戳、`must_change_password` 拦截写操作、
  未知账号按 IP 限流且文案与密码错误一致（防枚举）——设计成立。
- **可观测**：日志只记 `url.path`，`?token=` 不会进日志（导出接口用 query token 的风险可控）。
- **隐私**：诊断/志愿表/画布全部走端侧 storage，只有省份/科类/位次/专业名上行。

## 六、未修 / 需要你决策

1. **跨源换算的误差**：2026 估算基线（gaokao-advisor）与 2024 官方线的 985 入门位次差异很大
   （广东 7000 vs 29731）。代码已加 caveat，但根子是「用哪一年做基准」的产品决策，
   不是 bug。建议在拿到 2026 官方一分一段表后填 `backend/data/score_tables.json` 覆盖。
2. **校线仍无真实数据**：能力链路已端到端验证（导入→匹配→落库→推荐展示→志愿表导出），
   但仓库不附带投档表；需要你提供各省考试院原始表。
3. **管理端未做浏览器目视走查**：本轮只做了接口级冒烟（15 个管理端接口全 200）与
   `node --check` / 自闭合标签静态检查；按钮级交互建议实机过一遍。
4. **H5 构建仍只能靠 CI**：沙箱内 `npm ci` 被镜像拦截（历史问题），本轮未改依赖，
   `npm ci` 已在 `ci.yml` 取代 `npm install`，构建验证交给 CI。

## 七、复现命令

```bash
# 后端（114 passed）
cd backend && XUEFENG_DB_PATH=/tmp/xf.db pytest -q

# 前端（9 / 35 / 9）
cd frontend && npm test

# 当年数据校验
cd backend && python scripts/manage_data.py validate 2026
```
