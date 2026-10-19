import { useEffect, useState } from 'react'
import { api, Health } from './api/client'
import CommandPalette from './components/CommandPalette'
import KnowledgePage from './components/KnowledgePage'
import StudyTasksPage from './components/StudyTasksPage'
import TaskPage from './components/TaskPage'
import AnalysisPage from './components/AnalysisPage'
import { DocEditorProvider } from './components/DocEditorProvider'
import { FocusProvider } from './components/FocusProvider'
import { FocusTimer } from './components/FocusTimer'

type Page = 'home' | 'knowledge' | 'study' | 'tasks' | 'analysis'

// 深链：微信点 /study-tasks 直接进备考任务页（无需手动点导航）
function initialPage(): Page {
  if (typeof window !== 'undefined' && window.location.pathname.includes('study-tasks')) {
    return 'study'
  }
  return 'home'
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [page, setPage] = useState<Page>(initialPage())

  useEffect(() => {
    api.get<Health>('/health').then((r) => setHealth(r.data)).catch(() => {})
  }, [])

  return (
    <DocEditorProvider>
    <FocusProvider>
    <div style={{ display: 'flex', minHeight: '100vh', fontFamily: 'system-ui' }}>
      {/* 左侧导航：全站模块入口 */}
      <aside style={sidebar}>
        <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 16 }}>🐟 工作学习台</div>
        <NavItem active={page === 'home'} onClick={() => setPage('home')}>🏠 首页</NavItem>
        <NavItem active={page === 'knowledge'} onClick={() => setPage('knowledge')}>📚 资料库</NavItem>
        <NavItem active={page === 'study'} onClick={() => setPage('study')}>📖 备考任务</NavItem>
        <NavItem active={page === 'analysis'} onClick={() => setPage('analysis')}>🧩 分析</NavItem>
        <NavItem active={page === 'tasks'} onClick={() => setPage('tasks')}>📋 任务</NavItem>
        <div style={{ marginTop: 'auto', fontSize: 12, color: '#999' }}>
          {health ? `后端 ${health.version} 已连通` : '后端未连通'}
          <br />⌘/Ctrl + K 命令面板
        </div>
      </aside>

      <main style={{ flex: 1, padding: 24, background: '#fff' }}>
        {page === 'home' && (
          <div>
            <h1>工作学习一体化平台</h1>
            <p style={{ color: '#666' }}>
              Phase 0 脚手架 + M2 AI 层 + M0 资料底座 + M3 任务管理已落地（本地优先）。
            </p>
            {health && (
              <pre style={{ background: '#f5f5f5', padding: 12, borderRadius: 8 }}>
                {JSON.stringify(health, null, 2)}
              </pre>
            )}
            <p style={{ color: '#888' }}>
              试试：按 <b>⌘/Ctrl + K</b> 打开命令面板，说“记笔记：明天答辩要点”或“搜一下 OKR”。
            </p>
          </div>
        )}
        {page === 'knowledge' && <KnowledgePage />}
        {page === 'study' && <StudyTasksPage />}
        {page === 'analysis' && <AnalysisPage />}
        {page === 'tasks' && <TaskPage />}
      </main>

      {/* 全局命令面板（任意页面可唤起） */}
      <CommandPalette />
      {/* 全局专注计时浮条（专注中常驻右下角） */}
      <FocusTimer />
    </div>
    </FocusProvider>
    </DocEditorProvider>
  )
}

function NavItem({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'block',
        width: '100%',
        textAlign: 'left',
        padding: '10px 12px',
        marginBottom: 6,
        borderRadius: 8,
        border: 'none',
        cursor: 'pointer',
        background: active ? '#185FA5' : 'transparent',
        color: active ? '#fff' : '#333',
        fontSize: 14,
      }}
    >
      {children}
    </button>
  )
}

const sidebar: React.CSSProperties = {
  width: 200,
  background: '#f7f8fa',
  borderRight: '1px solid #eee',
  padding: 16,
  display: 'flex',
  flexDirection: 'column',
}
