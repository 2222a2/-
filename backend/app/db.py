"""SQLite 数据库层：连接管理 + 建表（7 张业务表 + 1 张 FTS5 全文索引）。

为什么用 SQLite：
- 零部署、单文件、本地优先，契合“数据在自己电脑”的定位；
- 支持 FTS5 全文检索（trigram 分词），中文子串免分词即可命中，够我们做全局搜索；
- 向量检索另走 chromadb（Phase 1 M2 接入），这里不混。

建表逻辑：
- task 用 parent_id 自引用实现“父子任务 / 子任务”，完成度由子任务汇总（应用层算）；
- plan_analysis / doc / focus_session / report / reward / knowledge_card 各司其职；
- search_index 是 FTS5 虚拟表，统一索引 task/doc/card 的标题与正文，供全局搜索一把搜全站。
"""
import html
import json
import sqlite3
from pathlib import Path

from .config import DB_PATH, ensure_dirs


def _pinyin(text: str) -> str:
    """取标题拼音串，用于按拼音排序/分组。未装 pypinyin 时回退为原文。"""
    try:
        from pypinyin import lazy_pinyin
        return "".join(lazy_pinyin(text or ""))
    except Exception:
        return text or ""

SCHEMA = """
CREATE TABLE IF NOT EXISTS task (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id    INTEGER REFERENCES task(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    description  TEXT,
    deadline     TEXT,                 -- ISO 时间字符串
    urgency      INTEGER DEFAULT 0,    -- 紧急度 0/1
    importance   INTEGER DEFAULT 0,    -- 重要度 0/1 -> 与 urgency 组合成四象限
    status       TEXT DEFAULT 'todo',  -- todo | doing | done | blocked
    completion   INTEGER DEFAULT 0,    -- 0-100，父任务由子任务汇总
    created_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS study_task (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL,        -- YYYY-MM-DD
    period      TEXT,                 -- morning | noon | evening
    subject     TEXT,                 -- math | english | cs408 | ds | other
    title       TEXT NOT NULL,
    done        INTEGER DEFAULT 0,    -- 0/1
    source      TEXT DEFAULT 'auto',  -- auto(生成器) | manual(手动添加) | review(遗忘曲线复习)
    sort_order  INTEGER DEFAULT 0,
    review_of   INTEGER DEFAULT NULL, -- 指向原始新学任务 id；新学任务为 NULL
    review_stage INTEGER DEFAULT NULL, -- 1..5，对应第几轮复习
    due_offset  INTEGER DEFAULT NULL, -- 1/2/4/7/15，相对学习日的天数偏移
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plan_analysis (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    INTEGER NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    requirement TEXT,                 -- 需求确认卡（目标/范围/约束/假设）
    steps_json TEXT,                  -- 拆解出的步骤数组 JSON
    qa_log_json TEXT,                 -- 逐步追问的问题预案 JSON
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS doc (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    path           TEXT NOT NULL,     -- 落盘的 .docx/.xlsx/.pptx 真实路径
    type           TEXT,              -- word | excel | ppt
    linked_task_id INTEGER REFERENCES task(id) ON DELETE SET NULL,
    versions_json  TEXT,              -- 版本快照列表
    created_at     TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS focus_session (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    INTEGER REFERENCES task(id) ON DELETE CASCADE,
    started_at TEXT,
    ended_at   TEXT,
    duration   INTEGER DEFAULT 0,     -- 秒，专注总时长
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS report (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    type         TEXT,                -- weekly | monthly
    period_start TEXT,
    period_end   TEXT,
    content      TEXT,                -- 报告正文（Markdown）
    auto_generated INTEGER DEFAULT 1,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reward_account (
    id           INTEGER PRIMARY KEY CHECK (id = 1),  -- 单用户固定 1 行
    points       INTEGER DEFAULT 0,    -- 累计积分（同时作为经验）
    level        INTEGER DEFAULT 1,
    streak       INTEGER DEFAULT 0,    -- 连续打卡天数
    last_checkin TEXT,                 -- 最近打卡日期 YYYY-MM-DD
    created_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reward_checkin (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT NOT NULL,         -- YYYY-MM-DD
    points     INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reward_badge (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    badge_key  TEXT NOT NULL UNIQUE,  -- first_task | first_review | streak_3/7/30 | points_100/500
    badge_name TEXT NOT NULL,
    earned_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reward_video (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT,
    path         TEXT,                 -- data/videos/review_<ts>.mp4
    period_start TEXT,
    period_end   TEXT,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reward_event (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type  TEXT NOT NULL,         -- task_done | review_done | checkin | badge
    points      INTEGER DEFAULT 0,      -- 本次增减积分
    ref_id      INTEGER,                -- 关联 study_task.id 等
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS knowledge_card (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT,
    content     TEXT,
    source_type TEXT,                 -- web_clip | upload | task_doc | note
    source_id   TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

-- 笔记包（多层文件夹）：parent_id 自引用，NULL 表示顶层；
-- 删包时子资料的 package_id 置 NULL（回到未归档），子包变顶层。
CREATE TABLE IF NOT EXISTS note_package (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    parent_id   INTEGER REFERENCES note_package(id) ON DELETE SET NULL,
    sort_order  INTEGER DEFAULT 0,
    color       TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

-- 统一全文索引：把 task/doc/card 的标题+正文灌进来，source_type+source_id 回查原表
CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
    source_type,
    source_id,
    title,
    body,
    tokenize = 'trigram'              -- trigram：中文不需要分词器，子串即可命中
);
"""


def get_conn() -> sqlite3.Connection:
    """返回开启了 Row 工厂与外键约束的连接。"""
    ensure_dirs()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """首次启动时建表（IF NOT EXISTS 保证幂等，可重复调用）。"""
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    migrate_schema()


def migrate_schema() -> None:
    """幂等迁移：扩展 knowledge_card + 建 note_package + 回填旧数据。

    设计约定（与项目对齐）：
    - content 永远是 FTS 真源（纯文本）；rich_body 存 HTML（展示用）。
    - item_type（note|website|file）与 source_type 并存；旧数据按映射补全。
    - title_pinyin 用于按拼音排序/分组（SQLite 默认按 Unicode 码点，非拼音）。
    """
    conn = get_conn()
    # note_package 表（幂等）
    conn.execute(
        """CREATE TABLE IF NOT EXISTS note_package (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               name TEXT NOT NULL,
               parent_id INTEGER REFERENCES note_package(id) ON DELETE SET NULL,
               sort_order INTEGER DEFAULT 0,
               color TEXT,
               created_at TEXT DEFAULT (datetime('now')),
               updated_at TEXT DEFAULT (datetime('now')))"""
    )
    # knowledge_card 扩展列（缺才加）
    existing = {r[1] for r in conn.execute("PRAGMA table_info(knowledge_card)").fetchall()}
    alters = []
    if "item_type" not in existing:
        alters.append("ALTER TABLE knowledge_card ADD COLUMN item_type TEXT")
    if "package_id" not in existing:
        alters.append(
            "ALTER TABLE knowledge_card ADD COLUMN package_id "
            "INTEGER REFERENCES note_package(id) ON DELETE SET NULL"
        )
    if "url" not in existing:
        alters.append("ALTER TABLE knowledge_card ADD COLUMN url TEXT")
    if "rich_body" not in existing:
        alters.append("ALTER TABLE knowledge_card ADD COLUMN rich_body TEXT")
    if "title_pinyin" not in existing:
        alters.append("ALTER TABLE knowledge_card ADD COLUMN title_pinyin TEXT")
    for a in alters:
        conn.execute(a)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_card_package ON knowledge_card(package_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_card_itemtype ON knowledge_card(item_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_card_created ON knowledge_card(created_at)")

    # 移除 Phase1 遗留的空壳 reward 表（仅 (id,points,badges_json,videos_json)，无数据），改5表模型
    try:
        conn.execute("DROP TABLE reward")
    except Exception:
        pass  # 新库本就没有旧 reward 表，忽略

    # study_task 扩展列（遗忘曲线复习用，缺才加；新库由 SCHEMA 自带）
    _st_cols = {r[1] for r in conn.execute("PRAGMA table_info(study_task)").fetchall()}
    _st_alters = []
    for _col, _ctype in (
        ("review_of", "INTEGER DEFAULT NULL"),
        ("review_stage", "INTEGER DEFAULT NULL"),
        ("due_offset", "INTEGER DEFAULT NULL"),
    ):
        if _col not in _st_cols:
            _st_alters.append(f"ALTER TABLE study_task ADD COLUMN {_col} {_ctype}")
    for _a in _st_alters:
        conn.execute(_a)
    conn.commit()

    # 回填旧行
    mapping = {"web_clip": "website", "upload": "file", "note": "note", "task_doc": "file"}
    rows = conn.execute(
        "SELECT id,title,content,source_type,item_type,rich_body,title_pinyin "
        "FROM knowledge_card"
    ).fetchall()
    for r in rows:
        upd, vals = [], []
        if not r["item_type"]:
            upd.append("item_type=?"); vals.append(mapping.get(r["source_type"], "note"))
        if r["rich_body"] is None and r["content"] is not None:
            rb = "<p>" + html.escape(r["content"]) + "</p>"
            upd.append("rich_body=?"); vals.append(rb)
        if not r["title_pinyin"]:
            upd.append("title_pinyin=?"); vals.append(_pinyin(r["title"] or ""))
        if upd:
            conn.execute(
                f"UPDATE knowledge_card SET {','.join(upd)} WHERE id=?", vals + [r["id"]]
            )
    conn.commit()
    conn.close()


def upsert_search(source_type: str, source_id: int, title: str, body: str) -> None:
    """往全局搜索索引里写/更新一条。逻辑：先删后插，保证更新后索引一致。"""
    conn = get_conn()
    conn.execute(
        "DELETE FROM search_index WHERE source_type=? AND source_id=?",
        (source_type, source_id),
    )
    conn.execute(
        "INSERT INTO search_index (source_type, source_id, title, body) VALUES (?,?,?,?)",
        (source_type, source_id, title, body),
    )
    conn.commit()
    conn.close()


# ------------------------- 用户偏好设置（app_settings 键值表）-------------------------
# 设计：极简 KV，存“需要跨会话复用、又不想写死在代码里”的小配置（如番茄钟时长）。
# 用 ON CONFLICT 做 upsert，避免“先查再插”的竞态；value 统一存字符串，读取时按类型转换。

def get_setting(key: str, default: str | None = None) -> str | None:
    """读一个设置项；不存在返回 default。"""
    conn = get_conn()
    row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    """写一个设置项（不存在则插入，存在则覆盖）。"""
    conn = get_conn()
    conn.execute(
        "INSERT INTO app_settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    conn.commit()
    conn.close()


def insert_task(
    title: str,
    description: str | None = None,
    deadline: str | None = None,
    urgency: int = 0,
    importance: int = 0,
    parent_id: int | None = None,
) -> int:
    """新建任务并同步进全局搜索索引。返回新任务 id。"""
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO task (title, description, deadline, urgency, importance, parent_id)
           VALUES (?,?,?,?,?,?)""",
        (title, description, deadline, urgency, importance, parent_id),
    )
    tid = cur.lastrowid
    conn.commit()
    conn.close()
    upsert_search("task", tid, title, description or "")
    return tid


def list_tasks(limit: int = 20, status: str | None = None) -> list[dict]:
    """列出任务（默认按创建时间倒序）。status 可选过滤。"""
    conn = get_conn()
    if status:
        rows = conn.execute(
            "SELECT * FROM task WHERE status=? ORDER BY id DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM task ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# M3 任务管理：CRUD + 完成度汇总（父任务由子任务均值算出）+ 自动周报。
# 为什么父任务完成度应用层算：子任务才是“真实进度”，父只是聚合视图；
# 放在应用层避免触发器复杂度，且能顺带向上冒泡更新祖父。
# ---------------------------------------------------------------------------

def get_task(tid: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM task WHERE id=?", (tid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_task(tid: int, **fields) -> bool:
    """更新任务字段；改了 title/description 同步全局搜索索引，改了子项冒泡父完成度。"""
    allowed = {"title", "description", "deadline", "urgency", "importance",
               "status", "completion", "parent_id"}
    sets = [k for k in fields if k in allowed and fields[k] is not None]
    if not sets:
        return False
    conn = get_conn()
    cur = conn.execute(
        f"UPDATE task SET {','.join(s + '=?' for s in sets)}, updated_at=datetime('now') "
        f"WHERE id=?",
        [fields[s] for s in sets] + [tid],
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    if not ok:
        return False
    # 搜索索引同步
    if "title" in sets or "description" in sets:
        t = get_task(tid)
        if t:
            upsert_search("task", tid, t["title"], t["description"] or "")
    # 向上冒泡：若本任务有父，重算父完成度
    t = get_task(tid)
    if t and t.get("parent_id"):
        recompute_parent_completion(t["parent_id"])
    return True


def delete_task(tid: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM task WHERE id=?", (tid,))
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    conn2 = get_conn()
    conn2.execute(
        "DELETE FROM search_index WHERE source_type='task' AND source_id=?", (tid,)
    )
    conn2.commit()
    conn2.close()
    return ok


def recompute_parent_completion(parent_id: int) -> None:
    """父任务 completion = 子任务 completion 的均值（无子任务则保留手动值）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT completion FROM task WHERE parent_id=?", (parent_id,)
    ).fetchall()
    conn.close()
    if rows:
        avg = round(sum(r["completion"] for r in rows) / len(rows))
        update_task(parent_id, completion=avg)


def list_stale_tasks(days: int = 7) -> list[dict]:
    """返回「久未更新且未完成」的任务（防空洞提醒）。

    days 阈值默认 7 天。判定：status != 'done' 且距 updated_at 已超 days 天。
    为什么默认 7 天：一周没动的事，要么是忘了推进，要么是该归档/删除的“防空洞”。
    用 JULIANDAY 算天数差，跨月/跨年也准确；CAST(... AS INTEGER) 取整便于展示。
    """
    conn = get_conn()
    rows = conn.execute(
        """SELECT id, title, status, updated_at,
                  CAST(JULIANDAY('now') - JULIANDAY(updated_at) AS INTEGER) AS days_since
           FROM task
           WHERE status != 'done'
             AND JULIANDAY('now') - JULIANDAY(updated_at) >= ?
           ORDER BY updated_at ASC""",
        (days,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_task_tree() -> list[dict]:
    """返回顶层任务（parent_id 为 NULL）列表，每项带 children；父完成度实时由子汇总。"""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM task ORDER BY id").fetchall()
    conn.close()
    tasks = [dict(r) for r in rows]
    by_parent: dict[int | None, list] = {}
    for t in tasks:
        by_parent.setdefault(t["parent_id"], []).append(t)
    roots = by_parent.get(None, [])
    for p in roots:
        children = by_parent.get(p["id"], [])
        p["has_children"] = bool(children)
        if children:
            p["completion"] = round(sum(c["completion"] for c in children) / len(children))
        p["children"] = children
    return roots


def _fmt_duration(sec: int) -> str:
    """把秒数渲染成人类可读时长；<1h 时带分钟/秒，避免 5s 显示成 0h 0m。"""
    sec = int(sec or 0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m}m"
    if m:
        return f"{m}m{s}s"
    return f"{s}s"


def _aggregate_docs_for_period(start: str, end: str) -> tuple[int, list[str]]:
    """统计周期内生成的文档（doc 表 created_at 落在 [start, end]）。

    返回 (文档数, Markdown 行列表)。用于周报/月报的「文档」维度——
    PRD M3 明确要求报告聚合「done 任务 + 文档 + 工时」，此前两版报告都漏了文档维度
    （见《阶段技术约束一致性审计》#7），本次补齐。
    为什么 LEFT JOIN task：doc.linked_task_id 可能为空，且要展示“关联任务名”。
    """
    conn = get_conn()
    rows = conn.execute(
        """SELECT d.path, d.type, t.title AS task_title
           FROM doc d
           LEFT JOIN task t ON t.id = d.linked_task_id
           WHERE d.created_at >= ? AND d.created_at <= ?
           ORDER BY d.id""",
        (start, end + " 23:59:59"),
    ).fetchall()
    conn.close()
    lines = []
    for d in rows:
        fname = Path(d["path"]).name
        tname = d["task_title"] or "未关联任务"
        lines.append(f"- {fname}（{d['type']} · 关联：{tname}）")
    return len(rows), lines


def _save_report(rtype: str, period_start: str, period_end: str, markdown: str) -> None:
    """把生成的报告落到 report 表（type=weekly|monthly）。

    为什么 delete+insert 而不是只 insert：报告是“某周期一份”的聚合产物，
    重复生成（多次打开周报页 / 重新点月报）应覆盖同一份，而不是越攒越多。
    用 (type, period_start) 作幂等键，每次生成都刷新该周期那一行。
    """
    conn = get_conn()
    try:
        conn.execute(
            "DELETE FROM report WHERE type=? AND period_start=?",
            (rtype, period_start),
        )
        conn.execute(
            "INSERT INTO report(type, period_start, period_end, content, auto_generated) "
            "VALUES(?,?,?,?,1)",
            (rtype, period_start, period_end, markdown),
        )
        conn.commit()
    finally:
        conn.close()


def generate_weekly_report() -> dict:
    """聚合本周(周一~周日) 已完成任务 + 专注工时，生成 Markdown 草稿。

    为什么这样聚合：周报 = “做了什么” + “投入多少”，二者分别从 task(done)
    和 focus_session(工时) 取，靠 task_id 关联，模块解耦、零额外录入。
    落库：同一周期只保留一份（见 _save_report）。
    """
    from datetime import datetime, timedelta
    today = datetime.now()
    monday = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    sunday = (today + timedelta(days=6 - today.weekday())).strftime("%Y-%m-%d")
    conn = get_conn()
    done = conn.execute(
        "SELECT * FROM task WHERE status='done' AND updated_at>=? AND updated_at<=? "
        "ORDER BY deadline",
        (monday, sunday + " 23:59:59"),
    ).fetchall()
    focus = conn.execute(
        "SELECT task_id, SUM(duration) AS total FROM focus_session "
        "WHERE started_at>=? AND started_at<=? GROUP BY task_id",
        (monday, sunday + " 23:59:59"),
    ).fetchall()
    conn.close()
    focus_map = {r["task_id"]: r["total"] for r in focus}
    doc_count, doc_lines = _aggregate_docs_for_period(monday, sunday)

    lines = [f"# 周报（{monday} ~ {sunday}）", ""]
    total_focus = sum(focus_map.values())
    lines.append(f"- 完成事项：**{len(done)} 项**")
    lines.append(f"- 本周专注总时长：**{_fmt_duration(total_focus)}**")
    lines.append(f"- 生成文档：**{doc_count} 份**")
    lines.append("")
    lines.append("## 完成清单")
    for t in done:
        dur = focus_map.get(t["id"], 0)
        dstr = f" · 专注 {_fmt_duration(dur)}" if dur else ""
        lines.append(f"- {t['title']}（完成度 {t['completion']}%）{dstr}")
    lines.append("")
    lines.append("## 本周期文档")
    if doc_lines:
        lines.extend(doc_lines)
    else:
        lines.append("- （本期暂无生成文档）")
    lines.append("")
    lines.append("## 专注时长 Top")
    top = sorted(focus_map.items(), key=lambda x: -x[1])[:5]
    for tid, dur in top:
        t = get_task(tid)
        name = t["title"] if t else f"#{tid}"
        lines.append(f"- {name}：{_fmt_duration(dur)}")
    markdown = "\n".join(lines)
    _save_report("weekly", monday, sunday, markdown)
    return {
        "period_start": monday,
        "period_end": sunday,
        "done_count": len(done),
        "focus_seconds": total_focus,
        "doc_count": doc_count,
        "markdown": markdown,
    }


def generate_monthly_report(year: int | None = None, month: int | None = None) -> dict:
    """聚合某月(默认当前月) 已完成任务 + 专注工时，生成 Markdown 草稿。

    与周报同口径（done 任务 + focus_session 工时，靠 task_id 关联），
    只是周期换成自然月。落库 type=monthly，与周报共用 report 表的幂等键逻辑。
    为什么单独成函数而非参数化周报：月报的“周期边界/展示文案/落库 type”
    差异足够清晰，分开更可读，也避免周报调用方被无关参数污染。
    """
    from calendar import monthrange
    from datetime import datetime
    today = datetime.now()
    y = year or today.year
    m = month or today.month
    start = f"{y:04d}-{m:02d}-01"
    last_day = monthrange(y, m)[1]
    end = f"{y:04d}-{m:02d}-{last_day:02d}"
    conn = get_conn()
    done = conn.execute(
        "SELECT * FROM task WHERE status='done' AND updated_at>=? AND updated_at<=? "
        "ORDER BY deadline",
        (start, end + " 23:59:59"),
    ).fetchall()
    focus = conn.execute(
        "SELECT task_id, SUM(duration) AS total FROM focus_session "
        "WHERE started_at>=? AND started_at<=? GROUP BY task_id",
        (start, end + " 23:59:59"),
    ).fetchall()
    conn.close()
    focus_map = {r["task_id"]: r["total"] for r in focus}
    doc_count, doc_lines = _aggregate_docs_for_period(start, end)

    lines = [f"# 月报（{start} ~ {end}）", ""]
    total_focus = sum(focus_map.values())
    lines.append(f"- 完成事项：**{len(done)} 项**")
    lines.append(f"- 本月专注总时长：**{_fmt_duration(total_focus)}**")
    lines.append(f"- 生成文档：**{doc_count} 份**")
    lines.append("")
    lines.append("## 完成清单")
    for t in done:
        dur = focus_map.get(t["id"], 0)
        dstr = f" · 专注 {_fmt_duration(dur)}" if dur else ""
        lines.append(f"- {t['title']}（完成度 {t['completion']}%）{dstr}")
    lines.append("")
    lines.append("## 本周期文档")
    if doc_lines:
        lines.extend(doc_lines)
    else:
        lines.append("- （本期暂无生成文档）")
    lines.append("")
    lines.append("## 专注时长 Top")
    top = sorted(focus_map.items(), key=lambda x: -x[1])[:5]
    for tid, dur in top:
        t = get_task(tid)
        name = t["title"] if t else f"#{tid}"
        lines.append(f"- {name}：{_fmt_duration(dur)}")
    markdown = "\n".join(lines)
    _save_report("monthly", start, end, markdown)
    return {
        "period_start": start,
        "period_end": end,
        "done_count": len(done),
        "focus_seconds": total_focus,
        "doc_count": doc_count,
        "markdown": markdown,
    }


# ---------------------------------------------------------------------------
# M4 分析引擎：plan_analysis 落库（需求确认卡 / 拆解步骤 / 逐步追问预案）
# 为什么独立成表：分析过程是“任务诞生前的决策痕迹”，与主 task 解耦——
# 一个 plan 对应一个主任务，删主任务时 ON DELETE CASCADE 自动清分析行。
# ---------------------------------------------------------------------------

def save_plan_analysis(task_id: int, requirement: dict, steps: list,
                       qa_log_json: str | None = None) -> int:
    """落库一次分析：需求确认卡(requirement dict) + 拆解步骤(steps list)。返回 plan id。"""
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO plan_analysis (task_id, requirement, steps_json, qa_log_json)
           VALUES (?,?,?,?)""",
        (task_id, json.dumps(requirement, ensure_ascii=False),
         json.dumps(steps, ensure_ascii=False), qa_log_json),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def get_plan_analysis(plan_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM plan_analysis WHERE id=?", (plan_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for key, col in (("requirement", "requirement"), ("steps", "steps_json"), ("qa_log", "qa_log_json")):
        raw = d.get(col)
        try:
            d[key] = json.loads(raw) if raw else ([] if key != "requirement" else None)
        except (json.JSONDecodeError, TypeError):
            d[key] = ([] if key != "requirement" else None)
    return d


def append_plan_qa(plan_id: int, entry: dict) -> bool:
    """向某分析的逐步追问预案追加一条（步骤风险/卡点/前置 + 用户回答）。"""
    p = get_plan_analysis(plan_id)
    if not p:
        return False
    log = p.get("qa_log") or []
    log.append(entry)
    conn = get_conn()
    conn.execute(
        "UPDATE plan_analysis SET qa_log_json=? WHERE id=?",
        (json.dumps(log, ensure_ascii=False), plan_id),
    )
    conn.commit()
    conn.close()
    return True


def insert_knowledge_card(
    title: str,
    content: str,
    source_type: str = "note",
    source_id: str | None = None,
    rich_body: str | None = None,
    item_type: str | None = None,
    package_id: int | None = None,
    url: str | None = None,
) -> int:
    """新建资料卡片并同步进全局搜索索引。返回新卡片 id。

    字段约定：
    - content 永远存纯文本（FTS 真源）；rich_body 存 HTML（展示用，可空）。
    - item_type 缺省时按 source_type 自动映射（web_clip→website 等）。
    - title_pinyin 由标题推算，供按拼音排序/分组。
    """
    if item_type is None:
        item_type = {
            "web_clip": "website", "upload": "file",
            "note": "note", "task_doc": "file",
        }.get(source_type, "note")
    title_pinyin = _pinyin(title or "")
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO knowledge_card
              (title, content, source_type, source_id, rich_body, item_type, package_id, url, title_pinyin)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (title, content, source_type, source_id, rich_body, item_type, package_id, url, title_pinyin),
    )
    cid = cur.lastrowid
    conn.commit()
    conn.close()
    upsert_search("knowledge_card", cid, title, content)
    return cid


def get_knowledge_card(card_id: int) -> dict | None:
    """按 id 取一条资料卡片（含完整正文）。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM knowledge_card WHERE id=?", (card_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_knowledge_cards(limit: int = 50, source_type: str | None = None) -> list[dict]:
    """列出资料卡片（默认按创建时间倒序）。可按来源类型（web_clip/upload/note/task_doc）过滤。"""
    conn = get_conn()
    if source_type:
        rows = conn.execute(
            "SELECT * FROM knowledge_card WHERE source_type=? ORDER BY id DESC LIMIT ?",
            (source_type, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM knowledge_card ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def search_cards(query: str, limit: int = 20) -> list[dict]:
    """仅在资料卡片范围内做全文检索，返回标题 + 命中摘要。

    为什么加 LIKE 兜底（重要）：FTS5 trigram 只索引“3 个字符及以上”的片段，
    2 字中文（如“周报”）或 1 字查询会直接零命中，而中文用户常用短词搜索。
    所以逻辑是：先走 trigram（长查询/子串强），若零命中且查询偏短，再走
    LIKE 子串兜底，保证“搜得到”。两者结果已天然去重（LIKE 仅在 trigram 空时触发）。
    """
    safe = '"' + query.replace('"', '""') + '"'
    conn = get_conn()
    rows = conn.execute(
        """SELECT source_id, title,
                  snippet(search_index, 3, '[', ']', '…', 12) AS body,
                  rank
           FROM search_index
           WHERE source_type='knowledge_card' AND search_index MATCH ?
           ORDER BY rank
           LIMIT ?""",
        (safe, limit),
    ).fetchall()

    # LIKE 兜底：trigram 对超短查询（<3 字符）无效，用子串匹配补上
    if not rows and len(query.strip()) < 3:
        rows = conn.execute(
            """SELECT id AS source_id, title, content AS body, 0 AS rank
               FROM knowledge_card
               WHERE title LIKE ? OR content LIKE ?
               ORDER BY id DESC LIMIT ?""",
            (f"%{query}%", f"%{query}%", limit),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_knowledge_card(card_id: int) -> bool:
    """删除一条资料卡片，并同步清理全文索引（保证搜索结果不出现脏数据）。"""
    conn = get_conn()
    cur = conn.execute("DELETE FROM knowledge_card WHERE id=?", (card_id,))
    conn.execute(
        "DELETE FROM search_index WHERE source_type='knowledge_card' AND source_id=?",
        (card_id,),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def search_kb(query: str, limit: int = 5) -> list[dict]:
    """全文检索（FTS5 trigram）。返回命中行的元数据 + 摘要片段。

    逻辑：trigram 分词下，把查询用双引号包成短语，规避特殊字符导致的语法错误；
    用 bm25 rank 排序，snippet() 截取命中上下文。
    短查询兜底：trigram 对 <3 字符（如两字中文）无效，零命中时退化为 LIKE 子串匹配，
    保证任务/资料里的短词也能被搜到（与 search_cards 同一思路）。
    """
    safe = '"' + query.replace('"', '""') + '"'
    conn = get_conn()
    rows = conn.execute(
        """SELECT source_type, source_id, title,
                  snippet(search_index, 3, '[', ']', '…', 12) AS body,
                  rank
           FROM search_index
           WHERE search_index MATCH ?
           ORDER BY rank
           LIMIT ?""",
        (safe, limit),
    ).fetchall()

    if not rows and len(query.strip()) < 3:
        like = f"%{query}%"
        rows = conn.execute(
            """SELECT 'task' AS source_type, id AS source_id, title,
                      COALESCE(description,'') AS body, 0 AS rank
               FROM task WHERE title LIKE ? OR description LIKE ?
               UNION ALL
               SELECT 'knowledge_card' AS source_type, id AS source_id, title,
                      COALESCE(content,'') AS body, 0 AS rank
               FROM knowledge_card WHERE title LIKE ? OR content LIKE ?
               LIMIT ?""",
            (like, like, like, like, limit),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ------------------------- 笔记包（note_package）-------------------------

def create_package(name: str, parent_id: int | None = None, color: str | None = None,
                   sort_order: int = 0) -> int:
    """新建包，返回新 id。parent_id 为 NULL 表示顶层包。"""
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO note_package (name, parent_id, color, sort_order) VALUES (?,?,?,?)",
        (name, parent_id, color, sort_order),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def list_packages() -> list[dict]:
    """返回所有包（扁平列表，含 parent_id），前端据此递归构树。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM note_package ORDER BY sort_order, name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_package(pid: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM note_package WHERE id=?", (pid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_package(pid: int, name: str | None = None, color: str | None = None,
                   sort_order: int | None = None, parent_id: int | None = None) -> bool:
    """改名/改色/移动。移动时校验不能把包放到自己的子孙下（防环）。"""
    if parent_id is not None:
        if parent_id == pid or parent_id in get_descendant_package_ids(pid):
            raise ValueError("不能把包移到自己或其子孙下")
    sets, vals = [], []
    if name is not None:
        sets.append("name=?"); vals.append(name)
    if color is not None:
        sets.append("color=?"); vals.append(color)
    if sort_order is not None:
        sets.append("sort_order=?"); vals.append(sort_order)
    if parent_id is not None:
        sets.append("parent_id=?"); vals.append(parent_id)
    if not sets:
        return False
    sets.append("updated_at=datetime('now')")
    conn = get_conn()
    conn.execute(f"UPDATE note_package SET {','.join(sets)} WHERE id=?", vals + [pid])
    conn.commit()
    conn.close()
    return True


def delete_package(pid: int) -> bool:
    """删包。子资料 package_id 因 ON DELETE SET NULL 自动回未归档；子包变顶层。"""
    conn = get_conn()
    cur = conn.execute("DELETE FROM note_package WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def get_descendant_package_ids(pid: int) -> set[int]:
    """返回 pid 的所有子孙包 id（不含自身），用于包过滤展开与防环。"""
    conn = get_conn()
    rows = conn.execute("SELECT id, parent_id FROM note_package").fetchall()
    conn.close()
    children: dict = {}
    for r in rows:
        children.setdefault(r["parent_id"], []).append(r["id"])
    result, stack = set(), [pid]
    while stack:
        cur = stack.pop()
        for ch in children.get(cur, []):
            if ch not in result:
                result.add(ch)
                stack.append(ch)
    return result


def query_cards(item_type: str | None = None, package_ids: list[int] | None = None,
                time_start: str | None = None, time_end: str | None = None,
                limit: int = 200) -> list[dict]:
    """按类型 / 归属包 / 时间区间过滤资料卡（组合 AND）。返回平铺列表。"""
    conn = get_conn()
    sql = "SELECT * FROM knowledge_card WHERE 1=1"
    params: list = []
    if item_type:
        sql += " AND item_type=?"
        params.append(item_type)
    if package_ids is not None:
        ph = ",".join("?" * len(package_ids))
        sql += f" AND package_id IN ({ph})"
        params.extend(package_ids)
    if time_start and time_end:
        sql += " AND created_at BETWEEN ? AND ?"
        params.extend([time_start, time_end])
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ------------------------- 备考学习任务（study_task）-------------------------

def upsert_study_tasks_for_date(date_str: str, items: list[dict]) -> None:
    """按日期重建当天的自动任务：先删 source='auto' 的旧项，再批量插入新项。
    手动添加（source='manual'）的任务不受影响，得以保留。"""
    conn = get_conn()
    conn.execute(
        "DELETE FROM study_task WHERE date=? AND source='auto'",
        (date_str,),
    )
    for it in items:
        conn.execute(
            """INSERT INTO study_task (date, period, subject, title, done, source, sort_order)
               VALUES (?,?,?,?,?,?,?)""",
            (
                date_str,
                it.get("period"),
                it.get("subject"),
                it["title"],
                1 if it.get("done") else 0,
                it.get("source", "auto"),
                it.get("sort_order", 0),
            ),
        )
    conn.commit()
    conn.close()


def list_study_tasks(
    date: str | None = None,
    week_start: str | None = None,
    week_end: str | None = None,
) -> list[dict]:
    """列出备考任务。可按日期，或按周区间（week_start..week_end 含端点）。"""
    conn = get_conn()
    if date:
        rows = conn.execute(
            "SELECT * FROM study_task WHERE date=? ORDER BY period, sort_order",
            (date,),
        ).fetchall()
    elif week_start and week_end:
        rows = conn.execute(
            "SELECT * FROM study_task WHERE date>=? AND date<=? ORDER BY date, period, sort_order",
            (week_start, week_end),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM study_task ORDER BY date DESC, period, sort_order LIMIT 200"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def patch_study_task(task_id: int, done: int | None = None, title: str | None = None) -> bool:
    """修改单个任务：勾选状态或标题。"""
    conn = get_conn()
    if done is not None:
        conn.execute(
            "UPDATE study_task SET done=?, updated_at=datetime('now') WHERE id=?",
            (done, task_id),
        )
    if title is not None:
        conn.execute(
            "UPDATE study_task SET title=?, updated_at=datetime('now') WHERE id=?",
            (title, task_id),
        )
    conn.commit()
    conn.close()
    return True


def add_study_task(
    date: str, period: str | None, subject: str | None, title: str, sort_order: int = 0
) -> int:
    """手动新增一个备考任务（source='manual'）。返回新 id。"""
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO study_task (date, period, subject, title, done, source, sort_order)
           VALUES (?,?,?,?,0,'manual',?)""",
        (date, period, subject, title, sort_order),
    )
    tid = cur.lastrowid
    conn.commit()
    conn.close()
    return tid


def delete_study_task(task_id: int) -> bool:
    """删除单个备考任务（手动/自动均可删）。

    注意：自动任务(source='auto')由生成器每天重建——今天删了某条自动任务，
    明天生成器重跑会把它加回来（这是预期的，自动任务描述的是“计划”，不是“历史”）。
    手动任务(source='manual')删后永久消失。
    """
    conn = get_conn()
    cur = conn.execute("DELETE FROM study_task WHERE id=?", (task_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# --- 遗忘曲线复习（M5）：复用 study_task 表，加 review_of/review_stage/due_offset 三列记录血缘 ---
# 触发点：原始新学任务 done 0→1 时由路由调用 spawn_reviews_for_task 生成 1/2/4/7/15 天后复习；
# 复习任务 done=1 不连锁（只在 review_of IS NULL 的原始任务上触发），避免指数爆炸。

REVIEW_OFFSETS = [1, 2, 4, 7, 15]  # 艾宾浩斯经验节点，可调


def get_study_task_done(task_id: int) -> int:
    """取某备考任务当前的 done 值（0/1）。找不到返回 0（PATCH 触发判定用）。"""
    conn = get_conn()
    row = conn.execute("SELECT done FROM study_task WHERE id=?", (task_id,)).fetchone()
    conn.close()
    return row["done"] if row else 0


def spawn_reviews_for_task(task_id: int) -> int:
    """原始新学任务被标记完成时，生成 1/2/4/7/15 天后的复习任务。返回生成条数。

    幂等：先按 review_of 清掉该任务已有的复习任务再插，重复勾选不会重复节点。
    只在 review_of IS NULL 的原始任务上触发；复习任务 done=1 不会连锁生成。
    """
    from datetime import datetime, timedelta

    conn = get_conn()
    row = conn.execute(
        "SELECT id, date, period, subject, title FROM study_task "
        "WHERE id=? AND review_of IS NULL",
        (task_id,),
    ).fetchone()
    if not row:
        conn.close()
        return 0
    base_date = row["date"]
    today = datetime.now().strftime("%Y-%m-%d")

    # 幂等清空：删除该原始任务已有的复习节点（取消再勾也不会翻倍）
    conn.execute(
        "DELETE FROM study_task WHERE source='review' AND review_of=?",
        (task_id,),
    )

    count = 0
    for stage, offset in enumerate(REVIEW_OFFSETS, start=1):
        due = (datetime.strptime(base_date, "%Y-%m-%d") + timedelta(days=offset)).strftime("%Y-%m-%d")
        if due < today:
            continue  # 理论不会发生（offset>=1），保险跳过过去日期
        conn.execute(
            """INSERT INTO study_task
               (date, period, subject, title, done, source, sort_order,
                review_of, review_stage, due_offset)
               VALUES (?,?,?,?,0,'review',0,?,?,?)""",
            (due, row["period"], row["subject"],
             f"复习：{row['title']}", task_id, stage, offset),
        )
        count += 1
    conn.commit()
    conn.close()
    return count


def list_due_reviews(date_str: str) -> list[dict]:
    """返回某天到期且未完成的复习任务（供前端'今日待复习'卡片）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM study_task WHERE date=? AND source='review' AND done=0 "
        "ORDER BY review_stage",
        (date_str,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def weekly_progress(week_start: str, week_end: str) -> dict:
    """按周聚合完成度：总完成、各科目完成、每日完成。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM study_task WHERE date>=? AND date<=?",
        (week_start, week_end),
    ).fetchall()
    conn.close()
    tasks = [dict(r) for r in rows]
    total = len(tasks)
    done = sum(1 for t in tasks if t["done"])
    by_subject: dict = {}
    by_date: dict = {}
    for t in tasks:
        s = t["subject"] or "其他"
        by_subject.setdefault(s, {"total": 0, "done": 0})
        by_subject[s]["total"] += 1
        by_subject[s]["done"] += 1 if t["done"] else 0
        d = t["date"]
        by_date.setdefault(d, {"total": 0, "done": 0})
        by_date[d]["total"] += 1
        by_date[d]["done"] += 1 if t["done"] else 0
    return {
        "week_start": week_start,
        "week_end": week_end,
        "total": total,
        "done": done,
        "rate": round(done / total, 3) if total else 0,
        "by_subject": by_subject,
        "by_date": by_date,
    }


def daily_completion_map(start: str, end: str) -> list[dict]:
    """返回 [start, end] 区间内每一天的完成度（total/done/rate），按日期升序。

    用于前端进度热力图：区间内的每一天都返回（含无任务的空白天，rate=0），
    这样前端能画一张完整连续的日历网格，而不是只画有数据的零散几天。
    """
    from datetime import datetime, timedelta

    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM study_task WHERE date>=? AND date<=?",
        (start, end),
    ).fetchall()
    conn.close()
    by_date: dict = {}
    for r in rows:
        d = r["date"]
        rec = by_date.setdefault(d, {"date": d, "total": 0, "done": 0})
        rec["total"] += 1
        rec["done"] += 1 if r["done"] else 0
    # 填充区间全部日期（即使当天无任务，也补一条 rate=0）
    result = []
    cur = datetime.strptime(start, "%Y-%m-%d")
    end_d = datetime.strptime(end, "%Y-%m-%d")
    while cur <= end_d:
        ds = cur.strftime("%Y-%m-%d")
        rec = by_date.get(ds, {"date": ds, "total": 0, "done": 0})
        rec["rate"] = round(rec["done"] / rec["total"], 3) if rec["total"] else 0
        result.append(rec)
        cur += timedelta(days=1)
    return result


# ------------------------- M1 文档中心（doc）-------------------------
# doc 表：path(真实文件) / type(word|excel|ppt) / linked_task_id(关联任务)
#        / versions_json(版本快照列表) / created_at。
# 落库与“真实文件落盘”解耦：先插一行拿 id → 文件名用 id 命名 → 再回填 path；
# 这样文件名稳定、删除/回滚都能按 id 定位，不依赖标题变化。

def insert_doc(path: str, doc_type: str, linked_task_id: int | None = None,
               versions_json: str | None = None) -> int:
    """新建文档记录并同步进全局搜索索引，返回新 doc id。"""
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO doc (path, type, linked_task_id, versions_json)
           VALUES (?,?,?,?)""",
        (path, doc_type, linked_task_id, versions_json),
    )
    did = cur.lastrowid
    conn.commit()
    conn.close()
    from pathlib import Path as _P
    upsert_search("doc", did, _P(path).name, f"{doc_type} 文档")
    return did


def get_doc(doc_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM doc WHERE id=?", (doc_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_docs(limit: int = 50) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM doc ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_doc_versions(doc_id: int, versions_json: str) -> bool:
    """覆盖式更新版本快照列表（每次保存都整体重写 JSON）。"""
    conn = get_conn()
    cur = conn.execute(
        "UPDATE doc SET versions_json=? WHERE id=?", (versions_json, doc_id)
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def update_doc_linked_task(doc_id: int, linked_task_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute(
        "UPDATE doc SET linked_task_id=? WHERE id=?", (linked_task_id, doc_id)
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def delete_doc(doc_id: int) -> bool:
    """删文档记录并清理搜索索引（真实文件由调用方负责清理，避免误删用户盘上其它文件）。"""
    conn = get_conn()
    cur = conn.execute("DELETE FROM doc WHERE id=?", (doc_id,))
    conn2 = get_conn()
    conn2.execute(
        "DELETE FROM search_index WHERE source_type='doc' AND source_id=?", (doc_id,)
    )
    conn2.commit()
    conn2.close()
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def ingest_pending_study_tasks(path: str) -> int:
    """启动时把生成器离线写的待入库 JSON 吃进来（后端没在线时生成器会落盘）。"""
    import json
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        return 0
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return 0
    count = 0
    for entry in data:
        date_str = entry.get("date")
        items = entry.get("items", [])
        if date_str and items:
            upsert_study_tasks_for_date(date_str, items)
            count += len(items)
    try:
        p.unlink(missing_ok=True)
    except OSError:
        # 删除失败（如 safe-delete 沙箱在非交互环境 FAIL_CLOSED）不应阻断后端启动；
        # pending 已吃进库，文件留着不影响运行，下次启动会再尝试。
        pass
    return count


# ------------------------- M7 专注计时（focus_session）-------------------------
# 设计：专注是“做事的副产品”，不是额外录入。点开始 INSERT(started_at)，点停止
# UPDATE(ended_at, duration)；周报聚合时 SELECT SUM(duration) WHERE 周期内。
# 只写 focus_session 一张表，和 M3 周报靠 task_id 解耦联动（见 M4联动设计文档）。

def _focus_now_str() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def start_focus_session(task_id: int | None = None) -> int:
    """开始一次专注，返回 session id。task_id 可空（纯记录工时也可）。"""
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO focus_session (task_id, started_at) VALUES (?, ?)",
        (task_id, _focus_now_str()),
    )
    sid = cur.lastrowid
    conn.commit()
    conn.close()
    return sid


def stop_focus_session(session_id: int) -> dict:
    """停止专注：补 ended_at + duration(秒)。已停止的返回原值不重算。"""
    from datetime import datetime
    conn = get_conn()
    row = conn.execute(
        "SELECT id, started_at, ended_at, duration FROM focus_session WHERE id=?",
        (session_id,),
    ).fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": "session not found"}
    if row["ended_at"]:
        conn.close()
        return {"ok": True, "already_stopped": True, "duration": row["duration"] or 0}
    started = datetime.strptime(row["started_at"], "%Y-%m-%d %H:%M:%S")
    duration = max(0, int((datetime.now() - started).total_seconds()))
    conn.execute(
        "UPDATE focus_session SET ended_at=?, duration=? WHERE id=?",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), duration, session_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "already_stopped": False, "duration": duration}


def get_active_focus() -> dict | None:
    """返回正在进行（未停止）的专注会话，用于前端刷新恢复计时。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM focus_session WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_focus_sessions(limit: int = 50) -> list[dict]:
    """最近 N 条专注记录（含任务标题），用于历史/回顾。"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT f.*, t.title AS task_title
           FROM focus_session f
           LEFT JOIN task t ON t.id = f.task_id
           ORDER BY f.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ------------------------- M6 奖励系统（reward）-------------------------
# 设计：单用户固定 reward_account(id=1) 一行；积分来自"完成任务/复习/打卡"三类行为；
# 徽章由 evaluate_badges() 基于账户状态自动判定授予；复盘视频落 reward_video。
# 行为钩子复用 study_tasks PATCH done 0→1（见 study_tasks.patch_study_task）。

REWARD_TASK = 5      # 完成一个原始学习任务
REWARD_REVIEW = 3    # 完成一次复习打卡
REWARD_CHECKIN = 2   # 每日打卡
LEVEL_STEP = 100     # 每 100 积分升 1 级

BADGES = [
    ("first_task", "初次完成", "完成第一个学习任务"),
    ("first_review", "复习起步", "完成第一次复习打卡"),
    ("streak_3", "三日不断", "连续打卡 3 天"),
    ("streak_7", "一周坚持", "连续打卡 7 天"),
    ("streak_30", "月度全勤", "连续打卡 30 天"),
    ("points_100", "百分达人", "累计积分达 100"),
    ("points_500", "积分富翁", "累计积分达 500"),
]


def init_reward_account() -> None:
    """确保单用户账户行存在（id 固定为 1）。"""
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO reward_account (id, points, level, streak) VALUES (1,0,1,0)"
    )
    conn.commit()
    conn.close()


def _award(points: int, event_type: str, ref_id: int | None = None) -> None:
    """写入一条积分流水并累加账户积分。"""
    conn = get_conn()
    conn.execute(
        "INSERT INTO reward_event (event_type, points, ref_id) VALUES (?,?,?)",
        (event_type, points, ref_id),
    )
    conn.execute(
        "UPDATE reward_account SET points=points+?, updated_at=datetime('now') WHERE id=1",
        (points,),
    )
    conn.commit()
    conn.close()


def add_reward_event(points: int, event_type: str, ref_id: int | None = None) -> dict:
    """统一加分入口（路由钩子与外部调用），返回最新账户状态。"""
    init_reward_account()
    _award(points, event_type, ref_id)
    return get_reward_state()


def get_study_task(task_id: int) -> dict | None:
    """取单个备考任务（奖励钩子用来判断 source 是否为 'review'）。"""
    conn = get_conn()
    row = conn.execute("SELECT * FROM study_task WHERE id=?", (task_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def checkin_today() -> dict:
    """每日打卡：+REWARD_CHECKIN 积分，并按昨天是否打卡更新连续天数 streak。"""
    from datetime import datetime, timedelta

    init_reward_account()
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_conn()
    existing = conn.execute("SELECT id FROM reward_checkin WHERE date=?", (today,)).fetchone()
    if existing:
        conn.close()
        return {"ok": False, "already": True, "state": get_reward_state()}
    acc = conn.execute("SELECT streak, last_checkin FROM reward_account WHERE id=1").fetchone()
    streak = acc["streak"] if acc else 0
    last = acc["last_checkin"] if acc else None
    yest = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    streak = streak + 1 if last == yest else 1
    conn.execute("INSERT INTO reward_checkin (date, points) VALUES (?,?)", (today, REWARD_CHECKIN))
    conn.execute(
        "UPDATE reward_account SET streak=?, last_checkin=?, points=points+?, updated_at=datetime('now') WHERE id=1",
        (streak, today, REWARD_CHECKIN),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "streak": streak, "state": get_reward_state()}


def get_reward_state() -> dict:
    """返回账户全景：积分/等级/经验/连续打卡/已得徽章/打卡总数。"""
    init_reward_account()
    conn = get_conn()
    acc = conn.execute("SELECT * FROM reward_account WHERE id=1").fetchone()
    earned_rows = conn.execute(
        "SELECT badge_key, badge_name, earned_at FROM reward_badge ORDER BY id"
    ).fetchall()
    earned_map = {r["badge_key"]: r["earned_at"] for r in earned_rows}
    # 徽章墙：完整 7 枚定义 + 是否已得（前端据此高亮/灰显）
    all_badges = [
        {
            "badge_key": key,
            "badge_name": name,
            "description": desc,
            "earned": key in earned_map,
            "earned_at": earned_map.get(key),
        }
        for (key, name, desc) in BADGES
    ]
    checkin_total = conn.execute("SELECT COUNT(*) c FROM reward_checkin").fetchone()["c"]
    conn.close()
    acc = dict(acc)
    points = acc["points"]
    return {
        "points": points,
        "level": points // LEVEL_STEP + 1,
        "exp": points % LEVEL_STEP,
        "exp_need": LEVEL_STEP,
        "streak": acc["streak"],
        "last_checkin": acc["last_checkin"],
        "badges": [dict(b) for b in earned_rows],
        "all_badges": all_badges,
        "checkin_total": checkin_total,
    }


def grant_badge(badge_key: str, badge_name: str) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO reward_badge (badge_key, badge_name) VALUES (?,?)",
        (badge_key, badge_name),
    )
    conn.commit()
    conn.close()


def list_badges() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM reward_badge ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def evaluate_badges() -> list[str]:
    """根据账户状态自动授予应得徽章，返回本次新授予的 badge_key 列表。"""
    state = get_reward_state()
    conn = get_conn()
    task_done = conn.execute(
        "SELECT COUNT(*) c FROM reward_event WHERE event_type='task_done'"
    ).fetchone()["c"]
    review_done = conn.execute(
        "SELECT COUNT(*) c FROM reward_event WHERE event_type='review_done'"
    ).fetchone()["c"]
    conn.close()
    earned = {b["badge_key"] for b in state["badges"]}
    streak = state["streak"]
    points = state["points"]
    new_badges: list[str] = []

    def try_grant(key: str, name: str, cond: bool) -> None:
        if cond and key not in earned:
            grant_badge(key, name)
            new_badges.append(key)

    for key, name, _desc in BADGES:
        cond = {
            "first_task": task_done >= 1,
            "first_review": review_done >= 1,
            "streak_3": streak >= 3,
            "streak_7": streak >= 7,
            "streak_30": streak >= 30,
            "points_100": points >= 100,
            "points_500": points >= 500,
        }.get(key, False)
        try_grant(key, name, cond)
    return new_badges


def list_videos() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM reward_video ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def insert_video(title: str, path: str, period_start: str, period_end: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO reward_video (title, path, period_start, period_end) VALUES (?,?,?,?)",
        (title, path, period_start, period_end),
    )
    vid = cur.lastrowid
    conn.commit()
    conn.close()
    return vid


def get_video(vid: int) -> dict | None:
    """按 id 取一条复盘视频记录（供静态文件路由定位文件路径）。"""
    conn = get_conn()
    row = conn.execute("SELECT * FROM reward_video WHERE id=?", (vid,)).fetchone()
    conn.close()
    return dict(row) if row else None

