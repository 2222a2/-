import axios from 'axios'

// 所有请求走相对路径 /api，由 vite 代理转发到后端 8000，免去跨域配置
export const api = axios.create({
  baseURL: '/api',
  timeout: 30000, // 剪藏/上传可能慢，放宽到 30s
})

export interface Health {
  status: string
  service: string
  version: string
}

// ------------------------- M0 资料聚合底座（笔记资料系统对齐版）-------------------------
export interface KnowledgeCard {
  id: number
  title: string | null
  content: string | null        // FTS 真源：纯文本
  source_type: string | null    // 来源：web_clip | upload | task_doc | note（旧字段，保持兼容）
  source_id: string | null      // 文件/网页指针（文件型已直接复用，不再有 file_ref）
  created_at: string | null      // UTC（datetime('now')）
  item_type: string | null      // 类型：note | file | website（笔记资料系统新增）
  package_id: number | null     // 归属笔记包 id
  url: string | null            // 网站型链接（笔记资料系统新增列）
  rich_body: string | null      // 富文本 HTML（笔记资料系统新增列）
  title_pinyin: string | null   // 拼音首字母分组键（笔记资料系统新增列）
}

export interface KnowledgeList {
  mode: string                  // 'list' | 'search'
  count?: number
  query?: string
  cards?: KnowledgeCard[]
  groups?: { group: string; items: KnowledgeCard[] }[]
  results?: { source_id: number; title: string; body: string; rank: number }[]
}

// 笔记包（note_package）
export interface NotePackage {
  id: number
  name: string
  parent_id: number | null
  sort_order: number
  color: string | null
  created_at: string | null
  updated_at: string | null
}

export type TimeRange = 'today' | 'week' | 'month' | 'all'
export type GroupBy = 'none' | 'time' | 'title' | 'package'

export const knowledge = {
  // 列表 / 搜索 / 筛选 / 分组（扩展自原 /api/knowledge，向后兼容）
  list: (opts?: {
    q?: string
    item_type?: string
    package_id?: number
    include_descendants?: boolean
    time_range?: TimeRange
    group_by?: GroupBy
    limit?: number
  }) =>
    api.get<KnowledgeList>('/knowledge', {
      params: {
        q: opts?.q,
        item_type: opts?.item_type,
        package_id: opts?.package_id,
        include_descendants: opts?.include_descendants,
        time_range: opts?.time_range,
        group_by: opts?.group_by,
        limit: opts?.limit,
      },
    }),
  get: (id: number) => api.get<KnowledgeCard>(`/knowledge/${id}`),
  // 结构化笔记创建（富文本 HTML 由后端 nh3 净化；content 抽纯文本进 FTS）
  createNote: (body: {
    title?: string
    item_type?: string
    package_id?: number | null
    url?: string
    rich_body?: string
    content?: string
  }) => api.post<{ id: number; ok: boolean }>('/knowledge/notes', body),
  // 兼容旧接口：纯文本笔记
  note: (content: string, title?: string) =>
    api.post<{ id: number; ok: boolean }>('/knowledge/notes', { content, title }),
  update: (id: number, body: {
    title?: string | null
    package_id?: number | null
    item_type?: string
    url?: string | null
    rich_body?: string
    content?: string
  }) => api.patch(`/knowledge/${id}`, body),
  remove: (id: number) => api.delete(`/knowledge/${id}`),
  clip: (url: string) => api.post('/knowledge/clip', { url }),
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post('/knowledge/uploads', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  // 笔记包 CRUD
  packages: {
    list: () => api.get<{ packages: NotePackage[] }>('/knowledge/packages'),
    create: (body: { name: string; parent_id?: number | null; color?: string; sort_order?: number }) =>
      api.post<{ id: number; ok: boolean }>('/knowledge/packages', body),
    update: (id: number, body: { name?: string; color?: string; sort_order?: number; parent_id?: number | null }) =>
      api.patch(`/knowledge/packages/${id}`, body),
    remove: (id: number) => api.delete(`/knowledge/packages/${id}`),
  },
}

// ------------------------- 备考学习任务（study_task）-------------------------
export interface StudyTask {
  id: number
  date: string
  period: string | null      // morning | noon | evening | null(其他)
  subject: string | null     // math | english | cs408 | ds | other
  title: string
  done: number               // 0 / 1
  source: string             // auto(生成器) | manual(手动)
  sort_order: number
  created_at: string | null
}

export interface WeeklyProgress {
  week_start: string
  week_end: string
  total: number
  done: number
  rate: number               // 0~1
  by_subject: Record<string, { total: number; done: number }>
  by_date: Record<string, { total: number; done: number }>
}

// 备考任务页口令：从 localStorage 读取（用户首次输入后存下），随每个 study 请求带上。
// 后端若设了 STUDY_PAGE_TOKEN，不带/带错会返回 401，页面据此弹出口令框。
let studyToken = (() => {
  try { return localStorage.getItem('study_token') || '' } catch { return '' }
})()
export function setStudyToken(t: string) {
  studyToken = t
  try { if (t) localStorage.setItem('study_token', t); else localStorage.removeItem('study_token') } catch { /* ignore */ }
}

// 后端 PATCH / POST-add 用 query 参数接收，故这里 body 传 null、参数走 params。
export const study = {
  listByDate: (date: string) =>
    api.get<StudyTask[]>('/study-tasks', { params: { date }, headers: { 'X-Study-Token': studyToken } }),
  listWeekly: (date?: string) =>
    api.get<WeeklyProgress>('/study-tasks/weekly', { params: { date }, headers: { 'X-Study-Token': studyToken } }),
  patch: (id: number, body: { done?: number; title?: string }) =>
    api.patch(`/study-tasks/${id}`, null, { params: body, headers: { 'X-Study-Token': studyToken } }),
  add: (body: {
    date: string
    period?: string
    subject?: string
    title: string
    sort_order?: number
  }) => api.post('/study-tasks/add', null, { params: body, headers: { 'X-Study-Token': studyToken } }),
  remove: (id: number) => api.delete(`/study-tasks/${id}`, { headers: { 'X-Study-Token': studyToken } }),
}

// ------------------------- 命令面板 -------------------------
export interface CommandResult {
  action?: string | null
  params?: Record<string, any>
  preview?: string
  steps?: { type: string; content?: string | null; name?: string | null }[]
}

export const command = (text: string) => api.post<CommandResult>('/ai/command', { text })

// ------------------------- M3 任务管理（task）-------------------------
export interface TaskItem {
  id: number
  title: string
  description: string | null
  parent_id: number | null
  deadline: string | null
  urgency: number          // 0/1
  importance: number       // 0/1
  status: string           // todo | doing | done | blocked
  completion: number       // 0-100
  created_at: string | null
  has_children?: boolean
  children?: TaskItem[]
}

export const tasksApi = {
  list: () => api.get<TaskItem[]>('/tasks'),
  get: (id: number) => api.get<TaskItem>(`/tasks/${id}`),
  create: (body: {
    title: string
    description?: string | null
    deadline?: string | null
    urgency?: number
    importance?: number
    parent_id?: number | null
  }) => api.post<{ id: number; ok: boolean }>('/tasks', body),
  update: (id: number, body: {
    title?: string
    description?: string | null
    deadline?: string | null
    urgency?: number
    importance?: number
    status?: string
    completion?: number
    parent_id?: number | null
  }) => api.patch(`/tasks/${id}`, body),
  remove: (id: number) => api.delete(`/tasks/${id}`),
  // 防空洞任务：久未更新且未完成（默认 7 天）
  stale: (days?: number) =>
    api.get<Array<{ id: number; title: string; status: string; updated_at: string; days_since: number }>>(
      '/tasks/stale', { params: { days } },
    ),
}

// ------------------------- M3 自动周报（report）-------------------------
export interface ReportOut {
  period_start: string
  period_end: string
  done_count: number
  focus_seconds: number
  doc_count: number
  markdown: string
}

export const reportsApi = {
  weekly: () => api.get<ReportOut>('/reports/weekly'),
  monthly: () => api.get<ReportOut>('/reports/monthly'),
  // 导出 Word / PDF（后端 python-docx / reportlab 渲染），返回可直接给 <a download> 的地址
  exportUrl: (type: 'weekly' | 'monthly', format: 'docx' | 'pdf' = 'docx') =>
    `/api/reports/export?type=${type}&format=${format}`,
}


// ----------------------------- M4 分析引擎 -----------------------------
export interface AnalysisQuestion {
  field: string
  question: string
}
export interface AnalysisStep {
  order: number
  desc: string
  est_hours: number
  deps: number[]
  need: string[]
  output: string
}
export interface AnalysisRequirement {
  goal: string
  deliverable: string
  deadline: string
  constraints: string
  success_criteria: string
  assumptions: string[]
}
export interface QaEntry {
  step_order: number
  step_desc: string
  questions: { risks: string; blockers: string; prerequisites: string }
  answers: { risks: string; blockers: string; prerequisites: string }
}

export const analysisApi = {
  // 阶段A：模糊任务 → 反问
  clarify: (text: string) =>
    api.post<{ questions: AnalysisQuestion[]; mock: boolean }>('/analysis/clarify', { text }),
  // 阶段B：回答反问 → 需求确认卡
  confirm: (text: string, answers: { field: string; answer: string }[]) =>
    api.post<{ requirement: AnalysisRequirement; mock: boolean }>('/analysis/confirm', { text, answers }),
  // 阶段C：确认卡 → 步骤
  decompose: (requirement: AnalysisRequirement) =>
    api.post<{ steps: AnalysisStep[]; mock: boolean }>('/analysis/decompose', { requirement }),
  // 阶段D-1：确认卡 + 步骤 → 建任务树 + 落库
  save: (title: string, requirement: AnalysisRequirement, steps: AnalysisStep[]) =>
    api.post<{ plan_id: number; task_id: number; child_ids: number[]; mock: boolean }>(
      '/analysis/save', { title, requirement, steps },
    ),
  // 阶段D-2：选中某步 → 三问
  qa: (planId: number, step: AnalysisStep) =>
    api.post<{ risks: string; blockers: string; prerequisites: string; mock: boolean }>(
      `/analysis/${planId}/qa`, { step },
    ),
  // 阶段D-3：回答三问 → 沉淀预案
  qaAnswer: (planId: number, payload: {
    step_order: number
    step_desc: string
    questions: { risks: string; blockers: string; prerequisites: string }
    answers: { risks: string; blockers: string; prerequisites: string }
  }) => api.post<{ ok: boolean; qa_log: QaEntry[] }>(`/analysis/${planId}/qa-answer`, payload),
}


// ------------------------- M1 文档中心（docs）-------------------------
export interface DocView {
  id: number
  path: string
  type: string | null          // word | excel | ppt
  linked_task_id: number | null
  versions_json: string
  created_at: string | null
  current_version: number
}
export interface DocVersion {
  version: number
  saved_at: string
  size: number
  note: string
  snapshot_rel: string
}
export interface DocGenerateResult {
  doc: DocView
  editor_config: Record<string, any>   // 直接喂给 DocEditor 的 OnlyOffice config
}

export const docsApi = {
  // 生成：意图/分析产物 → 后端渲染真实 Office 文件 → 返回编辑器配置
  generate: (body: {
    prompt: string
    doc_type?: string             // word | excel | ppt，默认 word
    title?: string
    linked_task_id?: number | null
    source?: string               // prompt | analysis
    requirement?: Record<string, any> | null
    steps?: any[]
  }) => api.post<DocGenerateResult>('/docs/generate', body),
  list: () => api.get<DocView[]>('/docs'),
  get: (id: number) => api.get<{ doc: DocView; editor_config: Record<string, any> }>(`/docs/${id}`),
  versions: (id: number) =>
    api.get<{ doc_id: number; versions: DocVersion[]; current_version: number }>(`/docs/${id}/versions`),
  rollback: (id: number, version: number) =>
    api.post<{ doc: DocView; editor_config: Record<string, any> }>(`/docs/${id}/rollback/${version}`),
}

// 文件服务 / 导出（走 vite 代理到后端 8000）
export const docFileUrl = (id: number) => `/api/docs/file/${id}`
export const docExportUrl = (id: number, version?: number) =>
  `/api/docs/${id}/export${version != null ? `?version=${version}` : ''}`


// ------------------------- M7 专注计时（focus）-------------------------
export interface FocusSession {
  id: number
  task_id: number | null
  started_at: string | null
  ended_at: string | null
  duration: number           // 秒
  task_title?: string | null
}

export const focusApi = {
  // 开始专注：task_id 可空（纯记录工时也行），返回 session id
  start: (taskId?: number | null) =>
    api.post<{ id: number; ok: boolean }>('/focus/start', { task_id: taskId ?? null }),
  // 停止专注：补 ended_at + duration，返回本次时长（秒）
  stop: (sessionId: number) =>
    api.post<{ ok: boolean; duration: number; already_stopped?: boolean }>('/focus/stop', { session_id: sessionId }),
  // 当前进行中的专注（前端刷新后用它恢复计时器）
  active: () => api.get<{ session: FocusSession | null }>('/focus/active'),
  // 最近专注历史（含任务标题）
  history: () => api.get<FocusSession[]>('/focus/history'),
}

// ------------------------- 用户偏好设置（番茄钟时长）-------------------------
export interface FocusPrefs {
  work_minutes: number
  break_minutes: number
}

export const prefsApi = {
  // 读取番茄钟工作/休息时长（分钟）
  get: () => api.get<FocusPrefs>('/settings/focus'),
  // 保存（只传要改的字段即可）
  update: (body: Partial<FocusPrefs>) => api.put<FocusPrefs>('/settings/focus', body),
}

