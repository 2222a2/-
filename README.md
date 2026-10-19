# 工作学习一体化平台（WorkLearn）

> 定位：单空间工作操作系统——“零跳转”闭环「想 → 拆 → 做 → 记 → 学 → 奖」。
> 当前进度（2026-10-16 核对）：**Phase 0 脚手架 ✅ + M2 AI 助手层 ✅ + M0 资料聚合底座 ✅ + M3 任务管理+周报 ✅ + M4 分析引擎 ✅ + M5 学习计划（后端+前端基础版，Phase 2 提前）✅**。
> **Phase 1 验收最大缺口：M1 文档中心（仅 OnlyOffice config 骨架，AI 生成 Office + 回调回存未做）、M7 专注模式（无计时 API/前端）。** 完整进度盘点见 `docs/项目计划总览与待办清单.md`。

## 目录结构
```
worklearn-platform/
├── backend/                 # FastAPI 后端（本地优先）
│   ├── app/
│   │   ├── main.py          # 应用入口：CORS + /api/health + 启动建库 + 挂载 /api/ai 与 /api/knowledge
│   │   ├── config.py        # 路径/CORS/AI/OnlyOffice/RAG 配置（全走环境变量）
│   │   ├── db.py            # SQLite 连接 + 建表(7张业务表+FTS5) + 写库/搜索 helper（含短查询 LIKE 兜底）
│   │   ├── schemas.py       # Pydantic 请求/响应模型（API 契约边界）
│   │   ├── onlyoffice.py    # 生成 OnlyOffice 编辑器 config
│   │   ├── knowledge.py     # ★ M0 资料聚合底座：统一入库流水线 ingest_card + 4 通道接口
│   │   └── ai/              # ★ M2 AI 助手层
│   │       ├── provider.py  #   LLMProvider 抽象 + MockProvider(离线) + get_provider 工厂
│   │       ├── doubao.py    #   豆包(Volcengine Ark) OpenAI 兼容适配器
│   │       ├── tools.py     #   ToolRegistry + 基础工具(create_task/list_tasks/search/remember)
│   │       ├── agent.py     #   工具执行循环 run_agent（MAX_ITER + 结果回灌）
│   │       ├── rag.py       #   Retriever 抽象 + FTS5兜底 + chromadb写入端(index_into_chroma) + 可选语义检索
│   │       └── router.py    #   /api/ai/{status,chat,agent,command}（命令面板规则+AI混合路由）
│   ├── scripts/test_m2.py   # M2 离线自测（MockProvider 跑通整条链路）
│   ├── requirements.txt     # openai + httpx + python-multipart；chromadb/readability/pdfplumber/python-docx 为可选
│   ├── .env.example         # 复制为 .env 填 ARK_API_KEY 等
│   └── data/                # 运行时生成：app.db（SQLite）+ docs/ + uploads/（上传留档）
├── frontend/                # React + TS + Vite 前端
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx          # 首页 + 左侧导航 + 全局挂载命令面板
│   │   ├── api/client.ts    # axios 实例 + knowledge / command API
│   │   └── components/
│   │       ├── DocEditor.tsx    # OnlyOffice 编辑器组件（懒加载）
│   │       ├── CommandPalette.tsx  # ★ M0 统一命令面板（⌘/Ctrl+K 全局唤起）
│   │       └── KnowledgePage.tsx   # ★ M0 资料库页面（剪藏/笔记/上传/列表/搜索/删除）
│   ├── vite.config.ts       # 含 /api 代理到后端 127.0.0.1:8000
│   └── package.json
└── docker-compose.yml       # 本地 OnlyOffice Docs 服务（端口 8080）
```

## M2 AI 助手层（已完成）
- **可插拔模型**：`LLMProvider` 抽象统一 `chat()`；豆包走 OpenAI 兼容协议（改 base_url 即可），预留通义/GLM/Ollama。
- **离线可用**：未配 `ARK_API_KEY` 时自动用 `MockProvider`，整条工具循环无需网络即可联调/测试。
- **工具循环**：`run_agent()` 实现「模型决策 → 真实执行 → 结果回灌 → 继续」闭环，带 `MAX_ITER` 防失控、`tool_call_id` 严格回查、异常包成结构化错误。
- **工具注册表**：`@tool` 装饰器一处注册 schema+实现；当前已带 `create_task / list_tasks / search_knowledge / remember`，M3/M4/M1 直接加工具即可被 AI 调度。
- **RAG**：`Retriever` 抽象，默认 `SqliteFtsRetriever`（FTS5 trigram，开箱即用），装 chromadb 后设 `RAG_BACKEND=chromadb` 即获语义向量检索。
- **接口**：`GET /api/ai/status`、`POST /api/ai/chat`、`POST /api/ai/agent`、`POST /api/ai/command`。
- **自测**：`backend> .venv2/Scripts/python.exe scripts/test_m2.py` 验证「记得住/搜得到/建任务」全链路。

## 数据库（SQLite 单文件）
| 表 | 作用 |
|----|------|
| `task` | 任务，parent_id 自引用实现子任务，urgency×importance 组合四象限 |
| `plan_analysis` | M4 分析引擎产物：需求确认卡 / 步骤 JSON / 逐步追问日志 |
| `doc` | 生成的 Office 文件（word/excel/ppt）+ 版本快照 |
| `focus_session` | M7 专注计时（start/end/duration），工时喂周报 |
| `report` | 自动周报/月报 |
| `reward` | 积分/徽章/视频 |
| `knowledge_card` | 资料卡片（剪藏/上传/任务文档/笔记） |
| `search_index` | FTS5 trigram 全文索引，统一检索 task/doc/card |

## 本地运行
```bash
# 1. 后端
cd backend
# ⚠️ 虚拟环境用 .venv2（不是 .venv）：原 .venv 曾因 Python 版本错配损坏且被本机文件监视器锁死句柄，
#    在当前会话内无法删除/重建（WorkBuddy 沙箱回收站不可用会拦截所有删除操作）。
#    重启用 WorkBuddy 释放句柄后，可把 .venv2 改名回 .venv、清掉坏目录。
.venv2/Scripts/activate
pip install -r requirements.txt
cp .env.example .env        # 填入 ARK_API_KEY 等
uvicorn app.main:app --host 127.0.0.1 --port 8000
#   → http://127.0.0.1:8000/api/health

# 2. 前端（另开终端）
cd frontend
npm install
npm run dev                 # 已配置 host=127.0.0.1
#   → http://127.0.0.1:5173/

# 3. OnlyOffice（可选，Phase 1 M1 才真正用）
# docker compose up -d       # → http://localhost:8080
```
前端所有 `/api/*` 请求经 Vite 代理转发到后端 8000，天然同源、免跨域。

## M0 资料聚合底座（已完成）
- **统一入库流水线** `ingest_card()`：所有来源都走「写 SQLite 卡片 → 同步进 FTS5 全文索引 →（可选）向量化进 chromadb」，保证“入库即可被搜到、可被 AI 引用”。
- **四个入库通道**：① 网页剪藏 `POST /api/knowledge/clip`（后端 requests 抓正文，readability 优先、正则降级）；② 文件上传 `POST /api/knowledge/uploads`（txt/md 直读，pdf/docx 用可选库抽取，原始文件落 `data/uploads/` 留档）；③ 手动笔记 `POST /api/knowledge/notes`；④ 任务文档（M1 定稿时调用，本模块提供能力）。
- **检索**：`GET /api/knowledge?q=` 站内搜索 + `GET /api/knowledge/` 列表 + `GET /{id}` 详情 + `DELETE /{id}` 删除（同步清理 FTS 与向量）。
- **短查询兜底**：FTS5 trigram 对 <3 字符（两字中文）无效，已加 `LIKE` 子串兜底（`search_cards` / `search_kb`），中文短词也能搜到。
- **向量写入端**：`rag.py` 新增 `index_into_chroma()`，补齐之前“只能查不能存”的缺口；`RAG_BACKEND=chromadb` 时自动同步向量，未装则静默降级到 FTS。
- **统一命令面板（前端）**：`CommandPalette.tsx`（⌘/Ctrl+K 全局唤起）→ 后端规则+AI 混合路由 → 本地执行（建任务/搜资料/记笔记/生成报告）。`remember` 工具已改走 `ingest_card` 同步向量。
- **自测**：后端实测「笔记→搜索(2字/3字)→上传→删除」全链路通过；前端 `vite build` 88 模块编译通过。

## 下一步（Phase 1 剩余，按依赖顺序）
> 完整进度盘点与待办见 `docs/项目计划总览与待办清单.md`。M3/M4 已随代码实现完成，下面只列 Phase 1 验收还差的块。

1. ~~**M2 AI 层**~~ ✅ 已完成（LLMProvider + 豆包适配器 + 工具循环 + RAG 接入）
2. ~~**M0 资料底座**~~ ✅ 已完成（统一入库流水线 + 4 通道 + FTS/向量检索 + 命令面板）
3. ~~**M3 任务 + 报告**~~ ✅ 已完成（CRUD/树/父完成度汇总 + 周报草稿，已聚合 focus_session）
4. ~~**M4 分析引擎**~~ ✅ 已完成（四阶段状态机 clarify/confirm/decompose/save/qa）
5. **M1 文档中心（🟡→✅）**：AI 生成真实 Office（python-docx/pptx/openpyxl）→ OnlyOffice 回调回存 → 版本管理（当前仅 config 骨架）
6. **M7 专注模式（🔴→✅）**：专注计时 API(start/stop 写 FocusSession) + 前端计时组件（周报已能读 focus_session）
7. **M5 学习计划**：后端已提前实现（study_tasks.py + StudyTasksPage），待补遗忘曲线复习 / 进度热力图
8. **串联验收**：场景 A 全链路走查（命令面板 → 分析 → 生成 → 编辑 → 完成 → 专注计时 → 周报）
