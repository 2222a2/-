# Phase 2 实施方案 · M5 收尾（45%→100%）+ M6 奖励系统（10%→可用）

> 本文是 Phase 2 的「单一可执行方案」。所有改动都建立在已核实的代码现实上（见《项目计划总览与待办清单》§4 + 本次代码核对）。
> 铁律（PRD §2）：任何新需求先过「是否减少一次软件切换 / 一次找资料」，否则进 C/D 档。本方案全程**复用 `study_task`/`focus_session`/`task` 数据，不造数据孤岛、不新建推送服务、端口维持 8000 不变**。

---

## 0. 目标与验收总览

| 模块 | 当前 | 目标 | 核心交付 |
|---|---|---|---|
| **M5 遗忘曲线** | 0% | ✅ | 学完自动插 1/2/4/7/15 天复习节点 + 今日待复习提醒 |
| **M5 进度热力图** | 0% | ✅ | 日历热力图（按日完成率着色） |
| **M5 排课 UI** | ~30% | ✅ | 月历视图（看/点进排课）+ 周模板可视化编辑 |
| **M6 积分/经验/等级** | 0% | ✅ | `reward_account` 聚合表 + CRUD + 行为钩子累加 |
| **M6 徽章** | 0% | ✅ | `reward_badge` 表 + 自动判定（连续打卡/完成等） |
| **M6 打卡** | 0% | ✅ | `reward_checkin` 表 + 连续天数 + 打卡积分 |
| **M6 复盘视频激励** | 0% | ✅ 已实现 | matplotlib+moviepy 合成 mp4（见 §3.4 / §8.5） |

> 注：M5 遗忘曲线已有完整设计《M5遗忘曲线复习-实现方案.md》，本方案**直接采纳，不再重写**，仅列落地清单 + 衔接点。

---

## 1. 当前状态盘点（代码核实）

**M5 已有（可直接复用）**
- `backend/app/db.py`：`study_task` 表 + `upsert_study_tasks_for_date / list_study_tasks / patch_study_task / add_study_task / delete_study_task / weekly_progress` + `migrate_schema()`（幂等补列）。
- `backend/app/study_tasks.py`：`POST /`(批量建) / `GET /`(date|week) / `PATCH /{id}` / `DELETE /{id}` / `POST /add` / `GET /weekly`，统一 `verify_study_token` 依赖。
- `backend/app/schemas.py`：`StudyTaskOut` / `WeeklyProgressOut`。
- `frontend/src/components/StudyTasksPage.tsx`：日视图（按 morning/noon/evening 分组增删改）+ 周进度视图（完成率条/各科/每日小条）。`?date=` 深链已支持。
- `frontend/src/api/client.ts`：`study` 接口对象，`X-Study-Token` 头自动带。

**M5 缺口**
- 遗忘曲线：无 `review_of/review_stage/due_offset` 列、无生成/查询算法、无 UI 提醒。
- 热力图：无「按日期区间聚合完成率」的接口与组件。
- 排课 UI：只有日/周，缺**月历视图**；且「每周默认排课」硬编码在 `backend/scripts/gen_study_tasks.py` 的 `DEFAULT_TEMPLATE`，前端不可配。

**M6 现状（极薄）**
- `db.py` 仅有空壳 `reward(id, points, badges_json, videos_json, created_at)`（`AUTOINCREMENT`，并非设计稿里 `CHECK(id=1)` 的单行约束），**无 router、无 schema 完整性、无逻辑**。
- 缺：积分累加钩子、徽章判定、打卡、复盘视频，以及对应的前端页。

**依赖现状（重要 · 2026-10-19 复核）**
- ⚠️ 本仓库**已无 `.venv2`**（旧记忆里的"一律用 .venv2"已失效）。当前可用解释器：
  - 起后端 / uvicorn：`C:\Users\用户\.workbuddy\binaries\python\envs\default\Scripts\python.exe`（已装 fastapi/uvicorn/pydantic，可直接 `import app.main` + `uvicorn.run`）。
  - 仅用 stdlib 的校验脚本：`C:\Users\用户\.workbuddy\binaries\python\versions\3.13.12\python.exe`。
- 复盘视频所需 `matplotlib` + `moviepy` 尚未安装（见 §3.4 / §6 风险）。**注意**：装包必须进上面的 `envs/default` venv，系统 Python 的 matplotlib 不算数。

---

## 2. M5 收尾

### 2.1 遗忘曲线（艾宾浩斯复习提醒）— 采纳既有方案

直接按 `docs/M5遗忘曲线复习-实现方案.md` 落地，落地清单：

| 文件 | 改动 |
|---|---|
| `db.py` | `study_task` 建表补 3 列 `review_of/review_stage/due_offset`（`migrate_schema` 里幂等 `ALTER`）；新增 `spawn_reviews_for_task(task_id)` + `list_due_reviews(date_str)` + `get_study_task_done(task_id)` |
| `study_tasks.py` | `PATCH /{id}` 在 `done 0→1` 时调 `spawn_reviews_for_task`；新增 `GET /reviews/due?date=` |
| `schemas.py` | `StudyTaskOut` 加 `review_of / review_stage / due_offset` 字段 |
| `StudyTasksPage.tsx` | 顶部「今日待复习」卡片（调 `/reviews/due`）+ 列表里 `source==='review'` 加「复习」chip/底色 |

关键决策（沿用原 doc，不再赘述）：触发点选 `done 0→1`（非新建时）；幂等 DELETE 再插（永远 5 条）；复习任务 `done=1` 不连锁；复用 `period/subject` 排回原时段。
验收口径沿用原 doc §7（1–5 条）。

### 2.2 学习进度热力图

**思路**：GitHub 风格日历热力图，横轴日期（默认最近 90 天，可切「本月/近一月」），纵轴周一~周日，颜色深浅 = 当日完成率。复用 `study_task` 的 `done` 聚合，**不新增表**，只加一个区间聚合函数 + 一个接口。

**`db.py` 新增**
```python
def daily_completion_map(start: str, end: str) -> list[dict]:
    """返回 [start, end] 区间内每天的 {date, total, done, rate}，无任务的日子 rate=0。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, COUNT(*) AS total, SUM(done) AS done "
        "FROM study_task WHERE date>=? AND date<=? GROUP BY date",
        (start, end),
    ).fetchall()
    conn.close()
    m = {r["date"]: (r["total"], r["done"] or 0) for r in rows}
    out, d = [], datetime.strptime(start, "%Y-%m-%d")
    while d.strftime("%Y-%m-%d") <= end:
        ds = d.strftime("%Y-%m-%d")
        total, done = m.get(ds, (0, 0))
        out.append({"date": ds, "total": total, "done": done,
                    "rate": round(done / total, 3) if total else 0.0})
        d += timedelta(days=1)
    return out
```

**`study_tasks.py` 新增**（沿用 `verify_study_token`）
```python
@router.get("/heatmap", response_model=list[schemas.DailyCompletionOut])
def heatmap(start: str, end: str):
    return db.daily_completion_map(start, end)
```
`schemas.py` 加 `DailyCompletionOut(date, total, done, rate)`。

**前端**：`StudyTasksPage.tsx` 增加第三个 tab「热力图」，新增 `StudyHeatmap` 子组件（CSS grid 渲染，色阶用 `#185FA5` 透明度映射 rate；hover 显示「x/y 完成」）。数据走 `study.heatmap(start, end)`（在 `client.ts` 的 `study` 对象加一个方法，同样带 `X-Study-Token`）。

**验收**：进入热力图 tab → 显示最近 90 天网格；某天有 5 任务完成 3 → 该格中深色 + hover「3/5」；点某格 → 跳到该日 day 视图（复用 `setDate`）。

### 2.3 排课 UI（日 / 周 / 月 + 周模板）

**核心 = 月历视图**（让 PRD「排课(日/周/月)」真正闭环）：
- `StudyTasksPage.tsx` 加「月」tab，渲染**当月日历 grid**（7 列×约 5 行）。每格显示：日期 + 当日完成率底色（复用 `daily_completion_map` 取当月区间）+ 任务数角标。
- 点击某天 → `setDate(那天)` 并切回 day 视图（排课/增删改已在 day 视图具备）。这样「月看全局 → 点某天排细节」形成闭环。
- 月视图数据：复用 §2.2 的 `/heatmap` 接口取整月区间即可，无需新接口。

**增强 = 周模板可视化编辑**（把硬编码 `DEFAULT_TEMPLATE` 收进后端，标 P1，可后置）：
- `app_settings` 存 `weekly_template_json`（结构：`{mon:[{period,subject,title}...], tue:[...], ...}`）。
- `study_tasks.py` 加 `GET/PUT /template`（沿用 token）。`gen_study_tasks.py` 改为：优先 `GET /template`，拿不到才用内置 `DEFAULT_TEMPLATE` 兜底。
- 前端「排课」页加一个模板编辑器（7 天 × 时间段，勾选科目/填标题），保存即写 `app_settings`。
- 价值：让「排课」从「只能看」升级为「能配」，真正对应 PRD 的"排课"。

**里程碑建议**：月视图先落地（必做），周模板编辑作为 2.3b 后置（明确标 P1，不阻塞验收）。

---

## 3. M6 奖励系统（从零）

### 3.1 Schema 重设计

弃用空壳 `reward` 表，改为「聚合账户 + 流水维度表」，贴合项目「一概念一表」惯例，且支持审计/徽章判定：

```sql
-- 积分/经验/等级聚合（单人，固定 id=1）
CREATE TABLE reward_account (
    id        INTEGER PRIMARY KEY CHECK (id=1),
    points    INTEGER DEFAULT 0,
    exp       INTEGER DEFAULT 0,
    level     INTEGER DEFAULT 1,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- 连续打卡
CREATE TABLE reward_checkin (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    checkin_date TEXT UNIQUE,                -- YYYY-MM-DD
    created_at   TEXT DEFAULT (datetime('now'))
);

-- 已得徽章
CREATE TABLE reward_badge (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    badge_key TEXT UNIQUE,                  -- streak_7 | first_review | study_done_100 ...
    name      TEXT,
    desc      TEXT,
    icon      TEXT,                         -- emoji
    earned_at TEXT
);

-- 复盘视频
CREATE TABLE reward_video (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT,
    file_path    TEXT,
    period_label TEXT,                      -- "2026-10 月度复盘"
    created_at   TEXT DEFAULT (datetime('now'))
);

-- 积分流水（审计/排错）
CREATE TABLE reward_event (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type   TEXT,                      -- checkin | study_done | review_done | badge
    ref_id       INTEGER,
    points_delta INTEGER DEFAULT 0,
    exp_delta    INTEGER DEFAULT 0,
    note         TEXT,
    created_at   TEXT DEFAULT (datetime('now'))
);
```

**迁移策略（幂等、安全）**：旧 `reward` 表当前**无业务数据**（仅建表），`migrate_schema()` 里用 `try/except`：若 `reward` 表存在则 `DROP TABLE reward`（老库无数据，安全），再建上述 5 张新表；新库直接建。首次调用 `init_reward_account()` 写入 `(id=1)` 初始行。

### 3.2 后端：`db.py` + `reward.py`

**`db.py` 新增函数**
- `init_reward_account()`：确保 `reward_account` 有 id=1 行。
- `add_reward(points_delta, exp_delta, event_type, ref_id, note)`：更新 `reward_account`（points/exp/level），写 `reward_event` 流水，返回最新 state。
- `get_reward_state()`：返回 `{points, exp, level, streak, badges:[...], last_video:...}`。
- `checkin_today()`：若今日未打卡则 INSERT；计算连续天数（从 `reward_checkin` 倒推连续）；给打卡积分；返回 `{streak, checked_today, new_badges}`。
- `compute_level(exp)`：经验→等级（阈值表，如 `[0,100,300,600,1000,1500,...]`，超过末值每 500 一级）。
- `evaluate_badges()`：基于当前状态/累计量判定应得徽章（见下），返回新获得列表并落 `reward_badge`。
- `list_badges()` / `grant_badge(key)` / `list_videos()` / `insert_video(...)`。

**徽章判定规则（首批，可扩展）**
| badge_key | 触发条件 | 积分奖励 |
|---|---|---|
| `first_checkin` | 首次打卡 | +20 |
| `streak_3` / `streak_7` / `streak_30` | 连续打卡达 3/7/30 天 | +30 / +80 / +300 |
| `first_study_done` | 首次完成学习任务 | +10 |
| `study_done_100` | 累计完成学习任务 ≥100（数 study_task done 总数） | +200 |
| `first_review_done` | 首次完成复习任务 | +15 |
| `level_5` | 等级达 5 | +500 |

> ⚠️ **实际落地与本节设计有偏差（2026-10-19 实测，以 `db.py` 代码为单一事实来源）**：
> - 实际徽章键名为 `first_task` / `first_review` / `streak_3` / `streak_7` / `streak_30` / `points_100` / `points_500`（见 `db.py` 的 `BADGES` 常量），**不存在** `first_checkin` / `first_study_done` / `study_done_100` / `level_5`。
> - 积分常量：`REWARD_TASK=5`、`REWARD_REVIEW=3`、`REWARD_CHECKIN=2`、`LEVEL_STEP=100`（每 100 分升 1 级）；**徽章本身不再额外加分**——积分只在 task/review/checkin 三个钩子里累加。
> - `POST /api/reward/checkin` 实际返回 `{ok, already, state}`（state 为最新 `get_reward_state()`），不是设计稿的 `{streak, checked_today, new_badges}`。
> - `get_reward_state()` 额外返回 `all_badges`（7 枚 + `earned` 标记 + `earned_at`），供前端徽章墙一次请求区分已得/未得。
> 验收口径见 §6 与 §8，以实际代码为准。

**行为钩子（关键衔接）**
- `study_tasks.py PATCH /{id}`：`done 0→1` 时 → `db.add_reward(+5,+10,'study_done',task_id)` + `evaluate_badges()`；若 `source==='review'` 额外 `+3` 并触发 `first_review_done`。
- `reward.py POST /checkin`：`db.checkin_today()`（内部已含积分+徽章）。
- 上述钩子与 M5 遗忘曲线 `done 0→1` 触发点**共用同一处**，互不冲突（复习完成既有复习节点逻辑、又走奖励累加）。

**`reward.py` 路由**（挂 `/api/reward`，**不加 X-Study-Token**——属主应用个人成就页，本地优先默认无鉴权，与全局一致）
```python
GET  /api/reward                      -> get_reward_state()            # 积分/等级/连续/徽章/最近视频
POST /api/reward/checkin              -> checkin_today()               # 今日打卡
GET  /api/reward/badges               -> list_badges()
POST /api/reward/video/generate       -> 生成复盘视频（见 3.4）
GET  /api/reward/video                -> list_videos()
GET  /api/reward/video/{id}/file      -> 静态文件服务（播放用）
```
`main.py` 加 `from . import reward; app.include_router(reward.router)`。

### 3.3 前端：`RewardPage.tsx` + `client.ts` + `App.tsx`

- `client.ts`：新增 `reward` 接口对象（`get / checkin / badges / generateVideo / listVideos`）。
- `App.tsx`：侧边栏加「🏆 奖励」入口（`type Page` 加 `'reward'`，渲染 `<RewardPage/>`）。
- `RewardPage.tsx` 组件：
  1. **积分卡**：points + 等级 + 经验条（`exp` 相对下一级进度）。
  2. **连续打卡**：🔥 当前连续 N 天 + 「今日打卡」按钮（点了调 `checkin`，禁用态显示已打卡）。
  3. **徽章墙**：已得高亮（emoji+name+desc），未得灰显（从一份内置 BADGE_CATALOG 渲染，标注「未解锁」）。
  4. **复盘视频**：「生成本月复盘视频」按钮 → 调 `generateVideo` → 轮询/直接返回 `<video src=... controls>` + 历史列表（点击播放）。

### 3.4 复盘视频（matplotlib + moviepy）

**流程**：`POST /api/reward/video/generate`
1. 拉取本期（默认本月）数据：`weekly_progress`/本期 done 任务清单、`get_reward_state`（积分/徽章/连续）、`list_badges`。
2. 用 **matplotlib**（Agg 后端）逐帧渲染：① 标题页「2026-10 月度复盘」② 完成清单滚动 ③ 进度曲线（复用 `daily_completion_map`）④ 徽章墙 + 积分总结。
3. 用 **moviepy** 把帧合成为 `data/videos/review_<timestamp>.mp4`（可加背景音乐占位/字幕）。
4. `insert_video(...)` 落库，`GET /{id}/file` 走 `FileResponse` 返回。

**依赖安装（必须，进 .venv2）**
```bat
cd backend
.venv2\Scripts\pip install matplotlib moviepy
```
> 注：moviepy 会拉 numpy/imageio 等；若体积/装包失败，见 §6 降级方案。

**降级方案（保底，先出一版）**
- 若 moviepy 装不上：先用 matplotlib 生成「复盘卡片」单图（PNG，已能体现完成清单+进度+徽章），前端直接展示图片；多帧 GIF 可用已装的 `PIL`（`Image.save(..., save_all=True)`）合成，零新依赖。
- 视频合成（mp4）标为 P1 增强，不影响「复盘激励」主链路（卡片/ GIF 即可激励）。

---

## 4. 执行顺序与里程碑（建议）

| 里程碑 | 内容 | 改动文件 | 估时 |
|---|---|---|---|
| **M1** | M5 遗忘曲线（采纳既有 doc） | db.py / study_tasks.py / schemas.py / StudyTasksPage.tsx | 0.5d |
| **M2** | M5 热力图 | db.py(`daily_completion_map`) / study_tasks.py(`/heatmap`) / schemas.py / StudyTasksPage.tsx(Heatmap) / client.ts | 0.5d |
| **M3a** | M5 排课月视图 | StudyTasksPage.tsx(月 tab) / client.ts | 0.5d |
| **M3b** | M5 周模板编辑（P1 后置） | app_settings + study_tasks.py(`/template`) + gen_study_tasks.py + 前端模板编辑器 | 0.5d |
| **M4** | M6 schema 迁移 + db/router CRUD | db.py(5 表+函数) / reward.py / main.py / migrate | 1d |
| **M5** | M6 前端页 + 打卡 + 徽章 + 钩子 | RewardPage.tsx / client.ts / App.tsx / study_tasks.py 钩子 | 1d |
| **M6** | M6 复盘视频 | reward.py(generate) + 装 matplotlib/moviepy + 前端播放 | 1d |

> 每里程碑配一个 `scripts/verify_phase2_*.py`（仿 `scripts/verify_*.py` 风格：起实例 → curl/内部调用 → 断言），保证「动了不破」。

---

## 5. 风险与约定

- **依赖**：`matplotlib`+`moviepy` 必须装进 `.venv2`（项目运行环境）；系统 Python 的 matplotlib 不算数。装包失败走 §3.4 降级。
- **不碰端口/不引推送**：后端固定 8000，奖励页走主应用 CORS，无新增鉴权。
- **不造数据孤岛**：M6 只聚合 `study_task`/`reward_checkin` 等已有数据，行为钩子复用 `done 0→1` 单一触发点。
- **迁移安全**：旧 `reward` 表无数据，`migrate_schema` 用 try/except DROP 重建，幂等。
- **复盘视频观感**（PRD 已知风险）：先出一版固定模板，后续调字体/配乐/转场。
- **降级不阻塞**：moviepy 缺失时，复盘以「卡片图 / GIF」交付，mp4 合成后置。

---

## 6. 验收口径总表

**M5**
1. 勾选某学习任务 `done 0→1` → 响应含 `reviews_spawned:5`；未来 1/2/4/7/15 天各出现一条 `source='review'` 任务（沿用《M5遗忘曲线》§7）。
2. 打开「热力图」tab → 最近 90 天网格着色正确，hover 显示 x/y；点格跳该日。
3. 打开「月」tab → 当月日历每格显示完成率底色；点某天进入 day 视图可排课。
4. （P1）周模板编辑器保存后，次日生成器按新模板建任务。

**M6**
1. `GET /api/reward` 返回初始 `{points:0, exp:0, level:1, streak:0, badges:[]}`。
2. 完成一个学习任务（done 0→1）→ points+5，且 `first_task` 徽章入账（设计稿曾写 `first_study_done`，实际键名见 §3.2 偏差说明）。
3. `POST /api/reward/checkin` 连续两天 → `streak=2`；第 7 天 → `streak_7` 徽章 + 积分。
4. `POST /api/reward/video/generate` → 返回 video id + `file_url`，`GET /{id}/file` 可播放（FileResponse mp4）；历史列表可见。已实测：临时库种子跑通，产出合法 mp4（~127KB），`get_video` 落库一致。
5. 前端奖励页：积分卡/连续打卡/徽章墙/复盘视频四块均正常交互（视频区为 `<video>` 内联播放器 + 下载链接）。

---

## 7. 衔接与后续

- 本方案与《M5遗忘曲线复习-实现方案.md》《study-tasks-extension.md》互补，不重复。
- M6 行为钩子与 M5 遗忘曲线 `done 0→1` 触发点同一处，落地时注意合并而非各写一遍。
- Phase 2 验收 = PRD 场景 B 跑通（上传/排课 → 打卡 → 复习提醒 → 复盘视频）。
- 复盘中心/仪表盘/社交分享卡等进 Phase 3（C 档），本方案不展开。

---

## 8. 落地排查记录（2026-10-19）

> 本轮把 M6 奖励系统前后端落地并起前端预览复验，过程中踩到几个坑，记录于此供后续会话避坑。

### 8.1 `/api/reward` 返回 404 ≠ 代码 bug（端口旧的进程作祟）
- 现象：起服务后 `GET /api/reward` 报 404，第一反应是 `reward` 路由没挂上。
- 排查：`app.openapi()` 明确列出了全部 5 条 reward 路由（`GET /api/reward`、`POST /api/reward/checkin`、`GET /api/reward/badges`、`GET /api/reward/video`、`POST /api/reward/video/generate`）→ **代码本身正确，路由确实挂上了**。
- 真因：**8000 端口上跑着一个没有 reward 路由的旧进程**，新 server 抢不到端口直接退出，curl 命中的是旧进程。
- 结论：**重启你正式的 8000 后端**后 reward 路由会正常，无需改代码。预览时改用 8011（后端）+ 5174（前端 Vite，代理 8011）绕开旧进程即可。

### 8.2 FastAPI 0.115 `include_router` 的 `.path` 假阴性（调试陷阱）
- `app.include_router(...)` 会把路由包成 `_IncludedRouter`，该对象**没有 `.path` 属性**。
- 因此 `for r in app.routes: print(r.path)` 遍历到的挂载路由 `.path` 全是空，**看起来像没挂上，实际已挂**——这是假阴性。
- 正确查已挂载路由的方式：用 `app.openapi()`（展开全部 path），或深入 `_IncludedRouter.routes`。别再被这个坑误导。

### 8.3 预览用临时种子库，绝不碰真实 `app.db`
- `DB_PATH` 硬编码到 `backend/data/app.db`，不希望预览数据污染真实库。
- 做法：在启动脚本里 `db.DB_PATH = tempfile.mktemp(suffix='.db')` + `db.init_db()`（注意是 `init_db()` 建完整 SCHEMA，不是 `migrate_schema()`——后者假设基础表已存在，裸跑会报缺表），再 `add_reward_event` / `evaluate_badges` / `checkin_today` 塞种子。
- 这样🏆页能渲染出"已解锁 3 枚徽章 + 连续 3 天"的真实填充态，而真实库零改动。
- 前端转译校验：`npx esbuild --bundle --external:react --external:react-dom --external:axios`（或对一个 `.tsx` 入口）能快速发现 import/类型错误，不必起完整 dev server。

### 8.4 环境 / 运行约定（更新）
- `.venv2` 已不存在（见 §1）。后端起服务用 `…\python\envs\default\Scripts\python.exe`；纯 stdlib 校验用托管 `…\python\versions\3.13.12\python.exe`。
- 前端 `node_modules` 完好，可直接 `vite` 校验 / 起 dev server。

### 8.5 复盘视频 #6 已落地（2026-10-19）
- 依赖：`envs/default` venv 装 `matplotlib==3.11.1` + `moviepy==2.2.1`（自带 imageio_ffmpeg，捆绑 ffmpeg，无需系统 ffmpeg）。
- 实现：新增 `backend/app/video_gen.py` 的 `generate_review_video(days=30)`，matplotlib(Agg) 渲 5 帧（封面 / 近 30 天完成率 / 本周各科 / 徽章墙 / 结尾），moviepy 合 1920×1080 mp4（libx264，无音轨，每帧 2.5s），落 `data/videos/review_<ts>.mp4` 并 `db.insert_video`，返回 `file_url=/api/reward/video/{id}/file`。
- 路由：`reward.py` 的 `POST /api/reward/video/generate` 调 `video_gen`（缺依赖返回 `{ok:False,error}`）；新增 `GET /api/reward/video/{vid}/file` 用 `FileResponse` 播 mp4；`db.get_video(vid)` 取路径。
- 中文：走 `C:/Windows/Fonts/msyh.ttc`（微软雅黑）；**emoji(🏅🔒🚀) 在该字体缺字形会成方框**，已改用 ★/☆ + 「已解锁/未解锁」文字表达。
- 验证：临时库种子端到端跑通 → 合法 mp4(~127KB)、`get_video` 落库一致（VERIFY PASS，无 glyph 警告）；前端 esbuild 编译通过；`app.openapi()` 确认 6 条 reward 路由含 `video/generate` 与 `video/{vid}/file` 已挂载。
