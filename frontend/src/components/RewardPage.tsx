import { useEffect, useState } from 'react'
import { reward, RewardState, RewardBadgeDef, RewardVideo } from '../api/client'

function todayStr(d = new Date()): string {
  const z = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`
}

const card: React.CSSProperties = {
  background: '#fff',
  border: '1px solid #eee',
  borderRadius: 12,
  padding: 20,
  boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
}

const grid2: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
  gap: 16,
  marginBottom: 20,
}

export default function RewardPage() {
  const [state, setState] = useState<RewardState | null>(null)
  const [videos, setVideos] = useState<RewardVideo[]>([])
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ kind: 'ok' | 'info'; text: string } | null>(null)

  async function load() {
    try {
      const [s, v] = await Promise.all([reward.state(), reward.videos()])
      setState(s.data)
      setVideos(v.data)
    } catch (e: any) {
      setMsg({ kind: 'info', text: '加载奖励数据失败：' + (e?.message || e) })
    }
  }

  useEffect(() => {
    load()
  }, [])

  const today = todayStr()
  const checkedInToday = state?.last_checkin === today

  async function doCheckin() {
    setBusy(true)
    setMsg(null)
    try {
      const r = await reward.checkin()
      const d = r.data
      if (d.already) {
        setMsg({ kind: 'info', text: '今天已经打过卡啦 🔥' })
      } else {
        setMsg({ kind: 'ok', text: `打卡成功！连续 ${d.streak} 天，已自动判定新徽章` })
      }
      setState(d.state)
    } catch (e: any) {
      setMsg({ kind: 'info', text: '打卡失败：' + (e?.message || e) })
    } finally {
      setBusy(false)
    }
  }

  function videoUrl(v: RewardVideo): string {
    return `/api/reward/video/${v.id}/file`
  }

  async function doGenerate() {
    setBusy(true)
    setMsg(null)
    try {
      const r = await reward.generateVideo()
      const d = r.data
      if (d.ok === false) {
        setMsg({ kind: 'info', text: d.error || '生成失败（视频依赖未安装）' })
      } else {
        setMsg({ kind: 'ok', text: `复盘视频已生成：${d.title || '本期复盘'}` })
      }
      await load()
    } catch (e: any) {
      setMsg({ kind: 'info', text: '生成失败：' + (e?.message || e) })
    } finally {
      setBusy(false)
    }
  }

  const expPct = state ? Math.round((state.exp / state.exp_need) * 100) : 0
  const earnedCount = state?.all_badges.filter((b) => b.earned).length ?? 0

  return (
    <div>
      <h1 style={{ margin: '0 0 4px' }}>🏆 奖励中心</h1>
      <p style={{ color: '#666', marginTop: 0 }}>
        完成任务 / 复习 / 打卡都会累积积分，自动解锁徽章。
      </p>

      {msg && (
        <div
          style={{
            marginBottom: 16,
            padding: '10px 14px',
            borderRadius: 8,
            fontSize: 14,
            background: msg.kind === 'ok' ? '#e8f5e9' : '#fff7e6',
            color: msg.kind === 'ok' ? '#1b5e20' : '#8a6d00',
            border: `1px solid ${msg.kind === 'ok' ? '#a5d6a7' : '#ffe08a'}`,
          }}
        >
          {msg.text}
        </div>
      )}

      <div style={grid2}>
        {/* ① 积分卡 */}
        <div style={card}>
          <div style={{ color: '#888', fontSize: 13 }}>当前等级</div>
          <div style={{ fontSize: 32, fontWeight: 700, color: '#185FA5' }}>Lv.{state?.level ?? 1}</div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, color: '#666', marginTop: 4 }}>
            <span>积分 {state?.points ?? 0}</span>
            <span>经验 {state?.exp ?? 0}/{state?.exp_need ?? 100}</span>
          </div>
          <div style={{ height: 10, background: '#eee', borderRadius: 6, marginTop: 8, overflow: 'hidden' }}>
            <div
              style={{ height: '100%', width: `${expPct}%`, background: '#185FA5', transition: 'width .3s' }}
            />
          </div>
          <div style={{ fontSize: 12, color: '#aaa', marginTop: 8 }}>
            每 {state?.exp_need ?? 100} 积分升 1 级
          </div>
        </div>

        {/* ② 连续打卡 */}
        <div style={card}>
          <div style={{ color: '#888', fontSize: 13 }}>连续打卡</div>
          <div style={{ fontSize: 32, fontWeight: 700 }}>
            🔥 {state?.streak ?? 0} 天
          </div>
          <div style={{ fontSize: 13, color: '#666', marginTop: 4 }}>
            累计打卡 {state?.checkin_total ?? 0} 次
          </div>
          <button
            onClick={doCheckin}
            disabled={busy || checkedInToday}
            style={{
              marginTop: 14,
              width: '100%',
              padding: '10px 0',
              borderRadius: 8,
              border: 'none',
              cursor: checkedInToday ? 'default' : 'pointer',
              background: checkedInToday ? '#e0e0e0' : '#185FA5',
              color: checkedInToday ? '#666' : '#fff',
              fontSize: 14,
              fontWeight: 600,
            }}
          >
            {checkedInToday ? '今日已打卡 ✓' : '今日打卡 +2 分'}
          </button>
        </div>
      </div>

      {/* ③ 徽章墙 */}
      <div style={{ ...card, marginBottom: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14 }}>
          <h3 style={{ margin: 0 }}>徽章墙</h3>
          <span style={{ fontSize: 13, color: '#888' }}>
            已解锁 {earnedCount}/{state?.all_badges.length ?? 0}
          </span>
        </div>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))',
            gap: 12,
          }}
        >
          {(state?.all_badges ?? []).map((b: RewardBadgeDef) => (
            <div
              key={b.badge_key}
              title={b.description}
              style={{
                padding: 14,
                borderRadius: 10,
                border: `1px solid ${b.earned ? '#ffd54f' : '#eee'}`,
                background: b.earned ? '#fffdf2' : '#fafafa',
                textAlign: 'center',
                opacity: b.earned ? 1 : 0.55,
              }}
            >
              <div style={{ fontSize: 30, filter: b.earned ? 'none' : 'grayscale(1)' }}>
                {b.earned ? '🏅' : '🔒'}
              </div>
              <div style={{ fontWeight: 600, marginTop: 6 }}>{b.badge_name}</div>
              <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>{b.description}</div>
              {b.earned && b.earned_at && (
                <div style={{ fontSize: 11, color: '#bba000', marginTop: 4 }}>
                  {b.earned_at.slice(0, 10)} 解锁
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* ④ 复盘视频区 */}
      <div style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>复盘视频</h3>
          <button
            onClick={doGenerate}
            disabled={busy}
            style={{
              padding: '8px 14px',
              borderRadius: 8,
              border: '1px solid #185FA5',
              background: '#fff',
              color: '#185FA5',
              cursor: busy ? 'default' : 'pointer',
              fontSize: 13,
            }}
          >
            {busy ? '生成中…' : '生成复盘视频'}
          </button>
        </div>
        {videos.length === 0 ? (
          <p style={{ color: '#999', fontSize: 14 }}>
            还没有复盘视频。点击右上「生成复盘视频」，会自动用本期学习数据合成一段 MP4（积分 / 完成率 / 徽章墙）。
          </p>
        ) : (
          <div style={{ display: 'grid', gap: 16 }}>
            {videos.map((v) => (
              <div
                key={v.id}
                style={{
                  display: 'flex',
                  gap: 16,
                  alignItems: 'center',
                  padding: '12px 0',
                  borderBottom: '1px solid #f0f0f0',
                }}
              >
                <video
                  controls
                  preload="metadata"
                  src={videoUrl(v)}
                  style={{ width: 200, height: 112, borderRadius: 8, background: '#000', flexShrink: 0 }}
                />
                <div>
                  <div style={{ fontWeight: 600 }}>{v.title || '复盘视频'}</div>
                  <div style={{ fontSize: 13, color: '#999', marginTop: 4 }}>
                    {v.created_at?.slice(0, 10) ?? ''}
                  </div>
                  <a
                    href={videoUrl(v)}
                    download
                    style={{ fontSize: 13, color: '#185FA5', marginTop: 4, display: 'inline-block' }}
                  >
                    下载
                  </a>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
