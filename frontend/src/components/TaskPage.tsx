import { useEffect, useMemo, useState } from 'react'
import { tasksApi, reportsApi, TaskItem, ReportOut } from '../api/client'
import { useFocus } from './FocusProvider'

// 四象限配色（与 PRD Q8 对齐）：重要×紧急 决定底色
const QUAD = {
  q1: { name: '重要 · 紧急', color: '#E24B4A' }, // 重要且紧急
  q2: { name: '重要 · 不紧急', color: '#185FA5' }, // 重要不紧急
  q3: { name: '紧急 · 不重要', color: '#BA7517' }, // 紧急不重要
  q4: { name: '日常 · 待规划', color: '#888780' }, // 既不重要也不紧急
}

function quadrantOf(t: TaskItem): keyof typeof QUAD {
  if (t.importance && t.urgency) return 'q1'
  if (t.importance && !t.urgency) return 'q2'
  if (!t.importance && t.urgency) return 'q3'
  return 'q4'
}

export default function TaskPage() {
  const [tasks, setTasks] = useState<TaskItem[]>([])
  const [view, setView] = useState<'board' | 'report'>('board')
  const [loading, setLoading] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [draftTitle, setDraftTitle] = useState('')
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const [newOpen, setNewOpen] = useState(false)
  // 防空洞任务（久未更新且未完成）
  const [staleIds, setStaleIds] = useState<Set<number>>(new Set())
  const [showStaleToast, setShowStaleToast] = useState(true)
  // 新建表单字段
  const [nf, setNf] = useState({ title: '', deadline: '', urgency: false, importance: false })
  // 周报 / 月报
  const [report, setReport] = useState<ReportOut | null>(null)
  const [monthlyReport, setMonthlyReport] = useState<ReportOut | null>(null)
  const [rptTab, setRptTab] = useState<'weekly' | 'monthly'>('weekly')

  async function load() {
    setLoading(true)
    try {
      const [r, s] = await Promise.all([tasksApi.list(), tasksApi.stale()])
      setTasks(r.data)
      // 默认展开所有有子任务的
      const ex = new Set<number>()
      r.data.forEach((t) => { if (t.has_children) ex.add(t.id) })
      setExpanded(ex)
      setStaleIds(new Set(s.data.map((x) => x.id)))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (view === 'board') load()
    else loadReport()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view])

  async function loadReport() {
    setLoading(true)
    try {
      const [w, m] = await Promise.all([reportsApi.weekly(), reportsApi.monthly()])
      setReport(w.data)
      setMonthlyReport(m.data)
    } finally {
      setLoading(false)
    }
  }

  // 按四象限分组顶层任务
  const grouped = useMemo(() => {
    const g: Record<string, TaskItem[]> = { q1: [], q2: [], q3: [], q4: [] }
    for (const t of tasks) g[quadrantOf(t)].push(t)
    return g
  }, [tasks])

  async function createRoot() {
    const title = nf.title.trim()
    if (!title) return
    await tasksApi.create({
      title,
      deadline: nf.deadline || null,
      urgency: nf.urgency ? 1 : 0,
      importance: nf.importance ? 1 : 0,
    })
    setNf({ title: '', deadline: '', urgency: false, importance: false })
    setNewOpen(false)
    await load()
  }

  async function toggleDone(t: TaskItem) {
    const next = t.status === 'done' ? 'doing' : 'done'
    await tasksApi.update(t.id, { status: next, completion: next === 'done' ? 100 : t.completion })
    await load()
  }
  async function commitTitle(t: TaskItem) {
    setEditingId(null)
    const title = draftTitle.trim()
    if (!title || title === t.title) return
    await tasksApi.update(t.id, { title })
    await load()
  }
  async function remove(t: TaskItem) {
    if (!confirm(`删除「${t.title}」${t.has_children ? '及其所有子任务' : ''}？`)) return
    await tasksApi.remove(t.id)
    await load()
  }
  async function addSub(t: TaskItem) {
    const title = window.prompt(`给「${t.title}」加一个子任务：`)
    if (!title || !title.trim()) return
    await tasksApi.create({ title: title.trim(), parent_id: t.id })
    setExpanded((p) => new Set(p).add(t.id))
    await load()
  }
  async function cycleStatus(t: TaskItem) {
    // 循环切换 todo -> doing -> done -> todo，方便快速标记
    const order = ['todo', 'doing', 'done']
    const next = order[(order.indexOf(t.status) + 1) % 3]
    await tasksApi.update(t.id, { status: next, completion: next === 'done' ? 100 : next === 'doing' ? Math.max(t.completion, 30) : t.completion })
    await load()
  }

  function toggleExpand(id: number) {
    setExpanded((p) => {
      const n = new Set(p)
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })
  }

  return (
    <div style={{ maxWidth: 1080, width: '100%', margin: '0 auto', padding: '0 12px', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <h1 style={{ margin: 0, fontSize: 22 }}>📋 任务管理</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => setView('board')} style={tabBtn(view === 'board')}>四象限看板</button>
          <button onClick={() => setView('report')} style={tabBtn(view === 'report')}>自动报告</button>
          {view === 'board' && (
            <button onClick={() => setNewOpen((v) => !v)} style={{ ...tabBtn(false), background: '#185FA5', color: '#fff' }}>
              + 新建
            </button>
          )}
        </div>
      </div>

      {view === 'board' ? (
        <>
          {showStaleToast && staleIds.size > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, background: '#FFF7E6', border: '1px solid #F0C36D', borderRadius: 10, padding: '10px 14px', marginTop: 14 }}>
              <span style={{ fontSize: 15 }}>🕳️</span>
              <span style={{ flex: 1, fontSize: 13, color: '#8a6d3b' }}>
                有 <b>{staleIds.size}</b> 个任务超过 7 天未更新（标灰行），建议尽快推进或归档。
              </span>
              <button onClick={() => setShowStaleToast(false)} style={{ border: 'none', background: 'transparent', color: '#8a6d3b', cursor: 'pointer', fontSize: 13 }}>知道了</button>
            </div>
          )}

          {newOpen && (
            <div style={newForm}>
              <input
                autoFocus placeholder="任务标题…"
                value={nf.title}
                onChange={(e) => setNf({ ...nf, title: e.target.value })}
                onKeyDown={(e) => { if (e.key === 'Enter') createRoot() }}
                style={miniInput}
              />
              <input type="date" value={nf.deadline} onChange={(e) => setNf({ ...nf, deadline: e.target.value })} style={miniInput} />
              <label style={chk}><input type="checkbox" checked={nf.importance} onChange={(e) => setNf({ ...nf, importance: e.target.checked })} /> 重要</label>
              <label style={chk}><input type="checkbox" checked={nf.urgency} onChange={(e) => setNf({ ...nf, urgency: e.target.checked })} /> 紧急</label>
              <button onClick={createRoot} style={{ ...miniInput, background: '#185FA5', color: '#fff', border: 'none', cursor: 'pointer' }}>创建</button>
            </div>
          )}

          {loading && <p style={{ color: '#888' }}>加载中…</p>}

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginTop: 16 }}>
            {(['q1', 'q2', 'q3', 'q4'] as const).map((q) => (
              <section key={q} style={{ background: '#fff', border: `1px solid ${QUAD[q].color}33`, borderRadius: 12, padding: 12 }}>
                <h3 style={{ margin: '0 0 10px', fontSize: 15, color: QUAD[q].color, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 3, background: QUAD[q].color, display: 'inline-block' }} />
                  {QUAD[q].name} <span style={{ color: '#bbb', fontSize: 12 }}>· {grouped[q].length}</span>
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {grouped[q].map((t) => (
                    <TaskNode
                      key={t.id} task={t} depth={0} color={QUAD[q].color}
                      expanded={expanded} toggleExpand={toggleExpand}
                      editingId={editingId} setEditingId={setEditingId} draftTitle={draftTitle} setDraftTitle={setDraftTitle}
                      onToggleDone={toggleDone} onCommitTitle={commitTitle} onRemove={remove}
                      onAddSub={addSub} onCycle={cycleStatus}
                      staleIds={staleIds}
                    />
                  ))}
                  {grouped[q].length === 0 && (
                    <p style={{ color: '#bbb', fontSize: 13, margin: 0 }}>这个象限暂无任务</p>
                  )}
                </div>
              </section>
            ))}
          </div>
          <p style={{ color: '#999', fontSize: 12, marginTop: 14 }}>
            父任务完成度由子任务自动汇总；点状态标签可循环切换 待办→进行中→完成。周报会自动聚合本周完成项与专注工时。
          </p>
        </>
      ) : (
        <div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            <button onClick={() => setRptTab('weekly')} style={tabBtn(rptTab === 'weekly')}>周报</button>
            <button onClick={() => setRptTab('monthly')} style={tabBtn(rptTab === 'monthly')}>月报</button>
          </div>
          <ReportView
            report={rptTab === 'weekly' ? report : monthlyReport}
            loading={loading}
            title={rptTab === 'weekly' ? '本周周报草稿' : '本月月报草稿'}
            exportType={rptTab === 'weekly' ? 'weekly' : 'monthly'}
          />
        </div>
      )}
    </div>
  )
}

// 递归渲染任务节点（含 children）
function TaskNode(props: {
  task: TaskItem
  depth: number
  color: string
  expanded: Set<number>
  toggleExpand: (id: number) => void
  editingId: number | null
  setEditingId: (id: number | null) => void
  draftTitle: string
  setDraftTitle: (s: string) => void
  onToggleDone: (t: TaskItem) => void
  onCommitTitle: (t: TaskItem) => void
  onRemove: (t: TaskItem) => void
  onAddSub: (t: TaskItem) => void
  onCycle: (t: TaskItem) => void
  staleIds: Set<number>
}) {
  const { task: t, depth, color, expanded, toggleExpand, editingId, setEditingId, draftTitle, setDraftTitle,
    onToggleDone, onCommitTitle, onRemove, onAddSub, onCycle, staleIds } = props
  const open = expanded.has(t.id) && (t.children?.length ?? 0) > 0
  const done = t.status === 'done'
  const stale = staleIds.has(t.id)
  const { start } = useFocus()
  return (
    <div style={{ marginLeft: depth ? 14 : 0, opacity: stale && !done ? 0.55 : 1 }}>
      <div style={{ ...card, borderLeft: `4px solid ${done ? '#bbb' : color}` }}>
        <input type="checkbox" checked={done} onChange={() => onToggleDone(t)} style={{ width: 16, height: 16 }} />
        {editingId === t.id ? (
          <input
            autoFocus value={draftTitle}
            onChange={(e) => setDraftTitle(e.target.value)}
            onBlur={() => onCommitTitle(t)}
            onKeyDown={(e) => { if (e.key === 'Enter') onCommitTitle(t); if (e.key === 'Escape') setEditingId(null) }}
            style={{ flex: 1, padding: '4px 8px', borderRadius: 6, border: '1px solid #ccc', fontSize: 14 }}
          />
        ) : (
          <span
            onClick={() => { setEditingId(t.id); setDraftTitle(t.title) }}
            style={{ flex: 1, cursor: 'text', textDecoration: done ? 'line-through' : 'none', color: done ? '#aaa' : '#222', fontSize: 14 }}
            title="点击改标题"
          >
            {t.title}
          </span>
        )}
        <span onClick={() => onCycle(t)} style={{ ...statusTag, background: statusColor(t.status), cursor: 'pointer' }} title="点击切换状态">
          {statusLabel(t.status)}
        </span>
        {stale && !done && (
          <span style={{ ...statusTag, background: '#9e9e9e', cursor: 'default' }} title="超过 7 天未更新">🕳 久未更新</span>
        )}
        {t.has_children && (
          <span onClick={() => toggleExpand(t.id)} style={{ cursor: 'pointer', color: '#888', fontSize: 12, userSelect: 'none' }}>
            {open ? '▾' : '▸'}{t.children?.length}
          </span>
        )}
        <button onClick={() => start(t.id, t.title)} style={iconBtn} title="专注计时">⏱</button>
        <button onClick={() => onAddSub(t)} style={iconBtn} title="加子任务">＋</button>
        <button onClick={() => onRemove(t)} style={iconBtn} title="删除">✕</button>
      </div>
      {/* 完成度进度条 */}
      {!t.has_children && (
        <div style={{ height: 4, background: '#eee', borderRadius: 2, margin: '2px 0 2px 20px', overflow: 'hidden' }}>
          <div style={{ width: `${t.completion}%`, height: '100%', background: done ? '#bbb' : color }} />
        </div>
      )}
      {t.deadline && (
        <div style={{ fontSize: 11, color: '#999', marginLeft: 20, marginTop: 2 }}>截止 {t.deadline}</div>
      )}
      {open && t.children?.map((c) => (
        <TaskNode key={c.id} {...props} task={c} depth={depth + 1} />
      ))}
    </div>
  )
}

function statusLabel(s: string): string {
  return { todo: '待办', doing: '进行中', done: '完成', blocked: '受阻' }[s] || s
}
function statusColor(s: string): string {
  return { todo: '#bbb', doing: '#185FA5', done: '#16A34A', blocked: '#E24B4A' }[s] || '#bbb'
}

// 报告视图（周报/月报共用）：展示后端生成的 Markdown 草稿 + 导出 Word
function ReportView({ report, loading, title, exportType }: {
  report: ReportOut | null
  loading: boolean
  title: string
  exportType: 'weekly' | 'monthly'
}) {
  if (loading) return <p style={{ color: '#888' }}>生成中…</p>
  if (!report) return null
  return (
    <div style={{ marginTop: 16 }}>
      <div style={panel}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
          <strong>{title}</strong>
          <span style={{ color: '#666', fontSize: 13 }}>{report.period_start} ~ {report.period_end}</span>
        </div>
        <div style={{ color: '#444', fontSize: 14, lineHeight: 1.7 }}>
          {report.markdown.split('\n').map((line, i) => {
            if (line.startsWith('## ')) return <h3 key={i} style={{ fontSize: 15, margin: '14px 0 6px' }}>{inline(line.slice(3))}</h3>
            if (line.startsWith('# ')) return <h2 key={i} style={{ fontSize: 18, margin: '8px 0' }}>{inline(line.slice(2))}</h2>
            if (line.startsWith('- ')) return <div key={i} style={{ margin: '3px 0 3px 16px' }}>• {inline(line.slice(2))}</div>
            if (line.trim() === '') return <div key={i} style={{ height: 8 }} />
            return <div key={i} style={{ margin: '3px 0', color: '#333' }}>{inline(line)}</div>
          })}
        </div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 12, gap: 12 }}>
        <p style={{ color: '#999', fontSize: 12, margin: 0 }}>
          聚合自 task(done)、doc(文档) 与 focus_session(工时)，靠 task_id 关联，零额外录入。可在此基础上手改后再导出 Word/PDF。
        </p>
        <div style={{ display: 'flex', gap: 8, whiteSpace: 'nowrap' }}>
          <a href={reportsApi.exportUrl(exportType, 'docx')} download
             style={{ ...tabBtn(false), background: '#185FA5', color: '#fff', textDecoration: 'none' }}>
            导出 Word
          </a>
          <a href={reportsApi.exportUrl(exportType, 'pdf')} download
             style={{ ...tabBtn(false), background: '#16A34A', color: '#fff', textDecoration: 'none' }}>
            导出 PDF
          </a>
        </div>
      </div>
    </div>
  )
}
function inline(s: string): React.ReactNode {
  const parts = s.split(/\*\*(.+?)\*\*/g)
  return parts.map((p, i) => (i % 2 ? <b key={i}>{p}</b> : <span key={i}>{p}</span>))
}

// ---------- 局部样式 ----------
function tabBtn(active: boolean): React.CSSProperties {
  return { padding: '6px 14px', borderRadius: 8, border: 'none', cursor: 'pointer', background: active ? '#185FA5' : '#f0f0f0', color: active ? '#fff' : '#555', fontSize: 14 }
}
const card: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8, padding: '9px 10px', borderRadius: 10, background: '#fff', border: '1px solid #eee',
}
const statusTag: React.CSSProperties = {
  fontSize: 11, padding: '2px 8px', borderRadius: 999, color: '#fff', whiteSpace: 'nowrap',
}
const iconBtn: React.CSSProperties = {
  border: 'none', background: 'transparent', color: '#bbb', cursor: 'pointer', fontSize: 16, padding: 6,
}
const miniInput: React.CSSProperties = {
  padding: '8px 10px', borderRadius: 6, border: '1px solid #ddd', fontSize: 14, background: '#fff',
}
const chk: React.CSSProperties = { fontSize: 13, color: '#444', display: 'flex', alignItems: 'center', gap: 4 }
const newForm: React.CSSProperties = {
  display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginTop: 16,
  background: '#f7f8fa', padding: 12, borderRadius: 12,
}
const panel: React.CSSProperties = {
  background: '#fff', border: '1px solid #eee', borderRadius: 12, padding: 18,
}
