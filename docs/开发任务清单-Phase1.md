# 工作学习一体化平台 · 开发任务清单（Phase 1 起）

> **范围红线**：Phase 1 = A 档工作闭环（M0 资料底座 / M1 文档中心 / M2 AI 层 / M3 任务管理+报告 / M4 任务分析引擎）+ M7 时间轴/专注。Phase 2 = B 档（学习+奖励），Phase 3 = C 档延后池，D 档砍掉。
> 本清单仅列 **Phase 1 的可执行开发任务**（细化到可开工粒度），Phase 2/3 只给轮廓，D 档不排期。
> 状态：方案/计划阶段，尚未写产品代码。

---

## Phase 1 验收目标
命令面板一句话 → 任务分析引擎拆计划 → 写子任务（截止/紧急/完成度）→ 调豆包生成真实 Office 文件 → OnlyOffice 编辑定稿 → 标记完成 → 专注计时已累计工时 → 自动进周报。**全链路跑通即 MVP 成功。**

---

## 0. 基础设施与脚手架
- [ ] 初始化前端工程：React + TypeScript + Vite + zustand
- [ ] 初始化后端工程：FastAPI + 本地目录结构 + 启动脚本
- [ ] 建 SQLite 库与数据表：`Task` / `PlanAnalysis` / `Doc` / `FocusSession` / `Report` / `Reward`
- [ ] 本地起 OnlyOffice Docs（Docker），前端用官方 SDK 嵌入验证可打开空白 docx
- [ ] 前后端联调环境（Vite dev proxy → FastAPI）

## 1. M2 AI 助手层（优先做，其余模块依赖它）
- [ ] 定义 `LLMProvider` 抽象接口 `chat(messages, tools)`
- [ ] 实现豆包适配器（Volcengine Ark / 对应 SDK）
- [ ] 预留通义 / GLM / Ollama 适配器占位
- [ ] 定义 Function Calling 工具 schema：`create_task` / `write_doc` / `search_kb` / `update_task`
- [ ] 实现工具执行循环（模型返回 tool_calls → 后端执行真实动作 → 结果回灌模型）
- [ ] 接入 RAG：检索资料库 top-k 拼进对话上下文

## 2. M0 资料聚合底座
- [ ] 资料卡片模型 + 入库（标题 / 正文 / 来源 / 向量）
- [ ] 资料库 RAG：sentence-transformers 向量化 + chromadb 存储
- [ ] 全局搜索（SQLite FTS5，跨任务 / 文档 / 对话 / 资料）
- [ ] 网页剪藏：接收正文+截图 POST → 存卡片 → 向量化
- [ ] 统一命令面板（Ctrl/Cmd+K）：意图识别（固定命令 + AI 兜底）→ 分发 action
- [ ] 日历 / 提醒中心：聚合 deadlines + 临近提醒 + 防空洞标记

## 3. M3 任务管理 + 自动报告
- [ ] 任务 CRUD（标题 / 截止 / 紧急 / 重要 / 状态 / 完成度 / parent_id）
- [ ] 四象限优先级计算与展示（重要 × 紧急）
- [ ] 完成度汇总：子任务完成数 → 父任务自动汇总
- [ ] 自动周报：扫描本期 done 任务 + 文档 + 工时 → 分组聚合 → 草稿 → 可改 → 导出 Word/PDF
- [ ] 长期未动任务提醒（防空洞）

## 4. M4 任务分析引擎（核心亮点）
- [ ] 需求澄清：prompt 限定 AI 反问 2–4 个关键约束（目标 / 交付物 / 截止 / 限制）
- [ ] 需求确认卡：AI 复述需求 → 用户拍板
- [ ] 步骤拆解 + 估算：产出有序步骤（描述 / 工期 / 依赖 / 所需资料工具 / 产出）
- [ ] 计划清单：步骤直接生成子任务写入 M3（带 parent_id）
- [ ] 逐步追问：选中步骤 → AI 按风险 / 卡点 / 前置条件三问 → 沉淀 `qa_log` 问题预案

## 5. M1 文档中心
- [ ] OnlyOffice 嵌入：打开 / 编辑 docx/xlsx/pptx，callback 自动回存本地
- [ ] AI 生成文件：豆包产结构化内容 → python-docx / python-pptx / openpyxl 渲染真实 Office → 落盘 → OnlyOffice 打开
- [ ] 版本管理：每次保存时间戳快照，可回滚

## 6. M7 时间轴 / 专注模式
- [ ] 时间轴：任务 / 学习计划拖入日历时间块
- [ ] 专注模式：开始任务 → 计时 + 屏蔽干扰 → 写 `FocusSession`
- [ ] 工时联动：`FocusSession` 数据自动喂给 M3 周报聚合

## 7. 串联与验收（场景 A）
- [ ] 端到端走查：命令面板 → 分析 → 生成 → 编辑 → 完成 → 专注计时 → 周报
- [ ] 写 Phase 1 验收说明 / demo 脚本

---

## Phase 2 轮廓（B 档，暂不展开）
- M5 学习计划：课本入库（PDF/图片解析拆单元）/ 排课（日周月）/ 遗忘曲线复习 / 进度热力图
- M6 奖励系统：积分 / 徽章 / 连续打卡 / 成就复盘视频（matplotlib + moviepy 合成）

## Phase 3 轮廓（C 档延后池）
- 复盘中心 / 个人仪表盘 / 自动化·工作流市场 / AI 长期记忆·用户画像 / 端到端同步与隐私开关 / PWA / Inbox 收集箱

## 红线以下（D 档，不排期）
- OKR 战略层（单人起步过早抽象）/ 成就墙·连胜动画等锦上添花
