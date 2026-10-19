"""M6 奖励系统路由：账户状态、每日打卡、徽章、复盘视频。

设计：积分来自三类行为（完成任务 / 复习 / 打卡），由 study_tasks PATCH done0→1 钩子
与 POST /checkin 写入；徽章由 db.evaluate_badges 自动判定；复盘视频落 reward_video。
单用户，账户固定 id=1。
"""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from . import db

router = APIRouter(prefix="/api/reward", tags=["reward"])


@router.get("")
def reward_state():
    """返回账户全景：积分 / 等级 / 经验 / 连续打卡 / 徽章 / 打卡总数。"""
    return db.get_reward_state()


@router.post("/checkin")
def checkin():
    """每日打卡：+积分并更新连续天数。"""
    return db.checkin_today()


@router.get("/badges")
def badges():
    """已获得的徽章列表。"""
    return db.list_badges()


@router.get("/video")
def videos():
    """复盘视频历史列表。"""
    return db.list_videos()


@router.post("/video/generate")
def generate_video():
    """生成本期复盘视频（MP4）。合成逻辑见 app.video_gen。"""
    from . import video_gen

    try:
        rec = video_gen.generate_review_video()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, **rec}


@router.get("/video/{vid}/file")
def video_file(vid: int):
    """静态文件服务：播放复盘视频。"""
    rec = db.get_video(vid)
    if not rec or not rec.get("path") or not Path(rec["path"]).exists():
        return {"ok": False, "error": "视频不存在或未生成"}
    return FileResponse(rec["path"], media_type="video/mp4")
