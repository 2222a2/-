# 备考任务模块扩展（P0→P3）说明

> 目标：把"每天按时间段分类的备考任务"打通数据层、前端编辑页、周进度看板，并让微信推送只列科目、手机可点开编辑。
> 技术栈：FastAPI + SQLite（后端）/ React + Vite + axios（前端），零新增重依赖。

## 一、四期分别做了什么

### P0 数据层 + 后端（已完成，之前落地）
- `backend/app/db.py`：`study_task` 表 + `upsert_study_tasks_for_date / list_study_tasks / patch_study_task / add_study_task / weekly_progress / delete_study_task / ingest_pending_study_tasks`。
- `backend/app/schemas.py`：`StudyTaskCreate / StudyTaskOut / WeeklyProgressOut`。
- `backend/app/study_tasks.py`：`POST /api/study-tasks`（按日期批量建）、`GET`（按 date 或 week）、`PATCH /{id}`（勾选/改标题）、`POST /add`（手动加）、`DELETE /{id}`（删）、`GET /weekly`（周聚合）。
- `backend/app/main.py`：已 `include_router`；启动时自动吃 `study_tasks_pending.json`。

### P1 生成器（本次新建 `backend/scripts/gen_study_tasks.py`）
- 读一份可编辑的每日模板 `DEFAULT_TEMPLATE`（时间段 + 科目 + 标题）。
- 默认生成"明天"的任务：优先 `POST /api/study-tasks`；后端没开则落盘 `backend/data/study_tasks_pending.json`（平台启动自动入库，不丢）。
- 发企业微信：**只列科目**（`英语 · 数学 · 408 · 数据结构`），链接指向平台页 `STUDY_WEB_BASE_URL/study-tasks?date=YYYY-MM-DD`。
- 用法：`python gen_study_tasks.py [--date X] [--dry-run] [--no-wechat]`。依赖仅标准库。

### P2 前端可编辑页 + 周进度（本次新建）
- `frontend/src/components/StudyTasksPage.tsx`：
  - **今日视图**：按 早上 / 午间 / 晚上 / 其他 分组；每条可勾选、点标题改、删除；每组底部可加任务（选科目+填标题）。
  - **本周进度视图**：总完成率进度条 + 各科完成率 + 每天(周一~周日)完成率小条。数据来自 `GET /weekly`。
  - 支持 `?date=` 深链（微信点开直接定位到那天）。
- `frontend/src/api/client.ts`：新增 `study` 接口对象与 `StudyTask / WeeklyProgress` 类型。
- `frontend/src/App.tsx`：侧边栏加「📖 备考任务」入口；深链自动进该页。
- `frontend/vite.config.ts`：`host` 改 `0.0.0.0`（同局域网手机可访问，P3 方案 B 基础）。

### P3 微信点开能编辑 —— 可达性（本次配置 + 方案）
- `backend/app/config.py`：新增 `STUDY_WEB_BASE_URL`（默认 `http://127.0.0.1:5173`），生成器拼链接用它；新增 `STUDY_PAGE_TOKEN`（默认空=不校验）。
- **口令保护（本次新增）**：`study_tasks.py` 路由统一加 `verify_study_token` 依赖——`STUDY_PAGE_TOKEN` 为空时放行（本地零摩擦），设了值则 `study-tasks` 全部接口必须带 `X-Study-Token` 且相等，否则 401。前端 `StudyTasksPage` 首次打开若被 401 会弹出口令框，输对后存 localStorage，后续免输。生成器写库时也自动带该 token。→ **走公网/局域网必开，避免别人误改你的任务**。
- 三种可达性方案（**当前先采用 B 同局域网**：零安装、零公网暴露，电脑手机同 WiFi 即可；cloudflared 公网隧道 A 留作"出门也要改"时的备选）：
  - **A 公网隧道（备选，外出也能改）**：装 `cloudflared`，`cloudflared tunnel --url http://localhost:5173`，把给的 `https://xxx.trycloudflare.com` 填进 `STUDY_WEB_BASE_URL` 环境变量。免费随机 URL 不可猜，个人自用足够。**务必同时设 `STUDY_PAGE_TOKEN`**。
  - **B 同局域网（零公网暴露）**：手机和电脑连同一 WiFi。`vite.config.ts` host 已默认 `0.0.0.0`，手机开 `http://<电脑局域网IP>:5173/study-tasks?date=...`。建议也设 `STUDY_PAGE_TOKEN`。
  - **C 暂不做手机编辑**：微信只点链接看，增删改在桌面完成（本次未采用）。

## 二、为什么这么做（决策原因）

1. **数据落 worklearn-platform，不另起小工具**：P0 已有 `study_task` 表与一套接口，顺着骨架扩，未来 M3 周报 / M7 专注计时都能直接引用，避免数据孤岛。
2. **时间段分组 + 周聚合**：直接落地"按早/中/晚分类"和"看每周完成/进度"两条诉求，且周进度呼应"周复盘非日自责"。
3. **微信只列科目不列时间段**：降低睡前打开压力（去罪恶化），手机屏窄也清爽。
4. **链接配置化而非写死**：用 `STUDY_WEB_BASE_URL` 同时兼容"本机 / 局域网 / 公网"三种落地，不绑架你选哪条。
5. **断网兜底 pending**：23:00 生成器写库时后端若没开，落盘等启动即同步，任务不会丢。
6. **前端增删改走已验证接口，只补一个 delete**：最小改动风险，且让"微信点开能改"在桌面端先有落点。

## 三、验证方式（都已实跑通过）

- **编译**：`cd frontend && npm run build` → `tsc -b` 0 错、`vite build` 产出 `dist/`（顺手修了 `KnowledgePage`/`NoteEditor` 两个预存 TS 错误，使整项目可干净构建）。
- **后端路由**：起实例后 curl 实测 `health / POST / GET(date) / PATCH(done) / DELETE / weekly` 全部正确；基线 5 行未被误改，测试数据已清理。
- **生成器**：`--no-wechat` 跑通两条路径——API 在线时写入 5 条、离线时落盘 `study_tasks_pending.json`（结构正确）；微信摘要仅列科目并带链接。
- **前端**：`npm run dev` 开发态即可用（vite 不走 tsc，预存 TS 错不影响 dev）；生产 `dist` 已能构建。

## 四、你接下来要做的（已按"方案 A + 口令"落地）

1. 在 `gen_study_tasks.py` 的 `DEFAULT_TEMPLATE` 改成你真实的每日计划。
2. **设口令**：起后端时带 `STUDY_PAGE_TOKEN=你自定的串`（见第五节命令示例）。前端首次打开会要你输这串，输一次即可。
3. **企业微信**：建群机器人，把 webhook 地址写进 `backend/data/.wechat_webhook.txt`。
4. **公网隧道**：装 `cloudflared`（见第五节），起隧道并把给的 `https://xxx.trycloudflare.com` 设为 `STUDY_WEB_BASE_URL`。
5. **定时**：设 23:00 跑生成器（Windows 任务计划程序），`STUDY_API_BASE` 指向后端端口（默认 8000），且生成器环境也带上 `STUDY_PAGE_TOKEN`。
6. 起服务：`uvicorn app.main:app --port 8000`（后端）+ `npm run dev`（前端，host 已 0.0.0.0），隧道指向 5173。手机微信点链接即可改。

## 五、实操步骤（企业微信 + 公网隧道 + 口令）

### 5.1 手机推送渠道设置（任选其一，企业微信建不了就换别的）
生成器按"企业微信 → 方糖 → 推送加 → Bark"自动选可用通道，只设其中一个即可。通道都把你当**个人**推送，不需要建群/管理员权限。

- **A. 企业微信群机器人（原方案，建得了才用）**：进群 → `...` → 群机器人 → 新建「备考小渝」→ 复制 webhook 存 `backend/data/.wechat_webhook.txt`（或 `WECHAT_WEBHOOK`）。消息进企业微信群，链接可点。
- **B. 方糖 ServerChan（推到个人微信，推荐首选）**：去 https://sct.ftqq.com 用微信扫码登录，拿到 `SCTxxxx` 形式的 key，设环境变量 `SERVERCHAN_KEY=SCTxxxx`。关注方糖公众号，推送以公众号消息进**个人微信**，链接可点（微信内打开）。
- **C. 推送加 pushplus（同上，推到个人微信）**：去 https://www.pushplus.plus 注册拿 token，设 `PUSHPLUS_TOKEN=xxxx`。关注公众号收消息。
- **D. Bark（仅 iPhone，体验最好）**：App Store 装 Bark，打开会给你一个 `https://api.day.app/你的KEY`，设 `BARK_URL=https://api.day.app/你的KEY`。推送是**系统通知**，点通知直接跳 Safari 打开链接。

先验证：`python backend/scripts/gen_study_tasks.py --no-wechat` 确认写库；再去掉 `--no-wechat` 正式发（设好对应 key 即可）。所有通道都只发"科目摘要 + 平台页链接"，不列时间段。

### 5.2 公网隧道（cloudflared，方案 A）
Windows 安装（任选其一）：
- `winget install --id Cloudflare.cloudflared`
- 或去 https://github.com/cloudflare/cloudflared/releases 下载 `cloudflared-windows-amd64.exe`，丢进 PATH。

一条命令起隧道（保持运行）：
```bat
cloudflared tunnel --url http://localhost:5173
```
它会打印 `https://xxxx.trycloudflare.com`。把这个地址作为 `STUDY_WEB_BASE_URL`。

### 5.3 一套起服务的命令（带口令 + 公网链接）
后端（PowerShell / CMD，设口令与前端可达地址）：
```bat
cd backend
set STUDY_PAGE_TOKEN=你自定的串
set STUDY_WEB_BASE_URL=https://xxxx.trycloudflare.com
.venv2\Scripts\python.exe -m uvicorn app.main:app --port 8000
```
前端（另一个终端）：
```bat
cd frontend
npm run dev
```
隧道（第三个终端）：
```bat
cloudflared tunnel --url http://localhost:5173
```
生成器 23:00 定时跑时，环境也要带 `STUDY_PAGE_TOKEN`（否则写库被 401）：
```bat
set STUDY_API_BASE=http://127.0.0.1:8000/api
set STUDY_PAGE_TOKEN=你自定的串
set STUDY_WEB_BASE_URL=https://xxxx.trycloudflare.com
python backend\scripts\gen_study_tasks.py
```

### 5.4 手机端验证清单
- [ ] 手机（任意网络）打开 `https://xxxx.trycloudflare.com/study-tasks?date=明天` → 弹出口令框，输入 `STUDY_PAGE_TOKEN` 后进入。
- [ ] 勾选一条 → 立即变灰删除线（PATCH 生效）。
- [ ] 在某段底部加一条 → 列表出现（POST /add 生效）。
- [ ] 点标题改字 → 回车保存（PATCH 生效）。
- [ ] 企业微信收到「明日备考科目：英语 · 数学 · 408 · 数据结构 👉 点此查看/编辑」且链接可点。
- [ ] 电脑端 `npm run build` 已通过（本次已验证）；`STUDY_PAGE_TOKEN` 未设时 study 接口 200，设错/漏设 401（本次已 curl 验证）。

### 5.5 方案 B 实操（同 WiFi，当前主用路线）
适用：电脑与手机连**同一个 WiFi**（家庭/公司网）。已在开发机验证链路通过（跨设备那一步需你到同 WiFi 环境补齐）。
- **一键启动**：项目根目录双击 `start_study.bat`（已提供），它会自动开两个窗口分别起后端(8000)与前端(5173)，并提示本机 IP 与口令。脚本里 `STUDY_PAGE_TOKEN` 默认 `guoguo2026`，可自行改；venv 自动优先 `.venv2` 再回退 `.venv`。
- **手机访问**：连同一 WiFi 后，手机浏览器打开 `http://<电脑局域网IP>:5173/study-tasks`，首次输入口令即可增删改。
- **查电脑局域网 IP**：另开 cmd 输入 `ipconfig`，找「无线局域网适配器 WLAN / Wi-Fi」下的 IPv4 地址（形如 192.168.x.x 或 10.x.x.x）。
- **端口冲突**：若 5173 被占用，vite 会自动跳到 5174/5175…，手机访问地址的端口以**前端窗口里 `Network:` 那行显示的实际端口**为准（已在本机验证：5173 与 5174 实例代理均正常返回真实数据）。
- **防火墙**：首次手机访问可能被 Windows 防火墙拦截，弹窗时勾选「专用网络-允许」；若未弹窗需在防火墙高级设置放行 node / 对应端口入站。
- **方糖推送（同 WiFi 版）**：生成器环境设 `STUDY_WEB_BASE_URL=http://<电脑局域网IP>:5173`（注意是局域网地址，**离开同 WiFi 就打不开**）；其余 `SERVERCHAN_KEY / STUDY_API_BASE / STUDY_PAGE_TOKEN` 照常。这样微信里点链接 = 同 WiFi 下打开页面改。
- **本机验证记录**：前后端 + `/api` 代理链路已在开发机实测通过（`/api/health` 200、`/api/study-tasks` 返回真实数据，5173 与 5174 两实例均通）；测试实例已全部清理，端口恢复空闲。
