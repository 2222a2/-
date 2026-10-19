import { useEffect, useMemo, useState } from 'react'
import { study, StudyTask, WeeklyProgress, DailyCompletion, setStudyToken } from '../api/client'

// 后端返回 401（口令错/未带）时，弹出口令框让用户重新输
function is401(e: any): boolean {
  return e?.response?.status === 401
}

// 科目 / 时间段 的中文标签与展示顺序（与后端 study_task 表枚举对齐）
const SUBJECT_LABELS: Record<string, string> = {
  math: '数学',
  english: '英语',
  cs408: '408',
  ds: '数据结构',
  other: '其他',
}
const SUBJECT_COLORS: Record<string, string> = {
  math: '#2F6FED',
  english: '#E0863A',
  cs408: '#8B5CF6',
  ds: '#16A34A',
  other: '#888',
}
const PERIOD_LABELS: Record<string, string> = {
  morning: '🌅 早上',
  noon: '☀️ 午间',
  evening: '🌙 晚上',
  other: '📌 其他',
}
const PERIOD_ORDER = ['morning', 'noon', 'evening', 'other']

function todayStr(d = new Date()): string {
  const z = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`
}
function shiftDate(date: string, days: number): string {
  const d = new Date(date + 'T00:00:00')
  d.setDate(d.getDate() + days)
  return todayStr(d)
}

export default function StudyTasksPage() {
  // 深链支持：微信链接 /study-tasks?date=YYYY-MM-DD 直接定位到那一天
  const initialDate = useMemo(() => {
    const p = new URLSearchParams(window.location.search).get('date')
    return p && /^\d{4}-\d{2}-\d{2}$/.test(p) ? p : todayStr()
  }, [])

  const [date, setDate] = useState(initialDate)
  const [view, setView] = useState<'day' | 'week' | 'heatmap' | 'month'>('day')
  const [tasks, setTasks] = useState<StudyTask[]>([])
  const [weekly, setWeekly] = useState<WeeklyProgress | null>(null)
  const [loading, setLoading] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [draftTitle, setDraftTitle] = useState('')
  // 今日到期未做的复习任务（"今日待复习"卡片）
  const [dueReviews, setDueReviews] = useState<StudyTask[]>([])
  // 进度热力图数据（近 90 天每日完成度）
  const [heatmap, setHeatmap] = useState<DailyCompletion[]>([])
  // 排课月视图：当前显示的月份锚点（YYYY-MM-01）与按日期分组的任务
  const [monthAnchor, setMonthAnchor] = useState<string>(() => todayStr().slice(0, 8) + '01')
  const [monthMap, setMonthMap] = useState<Record<string, StudyTask[]>>({})
  // 每段新增表单的本地状态（key = period，value = {subject, title}）
  const [addForm, setAddForm] = useState<Record<string, { subject: string; title: string }>>({})
  // 口令保护：后端设了 STUDY_PAGE_TOKEN 时，首次打开会被 401 拦截，这里弹框让用户输入
  const [needToken, setNeedToken] = useState(false)
  const [tokenInput, setTokenInput] = useState('')

  async function loadDay() {
    setLoading(true)
    try {
      const r = await study.listByDate(date)
      setTasks(r.data)
    } catch (e) {
      if (is401(e)) setNeedToken(true)
    } finally {
      setLoading(false)
    }
  }
  async function loadWeek() {
    setLoading(true)
    try {
      const r = await study.listWeekly(date)
      setWeekly(r.data)
    } catch (e) {
      if (is401(e)) setNeedToken(true)
    } finally {
      setLoading(false)
    }
  }
  function submitToken() {
    setStudyToken(tokenInput.trim())
    setNeedToken(false)
    setTokenInput('')
    if (view === 'day') loadDay()
    else loadWeek()
  }

  // 今日到期未做的复习任务（"今日待复习"卡片用），基于今天，与所选 date 无关
  async function loadDueReviews() {
    try {
      const r = await study.dueReviews(todayStr())
      setDueReviews(r.data)
    } catch (e) { if (is401(e)) setNeedToken(true) }
  }

  // 进度热力图：近 90 天每日完成度
  async function loadHeatmap() {
    setLoading(true)
    try {
      const r = await study.heatmap(90)
      setHeatmap(r.data)
    } catch (e) { if (is401(e)) setNeedToken(true) }
    finally { setLoading(false) }
  }

  // 排课月视图：拉取整月任务并按下 date 分组
  async function loadMonth() {
    setLoading(true)
    try {
      const [y, m] = monthAnchor.split('-').map(Number)
      const start = `${y}-${String(m).padStart(2, '0')}-01`
      const end = `${y}-${String(m).padStart(2, '0')}-${new Date(y, m, 0).getDate()}`
      const r = await study.listRange(start, end)
      const map: Record<string, StudyTask[]> = {}
      for (const t of r.data) (map[t.date] ||= []).push(t)
      setMonthMap(map)
    } catch (e) { if (is401(e)) setNeedToken(true) }
    finally { setLoading(false) }
  }

  // 上/下月切换（monthAnchor 移到相邻月 1 号）
  function shiftMonth(delta: number) {
    const [y, m] = monthAnchor.split('-').map(Number)
    const d = new Date(y, m - 1 + delta, 1)
    setMonthAnchor(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`)
  }

  useEffect(() => {
    if (view === 'day') { loadDay(); loadDueReviews() }
    else if (view === 'week') loadWeek()
    else if (view === 'month') loadMonth()
    else loadHeatmap()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [date, view, monthAnchor])

  // 按时间段分组（period 为空归到 other）
  const grouped = useMemo(() => {
    const map: Record<string, StudyTask[]> = {}
    for (const t of tasks) {
      const key = t.period && PERIOD_ORDER.includes(t.period) ? t.period : 'other'
      ;(map[key] ||= []).push(t)
    }
    for (const k of Object.keys(map)) map[k].sort((a, b) => a.sort_order - b.sort_order)
    return map
  }, [tasks])

  async function toggleDone(t: StudyTask) {
    try {
      await study.patch(t.id, { done: t.done ? 0 : 1 })
      setTasks((prev) => prev.map((x) => (x.id === t.id ? { ...x, done: t.done ? 0 : 1 } : x)))
      if (t.source === 'review') loadDueReviews()  // 复习勾掉后即时从"今日待复习"移除
    } catch (e) { if (is401(e)) setNeedToken(true) }
  }
  async function commitTitle(t: StudyTask) {
    setEditingId(null)
    const title = draftTitle.trim()
    if (!title || title === t.title) return
    try {
      await study.patch(t.id, { title })
      setTasks((prev) => prev.map((x) => (x.id === t.id ? { ...x, title } : x)))
    } catch (e) { if (is401(e)) setNeedToken(true) }
  }
  async function remove(t: StudyTask) {
    try {
      await study.remove(t.id)
      setTasks((prev) => prev.filter((x) => x.id !== t.id))
    } catch (e) { if (is401(e)) setNeedToken(true) }
  }
  async function addTask(period: string) {
    const f = addForm[period] || { subject: 'other', title: '' }
    const title = f.title.trim()
    if (!title) return
    const order = grouped[period]?.length || 0
    try {
      await study.add({
        date,
        period: period === 'other' ? '' : period,
        subject: f.subject,
        title,
        sort_order: order,
      })
      setAddForm((prev) => ({ ...prev, [period]: { subject: f.subject, title: '' } }))
      await loadDay()
    } catch (e) { if (is401(e)) setNeedToken(true) }
  }

  return (
    <div style={{ maxWidth: 920, width: '100%', margin: '0 auto', padding: '0 12px', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <h1 style={{ margin: 0, fontSize: 22 }}>📖 备考任务</h1>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button onClick={() => setView('day')} style={tabBtn(view === 'day')}>今日</button>
          <button onClick={() => setView('week')} style={tabBtn(view === 'week')}>本周进度</button>
          <button onClick={() => setView('heatmap')} style={tabBtn(view === 'heatmap')}>热力图</button>
          <button onClick={() => setView('month')} style={tabBtn(view === 'month')}>月视图</button>
        </div>
      </div>

      {view === 'day' ? (
        <>
          <DueReviewsCard items={dueReviews} onToggle={toggleDone} />

          <div style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '16px 0' }}>
            <button onClick={() => setDate(shiftDate(date, -1))} style={navBtn()} aria-label="前一天">←</button>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} style={{ ...navBtn(), cursor: 'text' }} />
            <button onClick={() => setDate(shiftDate(date, 1))} style={navBtn()} aria-label="后一天">→</button>
            {date !== todayStr() && (
              <button onClick={() => setDate(todayStr())} style={{ ...navBtn(), color: '#185FA5' }}>回到今天</button>
            )}
          </div>

          {loading && <p style={{ color: '#888' }}>加载中…</p>}
          {!loading && tasks.length === 0 && (
            <p style={{ color: '#999', padding: 24, textAlign: 'center', background: '#fafafa', borderRadius: 10 }}>
              这一天还没有任务。生成器会在每天 23:00 自动建好明天的计划；你也可以在下方面板手动加。
            </p>
          )}

          {PERIOD_ORDER.map((period) => {
            const list = grouped[period] || []
            return (
              <section key={period} style={{ marginBottom: 20 }}>
                <h3 style={{ margin: '0 0 8px', fontSize: 16, color: '#333' }}>
                  {PERIOD_LABELS[period]} <span style={{ color: '#bbb', fontSize: 13 }}>· {list.length} 项</span>
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {list.map((t) => (
                    <div key={t.id} style={{ ...card(!!t.done), ...reviewStyle(t) }}>
                      <input type="checkbox" checked={!!t.done} onChange={() => toggleDone(t)} style={{ width: 18, height: 18 }} />
                      {editingId === t.id ? (
                        <input
                          autoFocus
                          value={draftTitle}
                          onChange={(e) => setDraftTitle(e.target.value)}
                          onBlur={() => commitTitle(t)}
                          onKeyDown={(e) => { if (e.key === 'Enter') commitTitle(t); if (e.key === 'Escape') setEditingId(null) }}
                          style={{ flex: 1, padding: '4px 8px', borderRadius: 6, border: '1px solid #ccc', fontSize: 14 }}
                        />
                      ) : (
                        <span
                          onClick={() => { setEditingId(t.id); setDraftTitle(t.title) }}
                          style={{ flex: 1, cursor: 'text', textDecoration: t.done ? 'line-through' : 'none', color: t.done ? '#aaa' : '#222' }}
                          title="点击改标题"
                        >
                          {t.title}
                        </span>
                      )}
                      {t.source === 'review' && (
                        <span style={reviewTag()}>复习 · 第{t.review_stage}轮</span>
                      )}
                      {t.subject && (
                        <span style={subjectTag(t.subject)}>{SUBJECT_LABELS[t.subject] || t.subject}</span>
                      )}
                      {t.source === 'manual' && <span style={{ fontSize: 11, color: '#999' }}>手动</span>}
                      <button onClick={() => remove(t)} style={delBtn()} title="删除">✕</button>
                    </div>
                  ))}

                  {/* 每段底部的新增表单 */}
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 4, flexWrap: 'wrap' }}>
                    <select
                      value={(addForm[period]?.subject) || 'other'}
                      onChange={(e) => setAddForm((p) => ({ ...p, [period]: { ...(p[period] || { title: '' }), subject: e.target.value } }))}
                      style={miniInput()}
                    >
                      {Object.entries(SUBJECT_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    </select>
                    <input
                      placeholder="加一条任务…"
                      value={(addForm[period]?.title) || ''}
                      onChange={(e) => setAddForm((p) => ({ ...p, [period]: { ...(p[period] || { subject: 'other' }), title: e.target.value } }))}
                      onKeyDown={(e) => { if (e.key === 'Enter') addTask(period) }}
                      style={{ ...miniInput(), flex: '1 1 120px' }}
                    />
                    <button onClick={() => addTask(period)} style={{ ...miniInput(), background: '#185FA5', color: '#fff', cursor: 'pointer', border: 'none' }}>+ 加</button>
                  </div>
                </div>
              </section>
            )
          })}
        </>
      ) : view === 'week' ? (
        <WeekView weekly={weekly} loading={loading} />
      ) : view === 'month' ? (
        <MonthView
          anchor={monthAnchor}
          onPrev={() => shiftMonth(-1)}
          onNext={() => shiftMonth(1)}
          onPick={(d) => { setDate(d); setView('day') }}
          monthMap={monthMap}
        />
      ) : (
        <StudyHeatmap data={heatmap} onPick={(d) => { setDate(d); setView('day') }} />
      )}

      {/* 口令保护弹层：后端设了 STUDY_PAGE_TOKEN 且未带/带错时显示 */}
      {needToken && (
        <div style={gateOverlay}>
          <div style={gateBox}>
            <h2 style={{ margin: '0 0 6px', fontSize: 18 }}>🔒 请输入访问口令</h2>
            <p style={{ color: '#666', fontSize: 13, marginTop: 0, lineHeight: 1.5 }}>
              这个备考页加了口令，防止公网/同网别人误改。<br />
              口令就是你在环境变量 <code>STUDY_PAGE_TOKEN</code> 里设的那串。
            </p>
            <input
              type="password"
              value={tokenInput}
              autoFocus
              placeholder="输入口令"
              onChange={(e) => setTokenInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') submitToken() }}
              style={gateInput}
            />
            <button onClick={submitToken} style={{ ...gateInput, background: '#185FA5', color: '#fff', border: 'none', cursor: 'pointer' }}>
              进入
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// 今日待复习卡片：列出今天到期未做的复习任务（艾宾浩斯节点），勾掉即打卡
function DueReviewsCard({ items, onToggle }: { items: StudyTask[]; onToggle: (t: StudyTask) => void }) {
  if (items.length === 0) return null
  return (
    <div style={{ background: '#FFF7E6', border: '1px solid #FFE0A3', borderRadius: 12, padding: 14, margin: '12px 0' }}>
      <div style={{ fontWeight: 600, marginBottom: 8, color: '#B26A00' }}>🔁 今日待复习（{items.length}）</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {items.map((t) => (
          <div key={t.id} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <input type="checkbox" checked={false} onChange={() => onToggle(t)} style={{ width: 18, height: 18 }} />
            <span style={{ flex: 1, cursor: 'pointer', color: '#8a5a00' }} onClick={() => onToggle(t)}>{t.title}</span>
            <span style={{ fontSize: 11, color: '#B26A00', background: '#FFE9C2', padding: '2px 8px', borderRadius: 999, whiteSpace: 'nowrap' }}>
              第{t.review_stage}轮 · 学后第{t.due_offset}天
            </span>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 11, color: '#B8860B', marginTop: 8 }}>勾掉即算复习打卡，不影响原计划任务。</div>
    </div>
  )
}

// 学习进度热力图：近 90 天每日完成率网格，色阶映射 rate；点格跳当天
function StudyHeatmap({ data, onPick }: { data: DailyCompletion[]; onPick: (date: string) => void }) {
  if (data.length === 0) {
    return <p style={{ color: '#999', padding: 24, textAlign: 'center', background: '#fafafa', borderRadius: 10 }}>暂无数据，先去「今日」勾几天的任务吧。</p>
  }
  const heatColor = (rate: number) => {
    if (rate <= 0) return '#eee'
    const a = Math.max(0.15, Math.min(1, rate))
    return `rgba(24,95,165,${a.toFixed(2)})`
  }
  return (
    <div style={{ marginTop: 16 }}>
      <h3 style={{ fontSize: 15, margin: '0 0 8px' }}>📊 学习进度热力图（近 90 天）</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 4 }}>
        {data.map((d) => (
          <div
            key={d.date}
            title={`${d.date}：${d.done}/${d.total} 完成（${Math.round(d.rate * 100)}%）`}
            onClick={() => onPick(d.date)}
            style={{
              aspectRatio: '1 / 1',
              background: heatColor(d.rate),
              borderRadius: 4,
              cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 10, color: d.rate > 0.5 ? '#fff' : '#666',
            }}
          >
            {d.date.slice(5)}
          </div>
        ))}
      </div>
      <div style={{ fontSize: 11, color: '#999', marginTop: 8 }}>
        颜色越深 = 当天完成率越高；点任意格子跳到那一天。
      </div>
    </div>
  )
}

// 排课月视图：当月日历，每格完成率底色 + 已完成/总数角标，点格跳当天去勾任务
function MonthView({ anchor, onPrev, onNext, onPick, monthMap }: {
  anchor: string
  onPrev: () => void
  onNext: () => void
  onPick: (date: string) => void
  monthMap: Record<string, StudyTask[]>
}) {
  const [y, m] = anchor.split('-').map(Number)
  const firstWeekday = new Date(y, m - 1, 1).getDay() // 0=周日
  const daysInMonth = new Date(y, m, 0).getDate()
  const lead = (firstWeekday + 6) % 7 // 周一开头：周日排到最后
  const cells: (number | null)[] = []
  for (let i = 0; i < lead; i++) cells.push(null)
  for (let d = 1; d <= daysInMonth; d++) cells.push(d)
  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <button onClick={onPrev} style={navBtn()}>← 上月</button>
        <strong style={{ fontSize: 16 }}>{y}年{m}月</strong>
        <button onClick={onNext} style={navBtn()}>下月 →</button>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 4, marginBottom: 4 }}>
        {['一', '二', '三', '四', '五', '六', '日'].map((w) => (
          <div key={w} style={{ textAlign: 'center', fontSize: 12, color: '#999' }}>{w}</div>
        ))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 4 }}>
        {cells.map((d, i) => {
          if (d === null) return <div key={`e${i}`} />
          const ds = `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`
          const list = monthMap[ds] || []
          const done = list.filter((t) => t.done).length
          const rate = list.length ? done / list.length : 0
          return (
            <div
              key={ds}
              onClick={() => onPick(ds)}
              title={`${ds}：${done}/${list.length} 完成`}
              style={{
                minHeight: 64, borderRadius: 6, cursor: 'pointer', padding: 6,
                background: rate > 0 ? `rgba(24,95,165,${Math.max(0.15, rate).toFixed(2)})` : '#f5f5f5',
                border: ds === todayStr() ? '2px solid #185FA5' : '1px solid #eee',
                color: rate > 0.5 ? '#fff' : '#333',
              }}
            >
              <div style={{ fontSize: 12, fontWeight: 600 }}>{d}</div>
              {list.length > 0 && (
                <div style={{ fontSize: 11, marginTop: 4 }}>✓ {done}/{list.length}</div>
              )}
            </div>
          )
        })}
      </div>
      <div style={{ fontSize: 11, color: '#999', marginTop: 8 }}>
        底色深浅 = 当天完成率；数字 = 已完成/总数；点格子跳到那一天去勾任务。
      </div>
    </div>
  )
}

function WeekView({ weekly, loading }: { weekly: WeeklyProgress | null; loading: boolean }) {
  if (loading) return <p style={{ color: '#888' }}>加载中…</p>
  if (!weekly) return null
  const dates = (() => {
    const out: string[] = []
    const d = new Date(weekly.week_start + 'T00:00:00')
    for (let i = 0; i < 7; i++) { out.push(todayStr(d)); d.setDate(d.getDate() + 1) }
    return out
  })()
  const weekday = ['一', '二', '三', '四', '五', '六', '日']
  return (
    <div style={{ marginTop: 16 }}>
      <div style={panel}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
          <strong>本周完成度</strong>
          <span style={{ color: '#666' }}>{weekly.week_start} ~ {weekly.week_end}</span>
        </div>
        <div style={{ height: 14, background: '#eee', borderRadius: 7, overflow: 'hidden' }}>
          <div style={{ width: `${Math.round(weekly.rate * 100)}%`, height: '100%', background: '#185FA5' }} />
        </div>
        <div style={{ marginTop: 6, color: '#444' }}>
          {weekly.done} / {weekly.total} 完成 · <b>{Math.round(weekly.rate * 100)}%</b>
        </div>
      </div>

      <h3 style={{ fontSize: 15, margin: '20px 0 8px' }}>各科完成率</h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {Object.entries(weekly.by_subject).map(([s, v]) => {
          const rate = v.total ? v.done / v.total : 0
          return (
            <div key={s} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ width: 64, fontSize: 13 }}>{SUBJECT_LABELS[s] || s}</span>
              <div style={{ flex: 1, height: 12, background: '#eee', borderRadius: 6, overflow: 'hidden' }}>
                <div style={{ width: `${Math.round(rate * 100)}%`, height: '100%', background: SUBJECT_COLORS[s] || '#185FA5' }} />
              </div>
              <span style={{ width: 56, fontSize: 12, color: '#666', textAlign: 'right' }}>{v.done}/{v.total}</span>
            </div>
          )
        })}
      </div>

      <h3 style={{ fontSize: 15, margin: '20px 0 8px' }}>每日完成率</h3>
      <div style={{ display: 'flex', gap: 6 }}>
        {dates.map((d, i) => {
          const v = weekly.by_date[d]
          const rate = v && v.total ? v.done / v.total : 0
          const isToday = d === todayStr()
          return (
            <div key={d} style={{ flex: 1, textAlign: 'center' }}>
              <div style={{
                height: 60, display: 'flex', alignItems: 'flex-end', justifyContent: 'center',
                background: '#f5f5f5', borderRadius: 6, overflow: 'hidden', border: isToday ? '2px solid #185FA5' : 'none',
              }}>
                <div style={{ width: '100%', height: `${Math.round(rate * 100)}%`, background: '#185FA5', minHeight: v ? 2 : 0 }} />
              </div>
              <div style={{ fontSize: 11, color: '#666', marginTop: 4 }}>{weekday[i]}</div>
              <div style={{ fontSize: 10, color: '#aaa' }}>{d.slice(5)}</div>
            </div>
          )
        })}
      </div>
      <p style={{ color: '#999', fontSize: 12, marginTop: 16 }}>
        数据来自 study_task 表，按“周一~周日”聚合。周复盘看这里，不靠每天自责。
      </p>
    </div>
  )
}

// ---------- 局部样式 ----------
function tabBtn(active: boolean): React.CSSProperties {
  return {
    padding: '6px 14px', borderRadius: 8, border: 'none', cursor: 'pointer',
    background: active ? '#185FA5' : '#f0f0f0', color: active ? '#fff' : '#555', fontSize: 14,
  }
}
function navBtn(): React.CSSProperties {
  return { padding: '8px 12px', borderRadius: 8, border: '1px solid #ddd', background: '#fff', cursor: 'pointer', fontSize: 14 }
}
function card(done: boolean): React.CSSProperties {
  return {
    display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', borderRadius: 10,
    background: done ? '#fafafa' : '#fff', border: '1px solid #eee',
  }
}
function subjectTag(subject: string): React.CSSProperties {
  return {
    fontSize: 12, padding: '2px 8px', borderRadius: 999, color: '#fff',
    background: SUBJECT_COLORS[subject] || '#888', whiteSpace: 'nowrap',
  }
}
// 复习任务卡片：浅黄底色区分"新学"；非复习任务返回空（不覆盖默认 card 样式）
function reviewStyle(t: StudyTask): React.CSSProperties {
  if (t.source !== 'review') return {}
  return {
    background: t.done ? '#fdf6ec' : '#fffaf0',
    borderColor: t.done ? '#f0e0c0' : '#ffe0a3',
  }
}
// 复习任务的小标签样式（"复习 · 第N轮"）
function reviewTag(): React.CSSProperties {
  return {
    fontSize: 11, color: '#B26A00', background: '#FFE9C2',
    padding: '2px 8px', borderRadius: 999, whiteSpace: 'nowrap',
  }
}
function delBtn(): React.CSSProperties {
  return { border: 'none', background: 'transparent', color: '#bbb', cursor: 'pointer', fontSize: 18, padding: 8 }
}
function miniInput(): React.CSSProperties {
  return { padding: '10px 10px', borderRadius: 6, border: '1px solid #ddd', fontSize: 14, background: '#fff' }
}
const panel: React.CSSProperties = {
  background: '#fff', border: '1px solid #eee', borderRadius: 12, padding: 16,
}

// 口令弹层（移动端也居中、可点）
const gateOverlay: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
  display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 999, padding: 16,
}
const gateBox: React.CSSProperties = {
  background: '#fff', borderRadius: 14, padding: 24, maxWidth: 360, width: '100%',
  boxShadow: '0 10px 40px rgba(0,0,0,0.2)', textAlign: 'center',
}
const gateInput: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box', padding: '12px 14px', borderRadius: 10,
  border: '1px solid #ccc', fontSize: 16, marginTop: 12,
}
