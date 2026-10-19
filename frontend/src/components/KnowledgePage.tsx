import { useEffect, useState } from 'react'
import { knowledge } from '../api/client'

// 资料聚合底座的前端脸面：四个入库通道 + 列表/搜索/删除。
// 作用：让用户把网页、文件、笔记随手变成可检索资料；也是验证“入库即可搜到”的界面。
const SOURCE_LABEL: Record<string, string> = {
  web_clip: '🌐 网页剪藏',
  upload: '📎 上传',
  note: '📝 笔记',
  task_doc: '📄 任务文档',
}

export default function KnowledgePage() {
  const [tab, setTab] = useState<'clip' | 'note' | 'upload'>('note')
  const [url, setUrl] = useState('')
  const [note, setNote] = useState('')
  const [q, setQ] = useState('')
  const [cards, setCards] = useState<any[]>([])
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const refresh = async (query?: string) => {
    try {
      const r = await knowledge.list(query ? { q: query } : undefined)
      setCards(query ? r.data.results || [] : r.data.cards || [])
    } catch (e: any) {
      setErr(String(e?.response?.data?.detail || e))
    }
  }

  useEffect(() => {
    refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const done = (m: string) => {
    setMsg(m)
    setErr(null)
    setUrl('')
    setNote('')
    refresh(q || undefined)
    setTimeout(() => setMsg(null), 2500)
  }

  const doClip = async () => {
    if (!url.trim()) return
    setBusy(true)
    try {
      const r = await knowledge.clip(url.trim())
      done(`已剪藏：${r.data.title}`)
    } catch (e: any) {
      setErr(String(e?.response?.data?.detail || e))
    } finally {
      setBusy(false)
    }
  }

  const doNote = async () => {
    if (!note.trim()) return
    setBusy(true)
    try {
      await knowledge.note(note.trim())
      done('笔记已保存')
    } catch (e: any) {
      setErr(String(e?.response?.data?.detail || e))
    } finally {
      setBusy(false)
    }
  }

  const doUpload = async (file: File) => {
    setBusy(true)
    try {
      await knowledge.upload(file)
      done(`已入库文件：${file.name}`)
    } catch (e: any) {
      setErr(String(e?.response?.data?.detail || e))
    } finally {
      setBusy(false)
    }
  }

  const doDelete = async (id: number) => {
    if (!confirm(`删除资料 #${id}？`)) return
    try {
      await knowledge.remove(id)
      refresh(q || undefined)
    } catch (e: any) {
      setErr(String(e?.response?.data?.detail || e))
    }
  }

  return (
    <div style={{ maxWidth: 880, margin: '0 auto' }}>
      <h2 style={{ marginBottom: 4 }}>资料聚合底座</h2>
      <p style={{ color: '#666', marginTop: 0 }}>
        把网页、文件、笔记随手存进来，全站可搜、可被 AI 引用（⌘/Ctrl+K 也能直接调）。
      </p>

      {/* 入库通道切换 */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        {(['note', 'clip', 'upload'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              padding: '8px 14px',
              borderRadius: 8,
              border: '1px solid #ddd',
              background: tab === t ? '#185FA5' : '#fff',
              color: tab === t ? '#fff' : '#333',
              cursor: 'pointer',
            }}
          >
            {t === 'note' ? '✍️ 记笔记' : t === 'clip' ? '🔗 网页剪藏' : '📤 上传文件'}
          </button>
        ))}
      </div>

      {/* 各通道输入区 */}
      {tab === 'note' && (
        <div style={cardBox}>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="写点什么…会自动进资料库"
            style={{ width: '100%', minHeight: 90, padding: 10, borderRadius: 8, border: '1px solid #ddd', resize: 'vertical' }}
          />
          <button disabled={busy} onClick={doNote} style={btn}>保存笔记</button>
        </div>
      )}
      {tab === 'clip' && (
        <div style={cardBox}>
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="粘贴网页链接，如 https://..."
            style={{ width: '100%', padding: 10, borderRadius: 8, border: '1px solid #ddd' }}
          />
          <button disabled={busy} onClick={doClip} style={btn}>剪藏</button>
          <span style={{ fontSize: 12, color: '#999' }}>需要网络抓取正文</span>
        </div>
      )}
      {tab === 'upload' && (
        <div style={cardBox}>
          <input
            type="file"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) doUpload(f)
            }}
          />
          <span style={{ fontSize: 12, color: '#999' }}>支持 txt/md/pdf/docx（pdf/docx 需后端装对应库）</span>
        </div>
      )}

      {msg && <div style={{ color: '#2e7d32', margin: '8px 0' }}>{msg}</div>}
      {err && <div style={{ color: '#E24B4A', margin: '8px 0' }}>{err}</div>}

      {/* 搜索 + 列表 */}
      <div style={{ display: 'flex', gap: 8, margin: '16px 0 8px' }}>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && refresh(q)}
          placeholder="站内搜索资料…"
          style={{ flex: 1, padding: 10, borderRadius: 8, border: '1px solid #ddd' }}
        />
        <button onClick={() => refresh(q)} style={btn}>搜索</button>
      </div>

      <div>
        {cards.length === 0 && <div style={{ color: '#999', padding: 12 }}>暂无资料</div>}
        {cards.map((c: any) => (
          <div
            key={c.id}
            style={{ border: '1px solid #eee', borderRadius: 10, padding: 12, marginBottom: 10 }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <b>{c.title || '(无标题)'}</b>{' '}
                <span style={{ fontSize: 12, color: '#999' }}>
                  {SOURCE_LABEL[c.source_type] || c.source_type} · #{c.id}
                </span>
              </div>
              <button onClick={() => doDelete(c.id)} style={{ ...btn, background: '#fff', color: '#E24B4A', border: '1px solid #E24B4A' }}>
                删除
              </button>
            </div>
            <div style={{ fontSize: 13, color: '#555', marginTop: 6, whiteSpace: 'pre-wrap', maxHeight: 120, overflow: 'auto' }}>
              {c.content || c.body || ''}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

const cardBox: React.CSSProperties = {
  border: '1px solid #eee',
  borderRadius: 10,
  padding: 14,
  background: '#fafafa',
  display: 'flex',
  flexDirection: 'column',
  gap: 10,
}
const btn: React.CSSProperties = {
  padding: '8px 14px',
  borderRadius: 8,
  border: 'none',
  background: '#185FA5',
  color: '#fff',
  cursor: 'pointer',
  alignSelf: 'flex-start',
}
