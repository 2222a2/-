import { lazy, Suspense } from 'react'

// 懒加载 OnlyOffice React 组件：首屏不加载它，且即使未安装该 npm 包也不会让整个 App 崩溃。
// 该包 d.ts 把 default 导出成模块命名空间，故用一次类型兜底取真实组件。
const DocumentEditor = lazy(async () => {
  const mod = await import('@onlyoffice/document-editor-react')
  const Comp = ((mod as Record<string, unknown>).default ?? mod) as React.ComponentType<Record<string, unknown>>
  return { default: Comp }
})

export interface DocEditorProps {
  config: {
    onlyofficeUrl: string
    document: { fileType: string; title: string; url: string }
    documentType: string
    editorConfig: Record<string, unknown>
  }
}

// 该组件由 Phase 1 M1 调用：传入后端 build_editor_config 算出的 config 即可嵌入编辑器
export default function DocEditor({ config }: DocEditorProps) {
  return (
    <Suspense fallback={<div>正在加载编辑器…</div>}>
      <DocumentEditor
        id="onlyoffice-editor"
        documentServerUrl={config.onlyofficeUrl}
        config={config as unknown as object}
        onLoadComponentError={(e: unknown) =>
          console.error('OnlyOffice 加载失败', e)
        }
      />
    </Suspense>
  )
}
