"""M4 任务分析引擎：四阶段状态机（CLARIFY→CONFIRM→DECOMPOSE→PLAN）。

设计原理（确定流程包着生成式填空）：
- 阶段切换、落库动作 = 应用代码（确定性）；
- 理解模糊需求、把非结构化→结构化 = 模型（生成式）；
- 每个阶段只让模型产出一种固定 JSON 槽位，应用解析后交给下一阶段或落库。
这样 AI 的灵活性被“四道闸”框住：角色协议锁死、阶段门控、结构化输出、数量范围限制。

无状态设计：后端不维护会话，前端驱动流转；仅 /save 和 /qa-answer 需要写入 plan_analysis 行。
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException

from . import db, schemas
from .ai.provider import get_provider, MockProvider


router = APIRouter(prefix="/api/analysis", tags=["analysis"])


# --------------------------- 阶段 prompt（四道闸） ---------------------------
SYSTEM_CLARIFY = (
    "你是任务拆解专家。收到用户的模糊任务后，只做一件事：找出还缺的关键信息，提出 2-4 个反问。"
    "必须覆盖的维度：goal(目标) / deliverable(交付物) / deadline(截止) / constraint(约束) / criteria(成功标准)。"
    "规则：1) 只问用户没说的；2) 最多4个，按重要性排序；3) 不替用户决定、不列步骤、不写方案；"
    "4) 只输出一个 JSON：{\"questions\":[{\"field\":\"goal|deliverable|deadline|constraint|criteria\",\"question\":\"...\"}]}。"
)

SYSTEM_CONFIRM = (
    "基于用户任务描述与对反问的回答，产出“需求确认卡”，只输出一个 JSON："
    "{\"goal\":\"一句话目标\",\"deliverable\":\"具体交付物/范围\",\"deadline\":\"截止时间(ISO)或 无\","
    "\"constraints\":\"限制条件\",\"success_criteria\":\"怎样算完成\","
    "\"assumptions\":[\"模型做的假设，待用户确认\"]}。不要任何解释，只输出 JSON。"
)

SYSTEM_DECOMPOSE = (
    "基于已确认的需求，把任务拆成有序、可执行步骤。每条步骤输出 JSON："
    "{\"order\":1,\"desc\":\"动作描述\",\"est_hours\":2,\"deps\":[步骤序号],\"need\":[\"资料/工具\"],\"output\":\"该步产出\"}。"
    "规则：1) 单步 0.5-4 小时；2) 有依赖必须写 deps；3) 只输出 steps 数组，不要解释。"
)

SYSTEM_QA = (
    "你是风险评估专家。针对用户选中的某一步骤，从三个角度给出提醒（每项 1-2 句）："
    "risks(这步有什么风险) / blockers(可能卡在哪) / prerequisites(需要什么前置条件)。"
    "只输出一个 JSON：{\"risks\":\"...\",\"blockers\":\"...\",\"prerequisites\":\"...\"}。不要解释。"
)


# ----------------------------- 工具函数 -----------------------------
def _extract_json(text):
    """从模型输出中容错提取第一个 JSON 对象（兼容 ```json 围栏或夹杂文字）。"""
    if not text:
        return None
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)  # 去 markdown 围栏
    if m:
        text = m.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _is_mock() -> bool:
    return isinstance(get_provider(), MockProvider)


# ----------------------------- Mock 示例（无 key 也能跑通） -----------------------------
SAMPLE_QUESTIONS = [
    {"field": "goal", "question": "这份周报的核心目标是什么？希望客户看完后做什么决定？"},
    {"field": "deliverable", "question": "最终要交付成什么形式？一页纸 Word、PDF、还是在线文档？"},
    {"field": "deadline", "question": "最晚什么时候要？中间有没有预留修改时间？"},
    {"field": "audience", "question": "主要是给谁看的？客户方还是内部管理层？（影响措辞）"},
]

SAMPLE_REQUIREMENT = {
    "goal": "给周五客户会议准备一页纸周报",
    "deliverable": "1 页 Word 周报（本周进展 + 风险 + 下周计划）",
    "deadline": "2026-10-16 17:00",
    "constraints": "只用内部数据，不出现未公开数字",
    "success_criteria": "客户能一眼看懂本周状态与风险",
    "assumptions": ["数据来源是本周已标记 done 的任务"],
}

SAMPLE_STEPS = [
    {"order": 1, "desc": "收集本周已完成任务清单", "est_hours": 1, "deps": [], "need": ["任务系统"], "output": "任务清单"},
    {"order": 2, "desc": "整理风险与阻塞项", "est_hours": 1, "deps": [1], "need": ["周报模板"], "output": "风险清单"},
    {"order": 3, "desc": "撰写一页纸周报并导出 Word", "est_hours": 2, "deps": [1, 2], "need": ["python-docx"], "output": "weekly_report.docx"},
]


# ----------------------------- 阶段接口 -----------------------------
@router.post("/clarify", response_model=dict)
def clarify(payload: schemas.ClarifyIn):
    """阶段A：模糊任务 → 模型反问 2-4 个关键问题。"""
    if _is_mock():
        return {"questions": SAMPLE_QUESTIONS, "mock": True}
    msg = get_provider().chat([
        {"role": "system", "content": SYSTEM_CLARIFY},
        {"role": "user", "content": f"任务描述：{payload.text}"},
    ])
    data = _extract_json(msg.content) or {}
    return {"questions": data.get("questions", []), "mock": False}


@router.post("/confirm", response_model=dict)
def confirm(payload: schemas.ConfirmIn):
    """阶段B：任务描述 + 用户回答 → 需求确认卡（结构化 JSON）。"""
    if _is_mock():
        return {"requirement": SAMPLE_REQUIREMENT, "mock": True}
    answers_text = "\n".join(f"- {a.get('field', '')}: {a.get('answer', '')}" for a in payload.answers)
    msg = get_provider().chat([
        {"role": "system", "content": SYSTEM_CONFIRM},
        {"role": "user", "content": f"原始任务：{payload.text}\n\n用户对反问的回答：\n{answers_text}"},
    ])
    return {"requirement": _extract_json(msg.content) or {}, "mock": False}


@router.post("/decompose", response_model=dict)
def decompose(payload: schemas.DecomposeIn):
    """阶段C：确认卡 → 有序可执行步骤数组。"""
    if _is_mock():
        return {"steps": SAMPLE_STEPS, "mock": True}
    msg = get_provider().chat([
        {"role": "system", "content": SYSTEM_DECOMPOSE},
        {"role": "user", "content": f"已确认需求（JSON）：{json.dumps(payload.requirement, ensure_ascii=False)}"},
    ])
    data = _extract_json(msg.content) or {}
    steps = data.get("steps", []) if isinstance(data, dict) else []
    return {"steps": steps, "mock": False}


@router.post("/save", response_model=dict)
def save(payload: schemas.SaveIn):
    """阶段D-1：确认卡 + 步骤 → 建主任务 + 子任务 + 写 plan_analysis 行。"""
    requirement = payload.requirement or {}
    main_desc = requirement.get("goal") or requirement.get("deliverable") or ""
    deadline = requirement.get("deadline")
    if deadline in (None, "无", ""):
        deadline = None
    task_id = db.insert_task(
        title=(payload.title.strip() or main_desc or "未命名分析任务"),
        description=main_desc,
        deadline=deadline,
    )
    # 子任务：每条步骤一个，挂在主任务下
    child_ids = []
    for s in payload.steps:
        desc = s.get("desc") or "未命名步骤"
        extra = []
        if s.get("output"):
            extra.append(f"产出：{s['output']}")
        if s.get("need"):
            extra.append(f"需要：{', '.join(s['need'])}")
        cid = db.insert_task(
            title=desc,
            description="；".join(extra) if extra else None,
            parent_id=task_id,
        )
        child_ids.append(cid)
    plan_id = db.save_plan_analysis(task_id, requirement, payload.steps)
    return {"plan_id": plan_id, "task_id": task_id, "child_ids": child_ids, "mock": _is_mock()}


@router.post("/{plan_id}/qa", response_model=dict)
def step_qa(plan_id: int, payload: schemas.QaIn):
    """阶段D-2：选中某步 → 模型三问（风险/卡点/前置）。"""
    if not db.get_plan_analysis(plan_id):
        raise HTTPException(status_code=404, detail="plan not found")
    step = payload.step or {}
    if _is_mock():
        return {
            "risks": f"「{step.get('desc', '这步')}」可能因依赖前置未完而延期。",
            "blockers": "若所需资料/工具（如 python-docx）未就绪会卡住。",
            "prerequisites": "确认上游步骤已完成、所需工具已安装。",
            "mock": True,
        }
    msg = get_provider().chat([
        {"role": "system", "content": SYSTEM_QA},
        {"role": "user", "content": f"选中步骤（JSON）：{json.dumps(step, ensure_ascii=False)}"},
    ])
    qa = _extract_json(msg.content) or {}
    return {
        "risks": qa.get("risks", ""),
        "blockers": qa.get("blockers", ""),
        "prerequisites": qa.get("prerequisites", ""),
        "mock": False,
    }


@router.post("/{plan_id}/qa-answer", response_model=schemas.QaAnswerOut)
def step_qa_answer(plan_id: int, payload: schemas.QaAnswerIn):
    """阶段D-3：用户回答三问 → 沉淀进 qa_log_json 作为“问题预案”。"""
    entry = {
        "step_order": payload.step_order,
        "step_desc": payload.step_desc,
        "questions": payload.questions,
        "answers": payload.answers,
    }
    ok = db.append_plan_qa(plan_id, entry)
    if not ok:
        raise HTTPException(status_code=404, detail="plan not found")
    p = db.get_plan_analysis(plan_id)
    return schemas.QaAnswerOut(ok=True, qa_log=p.get("qa_log") or [])
