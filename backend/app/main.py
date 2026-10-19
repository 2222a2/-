"""FastAPI 应用入口。

Phase 0 只做：
1. 启动事件里 init_db() 建库建表（幂等）；并吃掉生成器离线落盘的待入库任务；
2. 放开 CORS，允许前端开发服务器跨域调用；
3. 暴露 /api/health 作为联调与存活探针。

后续模块的路由（任务、文档、AI、分析引擎…）会逐个挂到 /api 下。
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import CORS_ORIGINS, STUDY_PENDING
from .db import init_db
from . import schemas
from .ai import router as ai_router
from .knowledge import router as knowledge_router
from . import study_tasks
from . import tasks
from . import analysis
from . import docs
from . import focus
from . import prefs
from . import reward


app = FastAPI(title="工作学习一体化平台", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    """应用启动时建库，并把生成器离线落盘的任务吃进库（后端之前没在线时）。"""
    init_db()
    from . import db as _db

    ingested = _db.ingest_pending_study_tasks(str(STUDY_PENDING))
    if ingested:
        print(f"[study_tasks] 启动时同步了 {ingested} 条离线待入库任务")


@app.get("/api/health", response_model=schemas.HealthOut)
def health():
    return schemas.HealthOut(
        status="ok",
        service="worklearn-backend",
        version="0.3.0",
    )


# M2 AI 助手层：/api/ai/status|chat|agent|command
app.include_router(ai_router.router)
# M0 资料聚合底座：/api/knowledge/clip|notes|uploads|/|/{id}
app.include_router(knowledge_router)
# 备考学习任务：/api/study-tasks
app.include_router(study_tasks.router)
# M3 任务管理 + 自动周报：/api/tasks、/api/reports
app.include_router(tasks.router)
app.include_router(tasks.reports_router)
# M4 分析引擎：/api/analysis（四阶段状态机）
app.include_router(analysis.router)
# M1 文档中心：/api/docs（AI 生成真实 Office + OnlyOffice 回存 + 版本管理）
app.include_router(docs.router)
# M7 专注计时：/api/focus（start/stop/active/history），专注只写 focus_session，周报聚合读取
app.include_router(focus.router)
# 用户偏好设置：/api/settings/focus（番茄钟工作/休息时长，落库复用）
app.include_router(prefs.router)
# M6 奖励系统：/api/reward（积分/打卡/徽章/复盘视频）
app.include_router(reward.router)
