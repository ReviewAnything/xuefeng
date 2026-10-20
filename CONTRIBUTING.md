# 贡献指南（CONTRIBUTING）

感谢你关注**志愿决策助手 v2（xuefeng）**！这个项目以「就业确定性优先（普通家庭 + 就业导向）」为方法论，与开源社区资源结合，输出**决策框架而非录取结论**；张雪峰公开观点为观点来源之一（社区整理）。

## 开发环境

```bash
# 后端
cd backend && pip install -r requirements.txt && pytest -q
uvicorn main:app --reload --port 8000      # http://localhost:8000/docs

# 前端
cd frontend && npm install && npm run dev:h5

# 单一数据源
shared/content.json  # 前端与后端共用，年度更新只改这一个文件并 bump APP_VERSION
```

## 数据来源与更新

- 录取位次基线由 `backend/scripts/ingest_gaokao_advisor.py` 基于
  [chenxuyaun/gaokao-advisor](https://github.com/chenxuyaun/gaokao-advisor)（MIT）的
  31 省一分一段表 / 院校层次参数生成，覆盖 31 省，写入
  `backend/data/admission_real_baseline.json`，**后端优先使用**。
- 重新生成真实基线：

  ```bash
  python backend/scripts/ingest_gaokao_advisor.py          # 用内置参数（离线）
  python backend/scripts/ingest_gaokao_advisor.py --sync   # 拉取 gaokao-advisor 最新参数
  ```

## 提交约定

- 内容（专业观点、资源链接）请附**可溯源**的出处与年份；无出处的数字不进 `content.json`。
- 后端改动请补/更新 `backend/tests/test_api.py`；前端引擎改动请更新 `frontend/tests/engine.test.mjs`。
- 提交信息清晰说明「做了什么 / 为什么」。
- **本仓库的推送由维护者统一进行，PR 请走 review，不要自行 force-push。**

## 行为准则

- 本工具仅供学习参考，不构成正式升学/志愿填报建议。
- 尊重开源协议：gaokao-advisor 为 MIT，引用其数据时保留署名与许可说明。
