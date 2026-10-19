import { createContext, useContext, useState, type ReactNode } from 'react'
import type { CSSProperties } from 'react'
import DocEditor, { type DocEditorProps } from './DocEditor'

// 文档编辑器上下文：任何页面（命令面板 / 分析产物）调 openDoc(config) 即可弹出 OnlyOffice 编辑器。
// 为什么做成全局 context 而非各自内嵌：文档生成是“跨页面动作”，命令面板和分析页都要用，
// 放全局避免重复挂载 OnlyOffice 实例（OO 编辑器很重，挂载一次足矣）。
interface DocCtx {
  openDoc: (config: Record<string, any>) => void
  closeDoc: () => void
}
const Ctx = createContext<DocCtx>({ openDoc: () => {}, closeDoc: () => {} })
export const useDoc = () => useContext(Ctx)

export function DocEditorProvider({ children }: { children: ReactNode }) {
  // openDoc 接受宽松入参（命令面板/分析产物传来的 editor_config 是 Record<string, any>），
  // 在边界处收窄为 DocEditor 需要的精确结构，保证 tsc 通过且运行时不变。
  const [config, setConfig] = useState<DocEditorProps['config'] | null>(null)

  return (
    <Ctx.Provider
      value={{
        openDoc: (c: Record<string, any>) => setConfig(c as DocEditorProps['config']),
        closeDoc: () => setConfig(null),
      }}
    >
      {children}
      {config && (
        <div style={overlay}>
          <div style={bar}>
            <span style={{ fontWeight: 600 }}>📝 OnlyOffice 编辑器</span>
            <span style={{ fontSize: 12, color: '#bbb' }}>
              编辑后点左上角「保存」即回存本地，每次保存自动留版本
            </span>
            <button style={closeBtn} onClick={() => setConfig(null)}>关闭</button>
          </div>
          <div style={panel}>
            <DocEditor config={config} />
          </div>
        </div>
      )}
    </Ctx.Provider>
  )
}

const overlay: CSSProperties = {
  position: 'fixed',
  inset: 0,
  background: '#fff',
  zIndex: 2000,
  display: 'flex',
  flexDirection: 'column',
}
const bar: CSSProperties = {
  height: 44,
  flex: '0 0 auto',
  display: 'flex',
  alignItems: 'center',
  gap: 12,
  padding: '0 16px',
  background: '#185FA5',
  color: '#fff',
}
const closeBtn: CSSProperties = {
  marginLeft: 'auto',
  background: 'rgba(255,255,255,0.15)',
  color: '#fff',
  border: 'none',
  borderRadius: 6,
  padding: '6px 14px',
  cursor: 'pointer',
}
const panel: CSSProperties = {
  flex: 1,
  minHeight: 0,
}
