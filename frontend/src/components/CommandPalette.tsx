import { useEffect, useRef, useState } from 'react'
import { command, knowledge, docsApi } from '../api/client'
import { useDoc } from './DocEditorProvider'

// 统一命令面板：全站唯一入口（呼应“零跳转”）。
// 逻辑：Ctrl/Cmd+K 任意页面唤起 → 输入一句话 → 后端规则+AI 混合路由给出 action
//       → 前端本地执行（建任务 / 搜资料 / 生成报告 / AI 兜底）。
// 为什么做：把“想做啥”从点菜单变成“说一句”，是平台入口层，其余模块都挂在它下面。
export default function CommandPalette() {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const { openDoc } = useDoc()

  // 全局快捷键唤起 / 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen((v) => !v)
      } else if (e.key === 'Escape') {
        setOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 30)
  }, [open])

  const run = async () => {
    if (!text.trim()) return
    setLoading(true)
    setErr(null)
    setResult(null)
    try {
      const res = await command(text)
      const r = res.data
      // 根据 action 本地执行，让命令面板真正“能动手”
      if (r.action === 'create_task') {
        // 交给 agent 实际执行建任务工具
        const ag = await command(text) // 同一入口：agent 兜底会跑 create_task
        setResult({ ...r, preview: ag.data.preview || r.preview, steps: ag.data.steps })
      } else if (r.action === 'search_knowledge') {
        const q = (r.params?.query || text).replace(/(搜索|查资料|搜)\s*/, '')
        const sr = await knowledge.list(q)
        setResult({ ...r, search: sr.data })
      } else if (r.action === 'gen_doc') {
        // 调后端生成真实 Office 文件，并把返回的 OnlyOffice 配置直接打开编辑器
        const g = await docsApi.generate({
          prompt: r.params?.prompt || text,
          doc_type: r.params?.doc_type || 'word',
        })
        openDoc(g.data.editor_config)
        setResult({ ...r, preview: `${r.preview} · 已打开编辑器`, docId: g.data.doc.id })
      } else {
        setResult(r)
      }
    } catch (e: any) {
      setErr(String(e?.response?.data?.detail || e))
    } finally {
      setLoading(false)
    }
  }

  if (!open) return null

  return (
    <div
      style={overlay}
      onClick={() => setOpen(false)}
    >
      <div style={box} onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          value={text}
          placeholder="说一句：新建任务 写周报 / 搜一下 OKR 方案 / 记笔记…"
          style={input}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') run()
          }}
        />
        {loading && <div style={{ padding: 12, color: '#888' }}>执行中…</div>}
        {err && <div style={{ padding: 12, color: '#E24B4A' }}>{err}</div>}
        {result && <ResultView result={result} />}
        <div style={{ padding: '8px 12px', color: '#aaa', fontSize: 12 }}>
          ⌘/Ctrl + K 开关 · Enter 执行 · Esc 关闭
        </div>
      </div>
    </div>
  )
}

function ResultView({ result }: { result: any }) {
  return (
    <div style={{ padding: 12, borderTop: '1px solid #eee', maxHeight: 320, overflow: 'auto' }}>
      <div style={{ marginBottom: 6 }}>
        <b>动作：</b>
        {result.action || 'agent'} ｜ <span style={{ color: '#185FA5' }}>{result.preview}</span>
      </div>
      {result.search?.results?.length ? (
        <div>
          <div style={{ color: '#888', fontSize: 12, marginBottom: 4 }}>检索到 {result.search.results.length} 条：</div>
          {result.search.results.map((h: any) => (
            <div key={h.source_id} style={{ padding: '6px 0', borderBottom: '1px dashed #eee' }}>
              <div style={{ fontWeight: 600 }}>{h.title}</div>
              <div style={{ fontSize: 13, color: '#555' }}>{h.body}</div>
            </div>
          ))}
        </div>
      ) : null}
      {result.steps?.length ? (
        <div style={{ marginTop: 6 }}>
          {result.steps.map((s: any, i: number) => (
            <div key={i} style={{ fontSize: 13, color: '#444', padding: '2px 0' }}>
              [{s.type}] {s.name || ''} {s.content || ''}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

const overlay: React.CSSProperties = {
  position: 'fixed',
  inset: 0,
  background: 'rgba(0,0,0,0.25)',
  display: 'flex',
  justifyContent: 'center',
  alignItems: 'flex-start',
  paddingTop: '12vh',
  zIndex: 1000,
}
const box: React.CSSProperties = {
  background: '#fff',
  width: 'min(640px, 92vw)',
  borderRadius: 12,
  boxShadow: '0 8px 30px rgba(0,0,0,0.18)',
  overflow: 'hidden',
}
const input: React.CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  border: 'none',
  outline: 'none',
  padding: '16px 18px',
  fontSize: 16,
}
