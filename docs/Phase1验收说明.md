# Phase 1 验收说明（场景 A 端到端）

> 配套：本验收说明覆盖"项目计划总览 §5.3 串联验收（场景 A）"。  
> 自动化走查脚本：`scripts/verify_scenario_a.py`（31 项断言，全绿；其中 12 项为 Phase 1 收尾四项新能力补强）。  
> 相关设计：M1 文档中心设计与效果、OnlyOffice 部署与回存-避坑指南。

---

## 一、验收目标

Phase 1 = M0+M1+M2+M3+M4+M7 全部收口 **且** 场景 A 全链路跑通，且专注工时自动进周报。

**场景 A（工作闭环·Phase 1 验收）一句话定义**：

> 命令面板说一句"准备周五客户周报" → M4 澄清拆计划 → 子任务写入 M3 → M1 生成真实 Word → OnlyOffice 编辑定稿 → 标记完成 → M7 专注计时累计工时 → 自动进周报。

---

## 二、端到端流程图

```
命令面板(Ctrl+K)
   │ "准备周五客户周报"
   ▼
M4 分析引擎（四阶段状态机）          后端：/api/analysis/{clarify,confirm,decompose,save}
   │ 澄清 → 确认卡 → 拆解步骤 → 保存
   ▼
M3 任务管理                         后端：/api/tasks（主任务+子任务树）
   │
   ▼
M1 文档中心                         后端：/api/docs/generate → 真实 .docx 落盘 → 写 Doc 表(linked_task_id)
   │ OnlyOffice 打开 → 编辑 → 回调回存 → 版本 v2
   ▼
标记完成                            后端：PATCH /api/tasks/{id}{status:done}
   │
   ▼
M7 专注计时                         后端：/api/focus/start → stop（算 duration）
   │
   ▼
周报自动聚合                        后端：/api/reports/weekly（done 任务 + 文档 + focus 工时，零额外录入）
   │
   ├─ ① 报告聚合补文档维度          周报/月报含「本周期文档」段与 doc_count（PRD M3 原要求，此前漏，本次补）
   ├─ ② 防空洞任务提醒              GET /api/tasks/stale?days= 命中久未更新任务 → 前端标灰 + 应用内 toast
   ├─ ③ M7 番茄钟时长配置          GET/PUT /api/settings/focus 读写工作/休息时长，落库跨会话复用
   └─ ④ 报告导出补 PDF             GET /api/reports/export?format=docx|pdf 导出真实 .docx / .pdf
```

---

## 三、分步验收表

| #  | 步骤            | 操作 / 入口                         | 预期结果                                                                                            | 后端接口                                 | 截图位                          |
| -- | ------------- | ------------------------------- | ----------------------------------------------------------------------------------------------- | ------------------------------------ | ---------------------------- |
| 1  | 命令面板入口        | Ctrl+K 输入"准备周五客户周报"             | 命令面板可达、返回有效动作（见 §五 衔接点）                                                                         | `POST /api/ai/command`               | 命令面板弹层                       |
| 2  | M4 澄清         | 进入分析页，输入需求 → "澄清"               | 模型反问 2–4 个关键问题（mock 返回 4 个）                                                                     | `POST /api/analysis/clarify`         | AnalysisPage 阶段①             |
| 3  | M4 确认卡        | 回答反问 → "生成确认卡"                  | 产出结构化需求确认卡（goal/deliverable/deadline…）                                                          | `POST /api/analysis/confirm`         | AnalysisPage 阶段②             |
| 4  | M4 拆解         | "拆解步骤"                          | 产出有序可执行步骤数组                                                                                     | `POST /api/analysis/decompose`       | AnalysisPage 阶段③             |
| 5  | M4 保存         | "保存为任务"                         | 建主任务 + N 个子任务 + 写 plan_analysis                                                                 | `POST /api/analysis/save`            | AnalysisPage 阶段④             |
| 6  | M3 任务树        | 打开任务页                           | 任务树含主任务与全部子任务，父完成度由子汇总                                                                          | `GET /api/tasks`                     | TaskPage 树状列表                |
| 7  | M1 生成 Word    | 分析产物"生成 Word 初稿" / 命令面板"生成周报文档" | 返回真实 `.docx` 且落盘 `data/docs/<id>.docx`，Doc 表含 `linked_task_id`                                  | `POST /api/docs/generate`            | 生成的文件 / DocEditor 弹窗         |
| 8  | OnlyOffice 回存 | 编辑器里改一字 → 保存                    | 后端收到回调、文件回存本地、版本升到 v2                                                                           | `POST /api/docs/callback/{id}`       | OnlyOffice 编辑器（改后保存）         |
| 9  | 标记完成          | 任务节点勾选完成（子任务+主任务）               | 主任务 `completion` 随子任务汇总=100，`status=done`                                                       | `PATCH /api/tasks/{id}`              | TaskPage 完成勾选                |
| 10 | M7 专注计时       | 任务节点 ⏱ → 开始 → 停止                | 返回 session、停止时算出 duration（秒）                                                                    | `POST /api/focus/start` `/stop`      | 右下角专注浮条                      |
| 11 | 周报自动聚合        | 打开周报                            | `done_count` 含已完成任务、`focus_seconds>0` 且 >= 本次专注时长                                               | `GET /api/reports/weekly`            | 周报 Markdown                  |
| 12 | ① 报告文档维度      | 打开周报/月报                         | 报告含「生成文档：N 份」与「## 本周期文档」段，`doc_count>=1`（M1 已生成的 Word 被聚合进本期）                                   | `GET /api/reports/weekly`、`/monthly` | 周报「本周期文档」段                   |
| 13 | ② 防空洞提醒       | 任务页加载                           | `GET /api/tasks/stale?days=7` 命中久未更新（未完成）任务；标记完成后不再命中                                           | `GET /api/tasks/stale`               | 任务树标灰行 + 「🕳 久未更新」标签 + toast |
| 14 | ③ 番茄钟配置       | 右下角专注浮条 ⚙                       | `GET/PUT /api/settings/focus` 读写工作/休息时长并落库；默认值 work=25/break=5                                  | `GET/PUT /api/settings/focus`        | 时长设置入口 + 工作/休息阶段切换           |
| 15 | ④ 报告导出 PDF    | 周报页「导出 PDF」                     | `GET /api/reports/export?type=weekly&format=pdf` 返回真实 .pdf（%PDF 头）；`format=docx` 返回 .docx（PK 头） | `GET /api/reports/export`            | 下载的 .pdf / .docx             |

> **零跳转验证点**：步骤 1→11 全程在同一标签页内闭环，没有"切到另一个软件写文档/记工时/出周报"。这是产品核心价值主张（单空间工作操作系统）。

---

## 四、自动化走查（推荐先跑这个）

`scripts/verify_scenario_a.py` 以无密钥 Mock 模式完整模拟上述 1–11 步，每步断言，结尾清理测试数据（不污染真实库）。

**前置**：后端已在运行（默认 `http://localhost:8000`；可用环境变量 `BASE_URL` 覆盖）。未配 `ARK_API_KEY` 也能跑（走 Mock 兜底）。

```bash
cd backend
# 启动后端（如未运行）
BACKEND_PUBLIC_URL=http://localhost:8000 ONLYOFFICE_PUBLIC_URL=http://localhost:8080 \
  .venv2/Scripts/python.exe -m uvicorn app.main:app --port 8000

# 另开终端跑走查
cd backend
.venv2/Scripts/python.exe ../scripts/verify_scenario_a.py
```

**预期输出**：31 项 `[PASS]`，结尾 `✅ 场景 A 端到端走查全部通过（共 31 项断言）`。

**覆盖范围**：命令面板可达 → M4 四阶段 → M3 任务树含主/子 → M1 真实 docx 落盘 → 模拟 OO 回存 v2 + 文件服务 → 父完成度汇总 100 + 主任务 done → M7 专注时长 → 周报 `focus_seconds>0` 且 `done_count>=1` → **① 周报/月报含文档维度（doc_count + 本周期文档段）→ ② 防空洞任务 `/stale` 命中与完成态退出 → ③ 番茄钟时长 `/settings/focus` 读写落库 → ④ 报告导出 Word(.docx)/PDF(.pdf) 双格式真实文件**。

---

## 五、已知衔接点与限制（验收时注意）

1. **命令面板入口语义**：当前 `POST /api/ai/command` 对"周报"类关键词走 `gen_report`（直接生成周报），而场景 A 的"分析拆解"由 **M4 分析引擎**承载——前端入口是 AnalysisPage（命令面板选择"分析任务"或直接在分析页输入需求）。脚本阶段 1 已记录该实际路由并说明。若希望"准备周五客户周报"直接进 M4 分析流，需在 command 路由里为"分析类周报"加分支（不影响其余验收）。
2. **父完成度汇总口径**：父任务 `completion` 由**子任务的 `completion` 字段**汇总（非 `status`）。标记子任务完成时需同时置 `completion=100`，父任务才会滚到 100%（仅置 `status=done` 不会）。
3. **OnlyOffice 部署坑**：OO 链路有三处地址（前端视角 OO 地址 / OO 服务端视角后端地址 / 后端探活 OO 地址），混用会导致"编辑器打不开 / 保存不回存"。详见《OnlyOffice部署与回存-避坑指南.md》，并用 `GET /api/docs/oo-status` 自检。
4. **周报时长格式**：已修复——短时长（如 5 秒）原会显示成 `0h 0m`，现正确显示 `5s`（`db._fmt_duration`）。
5. **Mock 模式**：无 `ARK_API_KEY` 时各 AI 环节走确定性 Mock（周报直接消费 M3 聚合数据、分析产物转文档骨架），可完整演示，但内容非真实 AI 生成。

---

## 六、前端实操截图位清单（人工走查用）

自动化走查（`verify_scenario_a.py`）只验证了**接口与数据闭环**，界面"是否真的好用、好看、状态正确"仍需在浏览器里点一遍留档。下面这份清单按场景 A 步骤顺序，列出**每个界面该截哪张图、想证明什么**，与 §三 分步验收表一一对应（12–15 行为四项新能力）。

> 用法：启前后端 → 按"界面/入口"逐屏操作 → 截对应状态图存 `docs/screenshots/`（或贴进验收群）→ 对照"想证明"打勾。

| 截图#     | 对应步骤   | 界面 / 入口                              | 要截的状态                                  | 想证明                    |
| ------- | ------ | ------------------------------------ | -------------------------------------- | ---------------------- |
| S1      | 1      | 命令面板弹层（Ctrl+K）                       | 输入"准备周五客户周报"后的候选动作                     | 命令入口可达、返回有效动作          |
| S2      | 2      | AnalysisPage 阶段①                     | M4 反问的 2–4 个澄清问题                       | M4 澄清生效                |
| S3      | 3      | AnalysisPage 阶段②                     | 结构化需求确认卡（goal/deliverable/deadline）    | M4 确认卡产出               |
| S4      | 4      | AnalysisPage 阶段③                     | 有序拆解步骤数组                               | M4 拆解生效                |
| S5      | 5      | AnalysisPage 阶段④                     | "已保存为任务：主任务 + N 子任务"提示                 | M4 保存到 M3              |
| S6      | 6      | TaskPage 树状列表                        | 主任务含全部子任务、父节点显示汇总完成度                   | M3 任务树 + 父完成度计算        |
| S7      | 7      | DocEditor 弹窗 / `data/docs/<id>.docx` | 生成的 Word 初稿内容 + 文件已落盘                  | M1 生成真实 Office 文件      |
| S8      | 8      | OnlyOffice 编辑器                       | 改一字后点保存、版本升到 v2                        | M1 OO 回存 + 版本管理        |
| S9      | 9      | TaskPage 完成勾选                        | 子任务+主任务 `done`、父完成度=100%               | 标记完成 + 父完成度滚算          |
| S10     | 10     | 右下角专注浮条                              | 开始→计时→停止，显示本次时长                        | M7 专注计时                |
| S11     | 11     | 任务页「自动报告」Tab（周报）                     | `done_count`、专注总时长、Markdown 草稿         | 周报聚合（任务 + 工时）          |
| **S12** | **12** | 周报/月报「本周期文档」段                        | `生成文档：N 份` + 文档列表（文件名·类型·关联任务）         | **① 报告补文档维度（审计 #7）**   |
| **S13** | **13** | TaskPage 任务树                         | 久未更新任务行**标灰** + 「🕳 久未更新」标签 + 进页 toast | **② 防空洞任务提醒**          |
| **S14** | **14** | 专注浮条 ⚙ 设置                            | 工作/休息分钟输入框、保存后浮条进入对应阶段并倒计时             | **③ M7 番茄钟时长配置（落库复用）** |
| **S15** | **15** | 周报页「导出 Word / 导出 PDF」                | 两个按钮 + 点击后下载到本地 .docx / .pdf           | **④ 报告导出双格式**          |

> 提示：S12–S15 为 Phase 1 收尾四项新能力，是本次相比早期验收新增的人工走查点；自动化走查已覆盖其接口层（见 §四），此处补"界面可见性"一票。

---

## 七、Phase 1 验收结论

- M0 / M1 / M2 / M3 / M4 / M5(提前) / M7 功能件全部齐备；
- 场景 A 全链路（1→15 步）经自动化走查 **31/31 通过**，且"专注工时自动进周报"成立；
- Phase 1 收尾四项新能力（① 报告文档维度 ② 防空洞提醒 ③ 番茄钟配置 ④ 报告导出 PDF）已全部接入并随场景 A 走查验证；
- 此前计划的"硬偏离"（报告导出/落库/文档维度，见《阶段技术约束一致性审计》#5/#6/#7）至此全部修正，仅余 RAG 语义栈 + zustand 两处有意 MVP 取舍记录在案；
- 剩余非阻塞项（命令面板→M4 入口语义优化）列入 P1/P2，不影响 Phase 1 验收。

