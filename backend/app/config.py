"""全局配置：路径、CORS、AI/OnlyOffice 环境变量。

逻辑：所有“会随部署环境变化”的量（端口、密钥、外部服务地址）都从环境变量读，
默认值指向本地开发。这样同一份代码在本地和以后上云不用改代码。
"""
from pathlib import Path
import os

# 让 backend/.env 生效（README 的 cp .env.example .env 才有意义）。
# load_dotenv 找不到 .env 时静默跳过，不影响其他启动路径；且不覆盖已存在的环境变量。
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# backend/ 目录（app 的父目录）
BASE_DIR = Path(__file__).resolve().parent.parent

# SQLite 单文件库 + 生成的 Office 文件都落在 data/ 下
DATA_DIR = BASE_DIR / "data"
DOCS_DIR = DATA_DIR / "docs"
DB_PATH = DATA_DIR / "app.db"

# 前端开发服务器地址（Vite 默认 5173），用于 CORS 放行
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
).split(",")

# OnlyOffice Docs 服务地址（本地 Docker 默认 8080）
ONLYOFFICE_URL = os.getenv("ONLYOFFICE_URL", "http://localhost:8080")

# 后端对外可达地址：OnlyOffice 服务端要回源拉取/回调这个地址，必须能被 OO 容器访问。
# 本地同机调试默认 localhost:8000；OO 跑在 Docker 里时填 http://host.docker.internal:8000
# 或电脑局域网 IP:8000，否则 OO 拉不到文件、回调也打不到后端。
BACKEND_PUBLIC_URL = os.getenv("BACKEND_PUBLIC_URL", "http://localhost:8000")

# 前端浏览器加载 OnlyOffice 编辑器脚本用的地址（OO 的“编辑器服务”地址）。
# 与 ONLYOFFICE_URL（后端视角）分离：OO 可能在 Docker / 远程，
# 前端浏览器要从“自己能访问”的地址加载编辑器脚本（同机用 localhost:8080，
# 或 Docker 把 8080 映射到的宿主机端口 / 局域网 IP:8080），否则前端拉不到编辑器。
# OO 部署经典坑：把“后端怎么访问 OO”和“浏览器怎么访问 OO”当成一回事 —— 二者视角不同。
ONLYOFFICE_PUBLIC_URL = os.getenv("ONLYOFFICE_PUBLIC_URL", ONLYOFFICE_URL)

# 豆包（火山方舟 Volcengine Ark）走 OpenAI 兼容接口
ARK_API_KEY = os.getenv("ARK_API_KEY", "")
ARK_BASE_URL = os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
ARK_MODEL = os.getenv("ARK_MODEL", "doubao-seed-1-6-250615")

# AI 层配置：默认豆包；没配 key 时自动用 MockProvider（离线可跑）
AI_PROVIDER = os.getenv("AI_PROVIDER", "doubao")
# RAG 检索后端：fts（默认，SQLite FTS5）| chromadb（语义向量，需安装）
RAG_BACKEND = os.getenv("RAG_BACKEND", "fts")

# 后端监听端口
PORT = int(os.getenv("PORT", "8000"))

# 生成器离线时（后端未运行）落盘的待入库任务 JSON
STUDY_PENDING = DATA_DIR / "study_tasks_pending.json"

# 备考任务前端页的“可达地址”，用于生成企业微信推送里的点开链接。
# 三种取值对应 P3 三种可达性方案：
#  - 本机开发：http://127.0.0.1:5173（默认，仅电脑自己能开）
#  - 同局域网：http://<电脑局域网IP>:5173（手机连同一 WiFi 可开）
#  - 公网隧道：https://xxxx.trycloudflare.com（cloudflared 给的随机地址，任意网络可开）
# 生成器拼链接时追加 /study-tasks?date=YYYY-MM-DD，前端会据此直接定位到那一天。
STUDY_WEB_BASE_URL = os.getenv("STUDY_WEB_BASE_URL", "http://127.0.0.1:5173")

# 番茄钟默认时长（分钟）。可在前端设置里改，落 app_settings 表持久化。
# 默认 25 分钟工作 / 5 分钟休息，经典 Pomodoro 节奏；环境变量可整体覆盖。
FOCUS_WORK_MINUTES = int(os.getenv("FOCUS_WORK_MINUTES", "25"))
FOCUS_BREAK_MINUTES = int(os.getenv("FOCUS_BREAK_MINUTES", "5"))

# 备考任务页的访问口令（P3-A 公网隧道 / P3-B 同局域网时用，防别人误改）。
# 为空 = 不校验（本地/开发默认，零摩擦）；设了值，则 study-tasks 全部接口
# 必须带请求头 X-Study-Token 且等于此值，否则 401。前端首次打开会要你输口令。
STUDY_PAGE_TOKEN = os.getenv("STUDY_PAGE_TOKEN", "")


def ensure_dirs() -> None:
    """启动时保证数据目录存在。逻辑：延迟创建，避免仓库里塞空目录。"""
    DATA_DIR.mkdir(exist_ok=True)
    DOCS_DIR.mkdir(exist_ok=True)
