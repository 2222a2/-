"""Pydantic 数据模型：对外请求/响应结构与内部表结构的边界。

逻辑：数据库用 dict（sqlite3.Row），网络传输用 pydantic，二者在路由层转换。
这样以后换数据库或加字段，不影响 API 契约。
"""
from pydantic import BaseModel
from typing import Optional, List


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    parent_id: Optional[int] = None
    deadline: Optional[str] = None
    urgency: int = 0
    importance: int = 0


class TaskOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    parent_id: Optional[int] = None
    deadline: Optional[str] = None
    urgency: int = 0
    importance: int = 0
    status: str = "todo"
    completion: int = 0
    created_at: Optional[str] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    deadline: Optional[str] = None
    urgency: Optional[int] = None
    importance: Optional[int] = None
    status: Optional[str] = None
    completion: Optional[int] = None
    parent_id: Optional[int] = None


class ReportOut(BaseModel):
    period_start: str
    period_end: str
    done_count: int = 0
    focus_seconds: int = 0
    doc_count: int = 0          # 本周期生成的 Office 文档数（M3 文档维度，对齐 PRD 聚合口径）
    markdown: str = ""


class HealthOut(BaseModel):
    status: str
    service: str
    version: str


# ------------------------- M2 AI 助手层契约 -------------------------

class AiMessageIn(BaseModel):
    message: str


class AiCommandIn(BaseModel):
    text: str


class AiStatusOut(BaseModel):
    provider: str
    rag_backend: str
    rag_retriever: str
    api_key_configured: bool
    tools: List[str]


class AgentStep(BaseModel):
    type: str                       # decision | action | final
    content: Optional[str] = None
    calls: Optional[List[dict]] = None
    name: Optional[str] = None
    result: Optional[dict] = None


class AgentOut(BaseModel):
    reply: str
    steps: List[AgentStep]
    tool_calls: int


class CommandOut(BaseModel):
    action: Optional[str] = None
    params: dict = {}
    preview: str = ""
    steps: Optional[List[AgentStep]] = None


# ------------------------- M0 资料聚合底座契约 -------------------------

class ClipIn(BaseModel):
    url: str


class NoteIn(BaseModel):
    title: Optional[str] = None
    content: str


class KnowledgeCardOut(BaseModel):
    id: int
    title: Optional[str] = None
    content: Optional[str] = None
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    created_at: Optional[str] = None


class KnowledgeListOut(BaseModel):
    mode: str
    count: Optional[int] = None
    query: Optional[str] = None
    cards: Optional[List[KnowledgeCardOut]] = None
    results: Optional[List[dict]] = None


# ------------------------- 备考学习任务（study_task）契约 -------------------------

class StudyTaskCreate(BaseModel):
    date: str
    period: Optional[str] = None
    subject: Optional[str] = None
    title: str
    source: str = "auto"


class StudyTaskOut(BaseModel):
    id: int
    date: str
    period: Optional[str] = None
    subject: Optional[str] = None
    title: str
    done: int = 0
    source: str = "auto"            # auto(生成器) | manual(手动) | review(遗忘曲线复习)
    sort_order: int = 0
    review_of: Optional[int] = None     # 指向原始新学任务 id；新学任务为 NULL
    review_stage: Optional[int] = None  # 1..5，第几轮复习
    due_offset: Optional[int] = None    # 1/2/4/7/15，相对学习日的天数偏移
    created_at: Optional[str] = None


class WeeklyProgressOut(BaseModel):
    week_start: str
    week_end: str
    total: int
    done: int
    rate: float = 0
    by_subject: dict = {}
    by_date: dict = {}


class DailyCompletionOut(BaseModel):
    date: str                   # YYYY-MM-DD
    total: int = 0              # 当天任务总数
    done: int = 0               # 当天已完成数
    rate: float = 0             # done/total，0~1；无任务为 0


# ------------------------- M4 分析引擎契约 -------------------------
# 设计：四阶段状态机由前端驱动，后端每阶段只负责“把模型输出解析成结构化 JSON”。
# 字段统一用 dict/list（模型产出结构灵活），前端按需渲染可编辑表单。

class ClarifyIn(BaseModel):
    text: str                         # 用户的模糊任务描述


class ConfirmIn(BaseModel):
    text: str                         # 原始任务描述（上下文）
    answers: list = []                # 用户对反问的回答：[{field, answer}]


class DecomposeIn(BaseModel):
    requirement: dict                 # 阶段B确认卡


class SaveIn(BaseModel):
    title: str                        # 主任务标题
    requirement: dict                 # 确认卡（落 plan_analysis）
    steps: list = []                  # 拆解步骤（落 plan_analysis + 写 task 子任务）


class QaIn(BaseModel):
    step: dict                        # 选中的某一步：{order, desc, ...}


class QaAnswerIn(BaseModel):
    step_order: int
    step_desc: str = ""
    questions: dict = {}              # 模型三问：{risks, blockers, prerequisites}
    answers: dict = {}                # 用户回答：{risks, blockers, prerequisites}


class QaAnswerOut(BaseModel):
    ok: bool = True
    qa_log: list = []


# ------------------------- M1 文档中心（docs）契约 -------------------------
# 设计：生成接口 = “意图(自然语言/分析产物) → 豆包产结构化内容 → 渲染真实文件 → 落库”。
# 请求里 doc_type 决定渲染引擎（docx/xlsx/pptx）；source=analysis 时把分析产物的
# 需求卡+步骤直接塞进 prompt，让 AI 据此起草，保证“分析→文档”无缝衔接。

class DocsGenerateIn(BaseModel):
    prompt: str                                            # 生成意图，如“本周工作周报”
    doc_type: str = "word"                                 # word | excel | ppt
    title: Optional[str] = None
    linked_task_id: Optional[int] = None                   # 关联任务（周报→对应分析主任务）
    source: str = "prompt"                                 # prompt | analysis
    requirement: Optional[dict] = None                     # 分析产物：需求确认卡
    steps: Optional[list] = None                           # 分析产物：拆解步骤


class DocOut(BaseModel):
    id: int
    path: str
    type: Optional[str] = None
    linked_task_id: Optional[int] = None
    versions_json: Optional[str] = None
    created_at: Optional[str] = None


class DocVersionOut(BaseModel):
    version: int
    saved_at: str
    size: int
    note: str
    snapshot_rel: str                                     # 相对 DATA_DIR 的快照路径


# ------------------------- M7 专注计时（focus）契约 -------------------------
# 设计：专注只负责写 focus_session（start 记起点、stop 算时长），
# 周报在聚合时读取它——模块解耦、零额外录入（详见 M4联动设计文档）。

class FocusStartIn(BaseModel):
    task_id: Optional[int] = None      # 可空：纯记录工时也行
    note: Optional[str] = None


class FocusStopIn(BaseModel):
    session_id: int


class FocusSessionOut(BaseModel):
    id: int
    task_id: Optional[int] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration: int = 0                  # 秒
    task_title: Optional[str] = None
