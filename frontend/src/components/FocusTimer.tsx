import { useState } from 'react'
import { useFocus } from './FocusProvider'

function fmt(s: number): string {
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = s % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${pad(h)}:${pad(m)}:${pad(ss)}` : `${pad(m)}:${pad(ss)}`
}

// 全局悬浮专注计时器：专注中常驻右下角，显示番茄钟阶段/倒计时、停止、勿扰、时长设置。
// 由 FocusProvider 提供状态，任何页面（任务/资料/分析）都能看到并操作。
export function FocusTimer() {
  const { active, seconds, mode, modeRemaining, workMin, breakMin, stop, toggleDnd, setPrefs } = useFocus()
  const [showSettings, setShowSettings] = useState(false)
  const [wf, setWf] = useState(workMin)
  const [bf, setBf] = useState(breakMin)

  if (!active) return null
  return (
    <div
      style={{
        position: 'fixed',
        right: 16,
        bottom: 16,
        zIndex: 1000,
        background: '#fff',
        border: '1px solid #185FA5',
        borderRadius: 12,
        padding: '10px 14px',
        boxShadow: '0 6px 24px rgba(0,0,0,0.15)',
        minWidth: 220,
        fontFamily: 'system-ui',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#185FA5', fontWeight: 600 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: mode === 'work' ? '#E24B4A' : '#16A34A', display: 'inline-block' }} />
          {active.dnd ? '🔕 勿扰专注' : mode === 'work' ? '🎯 专注中（工作）' : '☕ 休息中'}
        </div>
        <button
          onClick={() => { setWf(workMin); setBf(breakMin); setShowSettings((v) => !v) }}
          title="设置番茄钟时长"
          style={{ border: 'none', background: 'transparent', cursor: 'pointer', fontSize: 14, color: '#185FA5' }}
        >
          ⚙
        </button>
      </div>

      {/* 番茄钟阶段倒计时（本阶段剩余） */}
      <div style={{ fontSize: 30, fontWeight: 700, margin: '4px 0', fontVariantNumeric: 'tabular-nums', color: mode === 'work' ? '#185FA5' : '#16A34A' }}>
        {fmt(modeRemaining)}
      </div>
      <div style={{ fontSize: 11, color: '#999', marginBottom: 6 }}>
        本次专注总时长 {fmt(seconds)} · {mode === 'work' ? `工作 ${workMin} 分钟` : `休息 ${breakMin} 分钟`}
      </div>

      <div
        style={{
          fontSize: 12,
          color: '#666',
          marginBottom: 8,
          maxWidth: 200,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {active.taskId ? `任务：${active.title}` : active.title}
      </div>

      {showSettings && (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8, background: '#f7f8fa', padding: 8, borderRadius: 8 }}>
          <label style={{ fontSize: 12, color: '#444' }}>工作<input type="number" min={1} max={120} value={wf} onChange={(e) => setWf(Number(e.target.value) || 25)} style={{ width: 46, marginLeft: 4 }} /></label>
          <label style={{ fontSize: 12, color: '#444' }}>休息<input type="number" min={1} max={60} value={bf} onChange={(e) => setBf(Number(e.target.value) || 5)} style={{ width: 46, marginLeft: 4 }} /></label>
          <button
            onClick={() => { setPrefs(wf, bf); setShowSettings(false) }}
            style={{ background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, padding: '4px 8px', cursor: 'pointer', fontSize: 12 }}
          >保存</button>
        </div>
      )}

      <div style={{ display: 'flex', gap: 8 }}>
        <button
          onClick={stop}
          style={{ flex: 1, background: '#185FA5', color: '#fff', border: 'none', borderRadius: 8, padding: '6px 10px', cursor: 'pointer', fontSize: 13 }}
        >
          停止并记工时
        </button>
        <button
          onClick={toggleDnd}
          style={{ background: active.dnd ? '#E24B4A' : '#f0f0f0', color: active.dnd ? '#fff' : '#555', border: 'none', borderRadius: 8, padding: '6px 10px', cursor: 'pointer', fontSize: 13 }}
        >
          {active.dnd ? '取消勿扰' : '勿扰'}
        </button>
      </div>
    </div>
  )
}
