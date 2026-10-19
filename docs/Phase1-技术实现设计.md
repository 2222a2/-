# Phase 1 技术实现设计（回答 9 个实现问题）

> 范围：Phase 1（A 档工作闭环 + M7 时间轴/专注）。
> 本文只给实现方案与示意代码，不实际搭建项目脚手架。
> 技术栈：前端 React+TS+Vite（状态用 React Context，**非**原方案的 zustand）；后端 FastAPI+SQLite；向量 chromadb（仅 opt-in）；文档生成 python-docx/pptx/openpyxl；**富文本 TipTap（`@tiptap/react`+`starter-kit`+`@tiptap/pm`，笔记编辑器，属 M0 资料底座）+ 后端 `nh3` 入库前 HTML 白名单净化（防 XSS）**；文档编辑器 OnlyOffice（本地 Docker）。

---

## Q1 · 需要建立什么数据库（表结构）

单文件 SQLite（`app.db`）。核心表 7 张：

```sql
-- 任务（父子嵌套，完成度由子任务汇总）
CREATE TABLE Task (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  description TEXT,
  deadline TEXT,                -- ISO8601
  urgency INTEGER DEFAULT 0,    -- 0/1
  importance INTEGER DEFAULT 0,  -- 0/1
  status TEXT DEFAULT 'todo',   -- todo/doing/done
  completion_pct INTEGER DEFAULT 0,
  parent_id INTEGER REFERENCES Task(id),
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 任务分析产物（与 Task 一对一）
CREATE TABLE PlanAnalysis (
  task_id INTEGER PRIMARY KEY REFERENCES Task(id),
  requirement TEXT,            -- 需求确认卡文本
  steps_json TEXT,             -- JSON: [{desc, est, deps, need, output}]
  qa_log_json TEXT             -- JSON: [{step, q, a, 预案}]
);

-- 文档（AI 生成或导入，落本地目录）
CREATE TABLE Doc (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  path TEXT NOT NULL,
  type TEXT,                   -- docx/xlsx/pptx
  linked_task_id INTEGER REFERENCES Task(id),
  versions_json TEXT,          -- 版本快照列表
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 专注计时（M7，喂周报）
CREATE TABLE FocusSession (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER REFERENCES Task(id),
  start_ts TEXT,
  end_ts TEXT,
  duration_sec INTEGER
);

-- 自动报告
CREATE TABLE Report (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT,                   -- weekly/monthly
  period_start TEXT,
  period_end TEXT,
  content TEXT,
  auto_generated INTEGER DEFAULT 1,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 奖励（单人版仅一行）
CREATE TABLE Reward (
  id INTEGER PRIMARY KEY CHECK (id=1),
  points INTEGER DEFAULT 0,
  badges_json TEXT,
  videos_json TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 资料卡片（RAG 用，正文来源见 Q4）
CREATE TABLE KnowledgeCard (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT,
  body TEXT,
  source TEXT,                 -- web/upload/note/task_doc
  url TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

向量与全文分开存：**embedding 进 chromadb**（语义检索），**全文进 FTS5 虚拟表**（关键词搜索，见 Q5）。

```sql
-- 全局搜索索引（trigram 对中文子串友好）
CREATE VIRTUAL TABLE search_idx USING fts5(
  title, body, source_type, source_id, tokenize='trigram'
);
```

---

## Q2 · 豆包适配器怎么实现

定义统一抽象 `LLMProvider`，豆包走 **Volcengine Ark 的 OpenAI 兼容接口**（base_url 改掉即可，不用单独 SDK）。

```python
# llm/provider.py
from abc import ABC, abstractmethod
class LLMProvider(ABC):
    @abstractmethod
    def chat(self, messages, tools=None, tool_choice="auto"): ...

# llm/doubao.py
from openai import OpenAI
class DoubaoProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "doubao-seed-1.6"):
        self.client = OpenAI(
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            api_key=api_key,
        )
        self.model = model          # 也可填 EndpointId: ep-xxxxxxxx
    def chat(self, messages, tools=None, tool_choice="auto"):
        params = {"model": self.model, "messages": messages}
        if tools:
            params["tools"] = tools
            params["tool_choice"] = tool_choice
        resp = self.client.chat.completions.create(**params)
        return resp.choices[0].message   # 含 .content 与 .tool_calls
```

- 配置从环境变量/配置文件读 `ARK_API_KEY`、`ARK_MODEL`，**不硬编码**。
- 预留 `TongyiProvider` / `GLMProvider` / `OllamaProvider`，同样实现 `chat()`，业务代码只依赖抽象。
- 豆包原生支持 function calling（OpenAI 兼容协议），返回 `tool_calls` 即可进入 Q3 循环。

---

## Q3 · 工具执行循环怎么实现（Function Calling 循环）

核心：模型返回 `tool_calls` → 后端**真实执行**对应动作 → 结果回灌模型 → 继续推理，直到不再调用工具。

```python
# agent/loop.py
import json
MAX_ITER = 8

def run_agent(user_msg: str, provider, tools_schema: list, dispatch: dict):
    messages = [
        {"role": "system", "content": "你是任务助手，必要时调用工具完成任务。"},
        {"role": "user",   "content": user_msg},
    ]
    for _ in range(MAX_ITER):
        msg = provider.chat(messages, tools=tools_schema)
        if not msg.tool_calls:                 # 不再需要工具 → 收尾
            return msg.content
        messages.append(msg.model_dump())      # 保留带 tool_calls 的 assistant 消息
        for tc in msg.tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments)
            result = dispatch[name](**args)    # 真实执行后端动作
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),
            })
    return "已达最大轮次，未收敛"
```

`tools_schema` 是工具声明（JSON Schema），例如：
```python
tools_schema = [{
  "type": "function",
  "function": {
    "name": "create_task",
    "description": "新建一个任务",
    "parameters": {
      "type": "object",
      "properties": {
        "title": {"type": "string"},
        "deadline": {"type": "string"},
        "importance": {"type": "integer"},
        "urgency": {"type": "integer"},
      },
      "required": ["title"],
    },
  }
}]
```
`dispatch` 把名字映射到真实函数：`{"create_task": create_task, "write_doc": write_doc, "search_kb": search_kb, ...}`。
关键点：① 必须设 `MAX_ITER` 防失控；② tool 结果回灌后才能继续；③ 敏感动作（删任务、发邮件）在 dispatch 里加人工确认门槛。

---

## Q4 · 资料卡片模型从哪里来

`KnowledgeCard` 不是凭空产生的，它有 4 条入库通道（每条都触发"正文抽取 → 向量化 → 写 chromadb + FTS5"）：

1. **网页剪藏**（Q6）：用户存网页 → 正文进 card。
2. **上传文件**：PDF/Word 用 `pdfplumber`/`python-docx` 抽正文 → card（`source=upload`）。
3. **任务关联文档**：AI 生成的 `.docx/.xlsx/.pptx` 定稿后，正文/文本摘要进 card（`source=task_doc`）。
4. **手动笔记**：用户在资料库新建笔记 → card（`source=note`）。

入管流水线（统一）：
```python
def ingest_card(title, body, source, url=None):
    cid = db.insert_knowledge_card(title, body, source, url)
    vec = embedder.encode(body)            # sentence-transformers
    chromadb.upsert(cid, vec)
    fts.insert_search_idx(title, body, source, cid)
    return cid
```
检索时（AI 回答前）：`query → embed → chromadb.top_k → 取回 card 文本 → 拼进 system/context`。这就是"不用找资料"的底层。

---

## Q5 · 全局搜索怎么实现

用 SQLite **FTS5 虚拟表 + trigram 分词器**（对中文子串匹配友好，无需额外分词库）。

```sql
-- 建表见 Q1。写入：每次建任务/文档/卡片时同步插一行
INSERT INTO search_idx(rowid, title, body, source_type, source_id)
VALUES (?, ?, ?, 'task', ?);

-- 查询（trigram 支持 %like% 式子串）
SELECT rowid, title, snippet(search_idx, 1, '[', ']', '…', 12)
FROM search_idx
WHERE search_idx MATCH ?
ORDER BY rank;                     -- bm25 排序
```

- `tokenize='trigram'`：中文不用分词也能做子串检索（2~3 字即可命中），实现成本最低。
- 跨类型：task / doc / knowledge_card 统一进 `search_idx`，用 `source_type+source_id` 回查原表，实现"一把搜全站"。
- 进阶可换 jieba 分词（`tokenize='unicode61'` + 外部分词）提升召回，但 MVP 用 trigram 足够。

---

## Q6 · 网页剪藏怎么实现

**MVP（最小）**：不做浏览器插件，做"粘贴链接 → 后端抓取"：
```python
# api/clip.py
import requests
from readability import Document
@app.post("/api/clip")
def clip(url: str):
    html = requests.get(url, timeout=10).text
    body = Document(html).summary()      # readability-lxml 抽正文
    title = Document(html).short_title()
    return ingest_card(title, body, "web", url)   # 复用 Q4 流水线
```
前端一个输入框贴 URL 即可。

**完整版**：浏览器插件 / 书签脚本（bookmarklet）在页面内执行，抓取 `title/url/选中文本/DOM 正文/截图`，POST 给 `/api/clip`。插件能存"正在看的页面"，体验更好，但属于后期。MVP 用粘贴链接版先验证闭环。

---

## Q7 · 统一命令面板怎么实现

前端一个全局模态框（Ctrl/Cmd+K 唤起），输入框 + 结果区。

实现分两层（混合路由，确定性命令走规则，自然语言走 AI）：
```typescript
// 前端：捕获快捷键 → 打开 modal → 输入提交
const onCommand = async (text: string) => {
  const res = await fetch('/api/command', {
    method: 'POST',
    body: JSON.stringify({ text }),
  }).then(r => r.json());
  // res = { action: 'create_task'|'write_doc'|'search'|..., params, preview }
  executeAction(res);
};
```
```python
# 后端 /api/command：先规则，后 AI
def command(text):
    if m := re.match(r"新建任务[：: ]?(.*)", text):
        return {"action": "create_task", "params": {"title": m.group(1)}}
    if "周报" in text:
        return {"action": "gen_report", "params": {"type": "weekly"}}
    # 兜底：交给 LLM 意图分类（复用 Q3 provider，仅分类不执行）
    intent = classify_intent(text)        # 返回 action + 提取参数
    return intent
```
支持的命令类型：建任务 / 生成文档 / 查资料 / 打开X / 跑分析 / 生成周报。规则层覆盖高频固定句式（快、可控），AI 层兜底自然语言（灵活）。

---

## Q8 · 日历实现方式与样式

**实现方式**：月视图 + 周视图切换。
- 快速方案：用 **FullCalendar（react 组件）**，自带月/周网格、拖拽、事件渲染，开发量最小。
- 自控方案（想要完全贴合主题）：自研 CSS Grid 月历（7 列 × N 行），周视图用时间轴 + 绝对定位的事件条。
- 数据：任务 `deadline` 作日期事件；`FocusSession` 作周视图时间块；学习计划（Phase 2）slot 也进日历。

**样式（浅色主题，贴合 IDE light）**：
- 背景白 / 浅灰，文字深灰；不深底。
- 事件 chip 按**四象限**着色：
  - 紧急且重要 → 红（`#E24B4A`）
  - 重要不紧急 → 蓝（`#185FA5`）
  - 紧急不重要 → 橙（`#BA7517`）
  - 都不 → 灰（`#888780`）
- 截止日：日期格右上角小圆点（红=今天到期，橙=3 天内，灰=更晚）。
- 周视图：时间轴左侧小时刻度，专注块用半透明色条横跨对应时段，显示任务名+时长。
- 今日列高亮浅黄底。

```tsx
// 简版月历事件 chip（颜色来自四象限）
const colorOf = (t: Task) =>
  t.urgency && t.importance ? '#E24B4A'
  : t.importance ? '#185FA5'
  : t.urgency ? '#BA7517' : '#888780';
```

---

## Q9 · 日历提醒都有什么功能

1. **临近截止提醒**：定时扫描 `deadline` 在 1/3/7 天内的未完成任务 → 应用内角标 + 浏览器 `Notification`。
2. **防空洞提醒**：`status!=done` 且超过 N 天（如 7 天）无更新 → 标灰/警示，提示"是否还做"。
3. **每日 / 每周 digest**（可选）：早上推送"今日截止 X 项 + 今日建议专注计划"（可让 AI 生成）。
4. **专注结束提醒**：`FocusSession` 到点提示休息（M7）。
5. **时间冲突检测**：同一时间块排入多个任务/学习 slot → 标红冲突（M7 排程时校验）。
6. **复习提醒**（Phase 2 学习）：艾宾浩斯间隔（1/2/4/7/15 天）自动插复习节点并提醒。

MVP 落地：先做 1+2+6（核心防漏），提醒通道用**应用内 toast + 浏览器 Notification API**，提前量在设置里可调。

---

## Q10 · 笔记富文本编辑器选型（M0 资料底座 / 笔记子系统）

笔记正文需要 H1/H2/段落等富文本，且要能被 FTS5 全文检索、入库前防 XSS。

- **前端：TipTap**（ProseMirror 封装）。直接依赖 `@tiptap/react` + `@tiptap/starter-kit` + `@tiptap/pm`（StarterKit 内含 heading/bold/italic/list/code 等常用节点）。
  - 选型理由：比手搓 `contentEditable` 稳、比 CKEditor 轻；与 React 契合好；输出标准 HTML，便于落库与检索。
  - 仅 `NoteEditor.tsx` 使用，不污染全局。
- **后端：`nh3`**（`requirements.txt` 仅依赖）做入库前白名单净化：`knowledge.py` 用 `nh3.clean(html, tags=..., attributes=...)` 剥掉 `<script>`/`onclick`/`iframe`，失败退化为纯文本。
  - 选型理由：笔记 HTML 来自用户编辑，必须服务端净化再落 `knowledge_card.rich_body`，否则存储型 XSS。
- **该选型原始方案（PRD / 技术设计初稿）未规划**，随 M0 笔记子系统实现时引入，属合理技术扩张；已纳入技术栈单一事实来源（本文 + 审计表 + README）。

---

## 小结（Phase 1 依赖关系）

```
DB(SQLite+FTS5+chromadb)
   └─ LLMProvider(豆包) ── 工具执行循环 ── dispatch → 真实动作
KFCard 入库(4 通道) ── 向量+FTS5 ── 全局搜索 / RAG 上下文
命令面板 ── 混合路由 ── 调工具 / 跳模块
日历 ── 任务+专注+学习 ── 提醒(临近/防空洞/冲突)
```
所有模块都围绕"零跳转"：命令面板入口、RAG 免找资料、专注计时自动喂周报、日历统一视图。
