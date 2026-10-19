"""M7 专注计时：开始 / 停止 / 恢复 / 历史。

设计：专注只负责写 focus_session 表（start 记起点、stop 算时长），
周报在聚合时读取它——模块解耦、零额外录入（详见 M4联动设计文档）。
前端做成全局浮条计时器：开始/停止全站共享，刷新页面仍能从后端恢复进行中的会话。
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from . import db


router = APIRouter(prefix="/api/focus", tags=["focus"])


class StartIn(BaseModel):
    task_id: Optional[int] = None
    note: Optional[str] = None


class StopIn(BaseModel):
    session_id: int


@router.post("/start", response_model=dict)
def start(payload: StartIn):
    """开始一次专注，返回 session id。task_id 可空（纯记录工时也行）。"""
    sid = db.start_focus_session(payload.task_id)
    return {"id": sid, "ok": True}


@router.post("/stop", response_model=dict)
def stop(payload: StopIn):
    """停止专注，补 ended_at + duration(秒)，返回本次时长。已停止不重算。"""
    return db.stop_focus_session(payload.session_id)


@router.get("/active", response_model=dict)
def active():
    """当前进行中的专注（未停止）。前端刷新页面后用它恢复计时器。"""
    f = db.get_active_focus()
    return {"session": f}


@router.get("/history", response_model=list)
def history(limit: int = 50):
    """最近专注记录（含任务标题），用于历史/回顾。"""
    return db.list_focus_sessions(limit)
