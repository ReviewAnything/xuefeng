# 部署说明（C1 公开 demo）

三条互相独立的部署路径，按需取用；前端是纯静态站，后端可选。

| 路径 | 用途 | 是否有后端 | 耗时 |
| --- | --- | --- | --- |
| A. GitHub Pages（静态 H5） | 公开 demo、分享链接 | 可选（不配则只跑本地内容） | 5 分钟 |
| B. Render（只读公开后端） | 给 Pages demo 提供 API | 是 | 5 分钟 |
| C. docker-compose（本地/自建服务器） | 完整体验（含管理端） | 是 | 1 分钟 |

---

## A. GitHub Pages 静态 H5

1. 仓库 **Settings → Pages → Source** 选择 **GitHub Actions**。
2. **Actions → Deploy H5 (GitHub Pages) → Run workflow**（默认手动触发；
   想自动部署就把 workflow 里的 `push` 段注释去掉）。
3. 完成后 Pages 会给出形如 `https://<用户名>.github.io/xuefeng/` 的地址。

构建细节（已在 `.github/workflows/deploy-h5.yml` 里）：

- `npm ci` 按 `package-lock.json` 装依赖，可复现；
- 先跑 `npm test`（决策引擎 + 志愿表工具 + SFC/管理端模板编译），失败即中止；
- `npm run build:h5` 产出 `frontend/dist/build/h5`，hash 路由 + 相对路径
  （`manifest.json` 的 `h5.router.base = "./"`），适配 Pages 子路径；
- 构建后做**产物自检**：`index.html` 存在、含 `#app` 挂载点、至少一个 >1KB 的 JS 包
  （避免「构建成功但上线空壳」）；
- 若配置了变量 `XUEFENG_API_BASE`，会把 `window.__XUEFENG_API__='…'` 注入 `index.html`。

**后端地址三处来源（优先级从高到低）**：

1. `window.__XUEFENG_API__`（部署后可改，无需重新构建）
2. 构建期环境变量 `VITE_API_BASE`
3. 默认 `http://localhost:8000`（本地开发）

没有后端时，诊断画布、专业图谱、开源资源、关于页照常可用（这些内容随包发布），
需要后端计算的「核验 / 院校推荐 / 等位分换算」会提示未连接。

---

## B. Render 只读公开后端（可选）

仓库根目录提供 `render.yaml`：Render → New → Blueprint → 选本仓库即可创建服务。

关键环境变量：

- `XUEFENG_DISABLE_ADMIN=true`：关掉 `/admin` 控制台与 `/api/admin/*`，
  **只保留公开只读 API**。公开展示时必须开启，否则默认管理员口令会被暴露。
- `XUEFENG_CORS_ORIGINS=https://<用户名>.github.io`：CORS 白名单，多个逗号分隔，不要写 `*`。
- `XUEFENG_DB_PATH=/tmp/xuefeng.db`：免费实例无持久化磁盘，库放 `/tmp`，
  重启后由 `backend/data/*.json` 自动重新播种。

部署成功后把服务地址填进 GitHub 仓库变量 `XUEFENG_API_BASE`，再跑一次 Pages workflow。

其它平台（Fly.io / Railway / 任意 VPS）同理，关键是三条：注入 `XUEFENG_DISABLE_ADMIN`、
配置 CORS 白名单、把 `uvicorn main:app --host 0.0.0.0 --port $PORT` 作为启动命令。

---

## C. docker-compose（本地或自建服务器）

```bash
docker compose up --build
# 前端 http://localhost:8080  后端 http://localhost:8000  管理端 http://localhost:8000/admin
```

首次登录管理端用默认账号 `admin / xuefeng@2026`，**登录后请立刻改密码**；
自建服务器对外暴露时同样建议设置 `XUEFENG_DISABLE_ADMIN=true` 或改默认口令。

---

## 数据与合规提示

- 演示数据分「官方省控线（11 省）」与「模型估算（其余省）」，界面上会标注来源；
- 院校级投档线**不入库不发包**：需要自己上传（管理端「校线导入」或 `scripts/import_school_lines.py`），
  导入前推荐结果只到「层次」粒度；
- 页面显著位置保留「仅供学习参考，正式填报以各省考试院为准」提示，部署时请勿移除；
- 管理端默认口令属于演示用途，任何公网部署都必须改掉或关闭管理端。

---

## 运维（D2/D3）

| 事项 | 做法 |
| --- | --- |
| 登录安全 | 默认 5 次失败锁 15 分钟；`XUEFENG_LOGIN_MAX_FAILS` / `_WINDOW` / `_LOCK` 可调；审计在 `login_attempts` 表与 `/api/admin/login-attempts` |
| 令牌失效 | 改密后旧令牌立即失效（令牌内嵌密码变更时间戳）；改密接口返回新令牌 |
| 初始密码 | `must_change_password=true` 时写接口一律 403，先改密再用 |
| 访问日志 | 每请求一行 JSON，含 `rid/status/ms`；响应头 `X-Request-ID` 便于和前端日志对齐 |
| 慢请求 | 默认 >800ms 标 `level=warn`（`XUEFENG_SLOW_MS` 调整），`/api/health.observability` 有聚合 |
| 备份 | `python scripts/backup_db.py --dir backups --keep 14 --gzip`，建议 cron 每日执行 |
| 健康检查 | `GET /api/health` 含版本、生效年份、库大小、校线覆盖、请求指标 |

自建服务器示例（每日 3:10 备份）：

```cron
10 3 * * * cd /srv/xuefeng/backend && /usr/bin/python3 scripts/backup_db.py --dir /var/backups/xuefeng --keep 14 --gzip
```

