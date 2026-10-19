import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { focusApi, prefsApi, type FocusSession } from '../api/client'

export interface ActiveFocus {
  id: number
  taskId: number | null
  title: string
  startedAt: string // 'YYYY-MM-DD HH:MM:SS'
  dnd: boolean // 勿扰开关
}

interface FocusCtx {
  active: ActiveFocus | null
  seconds: number // 本次专注总时长（秒）
  mode: 'work' | 'break' // 番茄钟当前阶段
  modeRemaining: number // 当前阶段剩余秒
  workMin: number
  breakMin: number
  start: (taskId?: number | null, title?: string) => Promise<void>
  stop: () => Promise<void>
  toggleDnd: () => void
  setPrefs: (work: number, brk: number) => Promise<void>
}

const Ctx = createContext<FocusCtx | null>(null)

export function useFocus(): FocusCtx {
  const c = useContext(Ctx)
  if (!c) throw new Error('useFocus 必须在 <FocusProvider> 内使用')
  return c
}

// 把后端 'YYYY-MM-DD HH:MM:SS' 转成可 new Date 的 ISO 字符串
function toIso(s: string): string {
  return s.replace(' ', 'T')
}

export function FocusProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState<ActiveFocus | null>(null)
  const [seconds, setSeconds] = useState(0) // 本次专注总时长
  const [mode, setMode] = useState<'work' | 'break'>('work')
  const [modeRemaining, setModeRemaining] = useState(0) // 当前阶段剩余秒
  const [workMin, setWorkMin] = useState(25)
  const [breakMin, setBreakMin] = useState(5)
  const timer = useRef<number | null>(null)

  // 用 ref 持有最新值，供每秒定时器闭包读取（避免闭包捕获到旧值）
  const modeRef = useRef<'work' | 'break'>('work')
  const workMinRef = useRef(workMin)
  const breakMinRef = useRef(breakMin)
  const modeStartRef = useRef<number>(0)

  function startTicking(startedAt: string) {
    stopTicking()
    const base = new Date(toIso(startedAt)).getTime()
    modeStartRef.current = base
    const update = () => {
      const now = Date.now()
      setSeconds(Math.max(0, Math.floor((now - base) / 1000)))
      const thr = (modeRef.current === 'work' ? workMinRef.current : breakMinRef.current) * 60
      let me = Math.floor((now - modeStartRef.current) / 1000)
      if (thr > 0 && me >= thr) {
        // 到点切换工作/休息阶段，重置本阶段起点
        const next: 'work' | 'break' = modeRef.current === 'work' ? 'break' : 'work'
        modeRef.current = next
        setMode(next)
        modeStartRef.current = now
        me = 0
      }
      setModeRemaining(Math.max(0, thr - me))
    }
    update()
    timer.current = window.setInterval(update, 1000)
  }
  function stopTicking() {
    if (timer.current) {
      clearInterval(timer.current)
      timer.current = null
    }
  }

  // 挂载时：恢复进行中的专注 + 读取番茄钟偏好（落库复用）
  useEffect(() => {
    prefsApi
      .get()
      .then((r) => {
        setWorkMin(r.data.work_minutes)
        setBreakMin(r.data.break_minutes)
        workMinRef.current = r.data.work_minutes
        breakMinRef.current = r.data.break_minutes
      })
      .catch(() => {})
    focusApi
      .active()
      .then((r) => {
        const s = r.data.session as FocusSession | null
        if (s && !s.ended_at) {
          const af: ActiveFocus = {
            id: s.id,
            taskId: s.task_id,
            title: s.task_title || '专注中',
            startedAt: s.started_at!,
            dnd: false,
          }
          setActive(af)
          startTicking(af.startedAt)
        }
      })
      .catch(() => {})
    return () => stopTicking()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function start(taskId?: number | null, title?: string) {
    // 一次只专注一件事：若已有进行中的，先停掉旧的再开新的
    if (active) {
      await focusApi.stop(active.id).catch(() => {})
      stopTicking()
    }
    const r = await focusApi.start(taskId)
    const af: ActiveFocus = {
      id: r.data.id,
      taskId: taskId ?? null,
      title: title || '专注中',
      startedAt: new Date().toISOString().slice(0, 19).replace('T', ' '),
      dnd: false,
    }
    setActive(af)
    modeRef.current = 'work'
    setMode('work')
    modeStartRef.current = new Date(toIso(af.startedAt)).getTime()
    startTicking(af.startedAt)
  }

  async function stop() {
    if (!active) return
    await focusApi.stop(active.id).catch(() => {})
    stopTicking()
    setActive(null)
    setSeconds(0)
    setModeRemaining(0)
  }

  function toggleDnd() {
    setActive((a) => (a ? { ...a, dnd: !a.dnd } : a))
  }

  async function setPrefs(work: number, brk: number) {
    await prefsApi.update({ work_minutes: work, break_minutes: brk }).catch(() => {})
    setWorkMin(work)
    setBreakMin(brk)
    workMinRef.current = work
    breakMinRef.current = brk
  }

  return (
    <Ctx.Provider value={{ active, seconds, mode, modeRemaining, workMin, breakMin, start, stop, toggleDnd, setPrefs }}>
      {children}
    </Ctx.Provider>
  )
}
