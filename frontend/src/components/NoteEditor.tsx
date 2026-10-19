import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { useEffect } from 'react'

interface Props {
  value: string
  onChange: (html: string) => void
}

// 笔记富文本编辑器：基于 TipTap（StarterKit 提供 H1/H2/加粗/斜体/列表等）。
// 输出的 HTML 由后端 nh3 净化后存 rich_body；content 抽纯文本进 FTS。
export default function NoteEditor({ value, onChange }: Props) {
  const editor = useEditor({
    extensions: [StarterKit],
    content: value || '',
    editorProps: {
      attributes: {
        class: 'note-editor-prose',
      },
    },
    onUpdate: ({ editor }) => onChange(editor.getHTML()),
  })

  // 受控同步：外部清空/切换卡片时，把最新 value 灌回编辑器
  useEffect(() => {
    if (editor && value !== editor.getHTML()) {
      editor.commands.setContent(value || '', false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, editor])

  if (!editor) return null
  return (
    <div>
      <div style={toolbar}>
        <ToolbarBtn label="H1" active={editor.isActive('heading', { level: 1 })} onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()} />
        <ToolbarBtn label="H2" active={editor.isActive('heading', { level: 2 })} onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()} />
        <div style={Sep} />
        <ToolbarBtn label="B" active={editor.isActive('bold')} onClick={() => editor.chain().focus().toggleBold().run()} bold />
        <ToolbarBtn label="I" active={editor.isActive('italic')} onClick={() => editor.chain().focus().toggleItalic().run()} italic />
        <div style={Sep} />
        <ToolbarBtn label="• 列表" active={editor.isActive('bulletList')} onClick={() => editor.chain().focus().toggleBulletList().run()} />
        <ToolbarBtn label="1. 列表" active={editor.isActive('orderedList')} onClick={() => editor.chain().focus().toggleOrderedList().run()} />
      </div>
      <EditorContent editor={editor} />
      <style>{`
        .note-editor-prose {
          min-height: 140px;
          border: 1px solid #ddd;
          border-radius: 8px;
          padding: 10px 12px;
          background: #fff;
          outline: none;
          font-size: 14px;
          line-height: 1.6;
        }
        .note-editor-prose:focus { border-color: #185FA5; }
        .note-editor-prose h1 { font-size: 20px; margin: 6px 0; }
        .note-editor-prose h2 { font-size: 17px; margin: 6px 0; }
        .note-editor-prose p { margin: 4px 0; }
        .note-editor-prose ul, .note-editor-prose ol { padding-left: 20px; }
      `}</style>
    </div>
  )
}

function ToolbarBtn({ label, active, onClick, bold, italic }: {
  label: string
  active: boolean
  onClick: () => void
  bold?: boolean
  italic?: boolean
}) {
  return (
    <button
      type="button"
      onMouseDown={(e) => e.preventDefault()}
      onClick={onClick}
      style={{
        padding: '4px 8px',
        border: '1px solid #ddd',
        borderRadius: 6,
        background: active ? '#185FA5' : '#fff',
        color: active ? '#fff' : '#333',
        cursor: 'pointer',
        fontWeight: bold ? 700 : 400,
        fontStyle: italic ? 'italic' : 'normal',
        fontSize: 13,
      }}
    >
      {label}
    </button>
  )
}

const toolbar: React.CSSProperties = {
  display: 'flex',
  gap: 6,
  alignItems: 'center',
  flexWrap: 'wrap',
  marginBottom: 8,
}
const Sep: React.CSSProperties = { width: 1, height: 20, background: '#e0e0e0', margin: '0 2px' }
