# 部署说明（C1 公开 demo）

四条互相独立的部署路径，按需取用；前端是纯静态站，后端可选。

| 路径 | 用途 | 是否有后端 | 耗时 |
| --- | --- | --- | --- |
| A. GitHub Pages（静态 H5） | 公开 demo、分享链接 | 可选（不配则只跑本地内容） | 5 分钟 |
| B. Render（只读公开后端） | 给 Pages demo 提供 API | 是 | 5 分钟 |
| C. docker-compose（本地/自建服务器） | 完整体验（含管理端） | 是 | 1 分钟 |
| D. 微信小程序（**首发渠道**） | 移动端正式产品 | 是（联调期本机，上线需 https 域名） | 首次 10 分钟 |

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

- 演示数据分「官方省控线（**31 省，2022–2026，逐年附 source_url**）」与「模型估算（其余省）」，界面上会标注来源；
- 一分一段表（位次锚定 / 等位分换算所需）已采集 **30/31 省**（仅西藏因官方不公布而缺失）；其中 9 省为经核实的第三方文本转录（标注 `third_party_text`），**不混入官方库、不参与 official 覆盖**；
- 官方省控线主表不含位次：入库时保留估算基线的 min_rank，避免把生效年份的官方行置 0 拉垮冲稳保实时排名（设计意图，非缺口）；
- 院校级投档线**不入库不发包**：需要自己上传（管理端「校线导入」或 `scripts/import_school_lines.py`），
  导入前推荐结果只到「层次」粒度；
- 页面显著位置保留「仅供学习参考，正式填报以各省考试院为准」提示，部署时请勿移除；
- 管理端默认口令属于演示用途，任何公网部署都必须改掉或关闭管理端。

---

## 公开只读 API（供 Pages demo 调用）

部署 Render 后端并设 `XUEFENG_DISABLE_ADMIN=true` 后，以下端点对 demo 可见（`/api/admin/*` 已关闭）：

| 端点 | 用途 |
| --- | --- |
| `GET /api/admission/control-line-years` | 近五年官方省控线可用年份（2022–2026） |
| `GET /api/admission/control-lines?year=&province=` | 某年某省分科类/档位的省控线 + 当年来源链接 |
| `GET /api/admission/volunteer-limit?province=` | 该省志愿个数上限（院校专业组 / 专业+院校 / 旧高考）+ 建议冲/稳/保分布 |
| `GET /api/rank-tables/lookup?year=&province=&subject=&score=` | 分数 → 位次（一分一段，本科/专科双档位） |
| `GET /api/equiv/curve?province=&subject=&year=` | 等位分换算曲线（真实一分一段锚定，标注官方/第三方来源） |
| `GET /api/equiv/convert?province=&subject=&from_year=&to_year=&score=` | 跨年等位分换算（自动标注口径差异 caveat） |
| `GET /api/health` | 健康检查：版本 / 生效年份 / 库大小 / 校线覆盖 |

前端新增页：**年度罗盘（compass）** 浏览近五年省控线走势与跨省对比；**志愿表（plan）** 内置本省志愿个数上限、组内专业排序、服从专业调剂标记与导出对齐。

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

---

## D. 微信小程序（首发渠道）

### D1. 本地开发链路（开发者工具模拟器）

```bash
cd frontend
npm install --legacy-peer-deps   # npm ci 会因 pinia/vue 的 peer 冲突报 ERESOLVE
npm run dev:mp-weixin            # 产物输出 frontend/dist/dev/mp-weixin（watch 模式）
```

1. 微信开发者工具 → 导入项目 → 目录选 `frontend/dist/dev/mp-weixin`，AppID 用测试号或真实 AppID；
2. 后端本机起：`cd backend && python main.py`（监听 `0.0.0.0:8000`）；
3. 模拟器里 `http://localhost:8000` 可直接访问（模拟器跑在 Mac 上，localhost 即本机）。

> 若请求被拦：开发者工具 → 详情 → 本地设置 → 勾选「不校验合法域名…」
> （`manifest.json` 的 `mp-weixin.setting.urlCheck: false` 已默认关掉校验）。

### D2. API 地址是怎么决定的（容易误解的三件事）

**① `localhost` 是前端构建期注入的，不是后端「只提供」本机访问。**
链路：`npm run dev:mp-weixin`（development 模式）→ 读 `frontend/.env.development`
→ `VITE_API_BASE=http://localhost:8000` → 经 `vite.config.ts` 的 `define`
以字面量注入应用代码。改后端地址只改 `.env.development`，不用动代码。

**② 后端本身绑的是 `0.0.0.0`，不是 127.0.0.1。**
`backend/main.py` 的 `__main__` 入口是 `uvicorn.run(host="0.0.0.0", port=8000)`，
docker-compose / render.yaml 同样 `--host 0.0.0.0`。
⚠️ 唯一例外：裸命令 `uvicorn main:app`（不带 `--host`）时 uvicorn 自身默认绑
`127.0.0.1`——启动日志出现 `Uvicorn running on http://127.0.0.1:8000` 就是这种情况，
改用 `python main.py` 或补 `--host 0.0.0.0` 即可。

**自查三步（现象：localhost 能通、内网 IP 不通）：**

```bash
# ① 看 8000 端口实际监听地址
lsof -nP -iTCP:8000 -sTCP:LISTEN
#    显示 127.0.0.1:8000 → 只绑了本机（问题所在）
#    显示 *:8000        → 绑了所有网卡（正确）

# ② 修复启动方式（任选其一）
cd backend && python main.py
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

```bash
# ③ 本机浏览器先验证：访问 http://<内网IP>:8000/api/health
#    本机通 → 后端已就绪，手机不通才是网络层问题（同 WiFi / 路由器 AP 隔离 /
#    VPN / macOS 防火墙——系统设置 → 网络 → 防火墙放行 Python）
#    本机不通 → 仍是绑定问题，回到 ①
```

> 判断依据：访问本机内网 IP 不经过物理网络，绑了 `0.0.0.0` 时本机必通。
> 所以「localhost 通 + 内网 IP 不通」可以直接判定监听地址是 `127.0.0.1`。

**③ CORS 只影响 H5 浏览器，与小程序无关。**
`main.py` 默认白名单（localhost 的 5173/8000/8080）是给 H5 跨域用的；
小程序 `wx.request` 不走浏览器同源策略，不受 CORS 约束。

### D3. 真机预览（开发版）

真机上 `localhost` 指向手机自己，必挂。联调步骤：

1. 手机与 Mac 连**同一 WiFi**；
2. 查 Mac 局域网 IP：`ipconfig getifaddr en0`（形如 `192.168.x.x`；公司网络/VPN 网段可能不通）；
3. 把 `frontend/.env.development` 的 `VITE_API_BASE` 改成 `http://<该IP>:8000`，重新 `dev:mp-weixin`；
4. 确认后端绑 `0.0.0.0`（见 D2②），必要时关 Mac 防火墙或放行 8000 端口；
5. 开发者工具 → 预览，扫码。开发版可绕过域名校验（仍需在手机上开启调试模式）。

### D4. 正式发布清单

| # | 事项 | 位置 |
| --- | --- | --- |
| 1 | 部署后端到公网 https（Render Blueprint 即 `render.yaml`，或自建） | 路径 B / C |
| 2 | `frontend/.env.production` 的 `VITE_API_BASE` 填真实 https 域名 | frontend/.env.production |
| 3 | `manifest.json` 的 `mp-weixin.appid` 替换占位的 `touristappid` | frontend/src/manifest.json |
| 4 | 微信公众平台 → 开发管理 → 开发设置 → **服务器域名**：request 合法域名加上该 https 域名 | mp.weixin.qq.com |
| 5 | `npm run build:mp-weixin`（production 模式，自动读 `.env.production`） | frontend/ |
| 6 | 开发者工具上传代码 → 提交审核 → 发布 | 微信开发者工具 |

> 注意：微信要求 request 合法域名必须是 **https 且已备案的域名**（本机 IP、
> localhost 均不可用于正式版）。

### D5. 小程序专属的工程约束（改动前必读）

- **源码禁用 `import.meta` / `process` / `require()` / `URLSearchParams`**：
  uni-app 小程序平台会把 `import.meta` 转译成 `require('url')`，运行时无该模块，
  app.js 启动即崩。环境变量只经 `vite.config.ts` 的 `define: { __APP_ENV__ }` 注入，
  应用代码只读 `__APP_ENV__` 普通对象；
- **护栏测试**：`frontend/tests/crossend.test.mjs`（`npm test` 内）会扫描 `src/**`
  并断言 define 契约，改环境配置后必须跑；
- **wot-design-uni 组件多为 `virtualHost`**：写在组件标签上的 `:style`/`class`
  在小程序端会被丢弃，须用 `custom-style`/`custom-class` prop（已全部接入）；
- **图标字体已自托管**：`src/styles/wd-icons-font.css` base64 内嵌（小程序 WXSS
  不支持远程 `@font-face`），升级 wot 后重跑 `scripts/gen_wd_icons_font.py`。

