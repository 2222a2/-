"""用户偏好设置接口：番茄钟工作/休息时长（落 app_settings 表，跨会话复用）。

为什么单独一个路由：偏好是“跨功能的小配置”，不止专注用；后续若加其它偏好
（如默认报告周期）也走这里，前端一个入口读取/写入，避免散落到各模块。
"""
from fastapi import APIRouter
from pydantic import BaseModel

from . import db, config


router = APIRouter(prefix="/api/settings", tags=["settings"])


class FocusPrefIn(BaseModel):
    work_minutes: int | None = None    # 专注（工作）时长，分钟
    break_minutes: int | None = None  # 休息时长，分钟


@router.get("/focus")
def get_focus_prefs():
    """读取番茄钟时长：库里有则用库里的，否则回退 config 默认值。"""
    return {
        "work_minutes": int(db.get_setting("focus_work_minutes", config.FOCUS_WORK_MINUTES)),
        "break_minutes": int(db.get_setting("focus_break_minutes", config.FOCUS_BREAK_MINUTES)),
    }


@router.put("/focus")
def set_focus_prefs(body: FocusPrefIn):
    """保存番茄钟时长（只更新传了的字段），返回最新值。"""
    if body.work_minutes is not None:
        db.set_setting("focus_work_minutes", body.work_minutes)
    if body.break_minutes is not None:
        db.set_setting("focus_break_minutes", body.break_minutes)
    return get_focus_prefs()
