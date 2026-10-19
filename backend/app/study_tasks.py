"""备考学习任务路由：生成器写入 + 前端/微信读取 + 手动增删改 + 周进度聚合。

数据落在 study_task 表（见 db.py），与既有 task 表解耦，避免污染通用 GTD 任务流。
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Depends, Header

from . import db
from . import schemas
from .config import STUDY_PAGE_TOKEN


def verify_study_token(x_study_token: str | None = Header(default=None, alias="X-Study-Token")):
    """口令保护：STUDY_PAGE_TOKEN 为空则放行（本地默认）；设了就必须带且正确，否则 401。

    这样走公网隧道 / 同局域网时，页面不会裸奔被人误改；本地开发无需任何改动。
    """
    if not STUDY_PAGE_TOKEN:
        return
    if x_study_token != STUDY_PAGE_TOKEN:
        raise HTTPException(status_code=401, detail="口令错误")


router = APIRouter(
    prefix="/api/study-tasks",
    tags=["study-tasks"],
    dependencies=[Depends(verify_study_token)],
)


def _monday_of(date_str: str) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d")
    monday = d - timedelta(days=d.weekday())
    return monday.strftime("%Y-%m-%d")


def _sunday_of(date_str: str) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d")
    sunday = d + timedelta(days=(6 - d.weekday()))
    return sunday.strftime("%Y-%m-%d")


@router.post("", response_model=dict)
def create_study_tasks(payload: dict):
    """批量建某天任务（生成器调用）。payload: {"date": "YYYY-MM-DD", "items": [...]}。

    每天只重建 source='auto' 的任务，手动添加的任务保留。
    """
    date_str = payload.get("date")
    items = payload.get("items", [])
    if not date_str:
        raise HTTPException(status_code=400, detail="date required")
    db.upsert_study_tasks_for_date(date_str, items)
    return {"ok": True, "date": date_str, "count": len(items)}


@router.get("", response_model=list[schemas.StudyTaskOut])
def get_study_tasks(
    date: str | None = None,
    week_start: str | None = None,
    week_end: str | None = None,
):
    """列出任务：按 date，或按周区间 week_start..week_end（含端点）。"""
    return db.list_study_tasks(date=date, week_start=week_start, week_end=week_end)


@router.patch("/{task_id}", response_model=dict)
def patch_study_task(task_id: int, done: int | None = None, title: str | None = None):
    """修改单个任务：勾选状态(done) 或标题(title)。"""
    if done is None and title is None:
        raise HTTPException(status_code=400, detail="nothing to update")
    db.patch_study_task(task_id, done=done, title=title)
    return {"ok": True, "id": task_id}


@router.delete("/{task_id}", response_model=dict)
def delete_study_task(task_id: int):
    """删除单个任务（手动添加的可删；自动任务次日重建会补回，见 db.delete_study_task 说明）。"""
    ok = db.delete_study_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="study task not found")
    return {"ok": True, "id": task_id}


@router.post("/add", response_model=dict)
def add_study_task(
    date: str,
    period: str | None = None,
    subject: str | None = None,
    title: str = "",
    sort_order: int = 0,
):
    """手动新增一个备考任务（source='manual'）。"""
    if not title:
        raise HTTPException(status_code=400, detail="title required")
    tid = db.add_study_task(date, period, subject, title, sort_order)
    return {"ok": True, "id": tid}


@router.get("/weekly", response_model=schemas.WeeklyProgressOut)
def weekly_progress(date: str | None = None):
    """按周聚合完成度：取 date 所在周的周一~周日。默认用今天。"""
    base = date or datetime.now().strftime("%Y-%m-%d")
    ws = _monday_of(base)
    we = _sunday_of(base)
    return db.weekly_progress(ws, we)
