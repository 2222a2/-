import { useState } from 'react'
import type { CSSProperties } from 'react'
import {
  analysisApi,
  docsApi,
  AnalysisQuestion,
  AnalysisStep,
  AnalysisRequirement,
  QaEntry,
} from '../api/client'
import { useDoc } from './DocEditorProvider'

// 四阶段进度
const STAGES = ['input', 'clarify', 'confirm', 'decompose'] as const
const STAGE_LABEL: Record<string, string> = {
  input: '① 描述任务',
  clarify: '② 澄清反问',
  confirm: '③ 需求确认卡',
  decompose: '④ 拆解步骤',
}

const card: CSSProperties = {
  background: '#fff', border: '1px solid #e6e6e0', borderRadius: 12,
  padding: 20, marginBottom: 16, boxShadow: '0 1px 3px rgba(0,0,0,.04)',
}
const btn: CSSProperties = {
  background: '#185FA5', color: '#fff', border: 'none', borderRadius: 8,
  padding: '9px 16px', fontSize: 14, cursor: 'pointer', marginRight: 8,
}
const btnGhost: CSSProperties = {
  background: '#f2f2ee', color: '#333', border: '1px solid #ddd', borderRadius: 8,
  padding: '9px 16px', fontSize: 14, cursor: 'pointer', marginRight: 8,
}
const inputStyle: CSSProperties = {
  width: '100%', padding: '8px 10px', border: '1px solid #ccc', borderRadius: 6,
  fontSize: 14, boxSizing: 'border-box',
}

export default function AnalysisPage() {
  const [stage, setStage] = useState<'input' | 'clarify' | 'confirm' | 'decompose' | 'done'>('input')
  const { openDoc } = useDoc()
  const [text, setText] = useState('')
  const [questions, setQuestions] = useState<AnalysisQuestion[]>([])
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [requirement, setRequirement] = useState<AnalysisRequirement | null>(null)
  const [steps, setSteps] = useState<AnalysisStep[]>([])
  const [plan, setPlan] = useState<{ plan_id: number; task_id: number; child_ids: number[]; mock: boolean } | null>(null)
  const [qaLog, setQaLog] = useState<QaEntry[]>([])
  const [mock, setMock] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  // 逐步追问子流程
  const [qaStepIdx, setQaStepIdx] = useState(-1)
  const [qaResult, setQaResult] = useState<{ risks: string; blockers: string; prerequisites: string } | null>(null)
  const [qaAnswers, setQaAnswers] = useState<{ risks: string; blockers: string; prerequisites: string }>({
    risks: '', blockers: '', prerequisites: '',
  })

  const stageIndex = stage === 'done' ? 4 : STAGES.indexOf(stage as typeof STAGES[number])

  function reset() {
    setStage('input'); setText(''); setQuestions([]); setAnswers({})
    setRequirement(null); setSteps([]); setPlan(null); setQaLog([]); setMock(false)
    setQaStepIdx(-1); setQaResult(null); setErr('')
  }

  async function doClarify() {
    if (!text.trim()) return
    setBusy(true); setErr('')
    try {
      const r = await analysisApi.clarify(text)
      setQuestions(r.data.questions); setAnswers({}); setMock(r.data.mock); setStage('clarify')
    } catch (e: any) { setErr(e?.message || '澄清失败') } finally { setBusy(false) }
  }
  async function doConfirm() {
    if (!questions.length) return
    setBusy(true); setErr('')
    const ans = questions.map((q) => ({ field: q.field, answer: answers[q.field] || '' }))
    try {
      const r = await analysisApi.confirm(text, ans)
      setRequirement(r.data.requirement); setMock(r.data.mock); setStage('confirm')
    } catch (e: any) { setErr(e?.message || '确认失败') } finally { setBusy(false) }
  }
  async function doDecompose() {
    if (!requirement) return
    setBusy(true); setErr('')
    try {
      const r = await analysisApi.decompose(requirement)
      setSteps(r.data.steps.length ? r.data.steps : []);
      setMock(r.data.mock); setStage('decompose')
    } catch (e: any) { setErr(e?.message || '拆解失败') } finally { setBusy(false) }
  }
  async function doSave() {
    if (!requirement) return
    setBusy(true); setErr('')
    try {
      const r = await analysisApi.save(text.trim(), requirement, steps)
      setPlan(r.data); setMock(r.data.mock); setQaLog([]); setStage('done')
    } catch (e: any) { setErr(e?.message || '保存失败') } finally { setBusy(false) }
  }
  async function doQa() {
    if (!plan || qaStepIdx < 0) return
    setBusy(true); setErr('')
    try {
      const r = await analysisApi.qa(plan.plan_id, steps[qaStepIdx])
      setQaResult(r.data); setQaAnswers({ risks: '', blockers: '', prerequisites: '' })
    } catch (e: any) { setErr(e?.message || '追问失败') } finally { setBusy(false) }
  }
  async function doQaAnswer() {
    if (!plan || !qaResult || qaStepIdx < 0) return
    setBusy(true); setErr('')
    try {
      const r = await analysisApi.qaAnswer(plan.plan_id, {
        step_order: steps[qaStepIdx].order,
        step_desc: steps[qaStepIdx].desc,
        questions: qaResult,
        answers: qaAnswers,
      })
      setQaLog(r.data.qa_log); setQaResult(null); setQaStepIdx(-1)
    } catch (e: any) { setErr(e?.message || '沉淀失败') } finally { setBusy(false) }
  }
  async function doGenerateDoc() {
    if (!requirement) return
    setBusy(true); setErr('')
    try {
      // 把分析产物的“需求卡 + 拆解步骤”直接喂给文档生成器，产出可编辑的 Word 初稿
      const r = await docsApi.generate({
        prompt: requirement.goal || '任务分析报告',
        doc_type: 'word',
        linked_task_id: plan?.task_id ?? null,
        source: 'analysis',
        requirement: requirement as unknown as Record<string, any>,
        steps: steps as unknown as any[],
      })
      openDoc(r.data.editor_config)
    } catch (e: any) { setErr(e?.response?.data?.detail || e?.message || '生成文档失败') } finally { setBusy(false) }
  }

  function updateStep(i: number, patch: Partial<AnalysisStep>) {
    setSteps((ss) => ss.map((s, idx) => (idx === i ? { ...s, ...patch } : s)))
  }
  function addStep() {
    setSteps((ss) => [...ss, { order: ss.length + 1, desc: '', est_hours: 1, deps: [], need: [], output: '' }])
  }
  function removeStep(i: number) {
    setSteps((ss) => ss.filter((_, idx) => idx !== i).map((s, idx) => ({ ...s, order: idx + 1 })))
  }
  function updateReq(patch: Partial<AnalysisRequirement>) {
    setRequirement((r) => (r ? { ...r, ...patch } : r))
  }

  return (
    <div style={{ maxWidth: 880, margin: '0 auto', padding: '8px 4px' }}>
      <h2 style={{ margin: '4px 0 2px' }}>🧩 任务分析引擎</h2>
      <p style={{ color: '#888', marginTop: 0, fontSize: 13 }}>
        把模糊任务变成可勾选、可排期的任务树。AI 给初稿，你定稿（human-in-the-loop）。
      </p>

      {/* 进度条 */}
      <div style={{ display: 'flex', gap: 8, margin: '12px 0 18px' }}>
        {STAGES.map((s, i) => (
          <div key={s} style={{
            flex: 1, textAlign: 'center', padding: '7px 4px', borderRadius: 8, fontSize: 13,
            background: i <= stageIndex ? '#185FA5' : '#f2f2ee',
            color: i <= stageIndex ? '#fff' : '#999',
          }}>{STAGE_LABEL[s]}</div>
        ))}
        <div style={{
          flex: 1, textAlign: 'center', padding: '7px 4px', borderRadius: 8, fontSize: 13,
          background: stage === 'done' ? '#2e8b57' : '#f2f2ee',
          color: stage === 'done' ? '#fff' : '#999',
        }}>⑤ 生成 & 追问</div>
      </div>

      {mock && (
        <div style={{ background: '#fff7e6', border: '1px solid #ffe08a', color: '#9a6b00',
          padding: '8px 12px', borderRadius: 8, fontSize: 13, marginBottom: 14 }}>
          当前为离线模拟（未配置 ARK_API_KEY），返回的是示例数据。配置密钥后即走真实 AI 拆解。
        </div>
      )}
      {err && <div style={{ color: '#E24B4A', marginBottom: 12, fontSize: 13 }}>⚠️ {err}</div>}

      {/* ① 输入 */}
      {stage === 'input' && (
        <div style={card}>
          <label style={{ fontWeight: 600, fontSize: 14 }}>描述一个模糊/复杂的任务</label>
          <textarea
            style={{ ...inputStyle, height: 90, marginTop: 10, resize: 'vertical' }}
            placeholder="例如：给周五的客户会议准备一份周报"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <div style={{ marginTop: 12 }}>
            <button style={btn} disabled={busy || !text.trim()} onClick={doClarify}>
              {busy ? '分析中…' : '开始分析 →'}
            </button>
          </div>
        </div>
      )}

      {/* ② 澄清反问 */}
      {stage === 'clarify' && (
        <div style={card}>
          <label style={{ fontWeight: 600, fontSize: 14 }}>AI 想先搞清楚这几件事（填空即可）</label>
          <div style={{ marginTop: 12 }}>
            {questions.map((q) => (
              <div key={q.field} style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 13, color: '#444', marginBottom: 4 }}>{q.question}</div>
                <input
                  style={inputStyle}
                  value={answers[q.field] || ''}
                  onChange={(e) => setAnswers((a) => ({ ...a, [q.field]: e.target.value }))}
                  placeholder="你的回答…"
                />
              </div>
            ))}
            {questions.length === 0 && <div style={{ color: '#888', fontSize: 13 }}>（无需澄清，直接下一步）</div>}
          </div>
          <div style={{ marginTop: 8 }}>
            <button style={btn} disabled={busy} onClick={doConfirm}>生成需求确认卡 →</button>
            <button style={btnGhost} onClick={() => setStage('input')}>返回</button>
          </div>
        </div>
      )}

      {/* ③ 需求确认卡（可编辑） */}
      {stage === 'confirm' && requirement && (
        <div style={card}>
          <label style={{ fontWeight: 600, fontSize: 14 }}>需求确认卡 · 可编辑后定稿</label>
          <div style={{ marginTop: 12, display: 'grid', gap: 12 }}>
            <Field label="目标 goal" value={requirement.goal} onChange={(v) => updateReq({ goal: v })} />
            <Field label="交付物 deliverable" value={requirement.deliverable} onChange={(v) => updateReq({ deliverable: v })} />
            <Field label="截止 deadline" value={requirement.deadline} onChange={(v) => updateReq({ deadline: v })} />
            <Field label="约束 constraints" value={requirement.constraints} onChange={(v) => updateReq({ constraints: v })} />
            <Field label="成功标准 success_criteria" value={requirement.success_criteria} onChange={(v) => updateReq({ success_criteria: v })} />
            <div>
              <div style={{ fontSize: 13, color: '#444', marginBottom: 4 }}>关键假设 assumptions（每行一条）</div>
              <textarea style={{ ...inputStyle, height: 70, resize: 'vertical' }}
                value={(requirement.assumptions || []).join('\n')}
                onChange={(e) => updateReq({ assumptions: e.target.value.split('\n').filter(Boolean) })} />
            </div>
          </div>
          <div style={{ marginTop: 14 }}>
            <button style={btn} disabled={busy} onClick={doDecompose}>确认并拆解 →</button>
            <button style={btnGhost} onClick={() => setStage('clarify')}>返回</button>
          </div>
        </div>
      )}

      {/* ④ 拆解步骤（可编辑） */}
      {stage === 'decompose' && (
        <div style={card}>
          <label style={{ fontWeight: 600, fontSize: 14 }}>拆解步骤 · 可增删改、调工期</label>
          <div style={{ marginTop: 12, fontSize: 12, color: '#888', display: 'grid',
            gridTemplateColumns: '40px 1fr 70px 90px 1fr', gap: 8, marginBottom: 6 }}>
            <span>#</span><span>动作</span><span>工时(h)</span><span>依赖</span><span>需要/产出</span>
          </div>
          {steps.map((s, i) => (
            <div key={i} style={{ display: 'grid', gridTemplateColumns: '40px 1fr 70px 90px 1fr', gap: 8,
              alignItems: 'center', marginBottom: 8 }}>
              <span style={{ color: '#185FA5', fontWeight: 600 }}>{s.order}</span>
              <input style={inputStyle} value={s.desc}
                onChange={(e) => updateStep(i, { desc: e.target.value })} />
              <input style={{ ...inputStyle, width: 60 }} type="number" min={0.5} step={0.5} value={s.est_hours}
                onChange={(e) => updateStep(i, { est_hours: Number(e.target.value) || 0 })} />
              <input style={inputStyle} value={(s.deps || []).join(',')}
                onChange={(e) => updateStep(i, { deps: e.target.value.split(',').map((x) => Number(x.trim())).filter(Boolean) })}
                placeholder="1,2" />
              <input style={inputStyle}
                value={`${(s.need || []).join(',')}${s.output ? ' → ' + s.output : ''}`}
                onChange={(e) => {
                  const raw = e.target.value
                  const [needRaw, outRaw] = raw.split('→')
                  updateStep(i, {
                    need: (needRaw || '').split(',').map((x) => x.trim()).filter(Boolean),
                    output: (outRaw || '').trim(),
                  })
                }}
                placeholder="工具,资料 → 产出" />
              <button style={{ ...btnGhost, padding: '4px 8px', margin: 0 }} onClick={() => removeStep(i)}>✕</button>
            </div>
          ))}
          <div style={{ marginTop: 8 }}>
            <button style={btnGhost} onClick={addStep}>＋ 加步骤</button>
          </div>
          <div style={{ marginTop: 16 }}>
            <button style={btn} disabled={busy} onClick={doSave}>生成任务清单并保存 →</button>
            <button style={btnGhost} onClick={() => setStage('confirm')}>返回</button>
          </div>
        </div>
      )}

      {/* ⑤ 生成结果 + 逐步追问 */}
      {stage === 'done' && plan && (
        <>
          <div style={{ ...card, borderColor: '#2e8b57' }}>
            <div style={{ fontWeight: 600, fontSize: 15, color: '#2e8b57' }}>✅ 已生成任务清单</div>
            <p style={{ fontSize: 13, color: '#555', marginTop: 8 }}>
              主任务 #{plan.task_id} 下挂 <b>{plan.child_ids.length}</b> 个子步骤，已写入「📋 任务」四象限看板。
            </p>
            <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {steps.map((s) => (
                <span key={s.order} style={{ background: '#eef4fb', color: '#185FA5',
                  borderRadius: 6, padding: '4px 8px', fontSize: 12 }}>
                  {s.order}. {s.desc}
                </span>
              ))}
            </div>
            <div style={{ marginTop: 14 }}>
              <button style={btn} disabled={busy} onClick={doGenerateDoc}>📄 生成 Word 文档初稿</button>
              <button style={btnGhost} onClick={reset}>再分析一个</button>
              <span style={{ fontSize: 12, color: '#888', marginLeft: 4 }}>
                生成后自动打开 OnlyOffice，可编辑并回存
              </span>
            </div>
          </div>

          {/* 逐步追问 */}
          <div style={card}>
            <label style={{ fontWeight: 600, fontSize: 14 }}>逐步追问 · 沉淀「问题预案」</label>
            <p style={{ fontSize: 12, color: '#888', marginTop: 4 }}>
              选一步 → AI 从风险/卡点/前置三问提醒 → 你回答 → 沉淀为预案，执行时不踩坑。
            </p>
            <div style={{ marginTop: 10, display: 'flex', gap: 8, alignItems: 'center' }}>
              <select style={inputStyle} value={qaStepIdx} onChange={(e) => { setQaStepIdx(Number(e.target.value)); setQaResult(null) }}>
                <option value={-1}>选择步骤…</option>
                {steps.map((s, i) => (
                  <option key={s.order} value={i}>{s.order}. {s.desc}</option>
                ))}
              </select>
              <button style={btn} disabled={busy || qaStepIdx < 0} onClick={doQa}>生成三问</button>
            </div>

            {qaResult && (
              <div style={{ marginTop: 14, background: '#fafafa', border: '1px solid #eee', borderRadius: 8, padding: 14 }}>
                {([
                  ['risks', '⚠️ 风险', qaResult.risks],
                  ['blockers', '🚧 卡点', qaResult.blockers],
                  ['prerequisites', '🔑 前置', qaResult.prerequisites],
                ] as const).map(([k, label, val]) => (
                  <div key={k} style={{ marginBottom: 10 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: '#444', marginBottom: 4 }}>{label}</div>
                    <div style={{ fontSize: 13, color: '#666', marginBottom: 4 }}>{val}</div>
                    <textarea style={{ ...inputStyle, height: 48, resize: 'vertical' }}
                      placeholder="你的应对/回答…"
                      value={qaAnswers[k]} onChange={(e) => setQaAnswers((a) => ({ ...a, [k]: e.target.value }))} />
                  </div>
                ))}
                <button style={btn} disabled={busy} onClick={doQaAnswer}>沉淀预案</button>
              </div>
            )}

            {qaLog.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8 }}>已沉淀预案（{qaLog.length}）</div>
                {qaLog.map((q, i) => (
                  <div key={i} style={{ background: '#eef4fb', borderRadius: 8, padding: 10, marginBottom: 8, fontSize: 12 }}>
                    <b>步骤 {q.step_order}：{q.step_desc}</b>
                    <div style={{ marginTop: 4, color: '#555' }}>
                      风险应对：{q.answers.risks || '—'}；卡点应对：{q.answers.blockers || '—'}；前置：{q.answers.prerequisites || '—'}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <div style={{ fontSize: 13, color: '#444', marginBottom: 4 }}>{label}</div>
      <input style={inputStyle} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  )
}
