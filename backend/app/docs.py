"""M1 文档中心：AI 生成真实 Office 文件 + OnlyOffice 回存 + 版本管理。

整体链路（一句话）：
  意图(prompt / 分析产物) → 豆包产出结构化内容(JSON) → python-docx/openpyxl/python-pptx
  渲染成真实文件 → 落 data/docs → 写 Doc 表(含 linked_task_id) → 返回 OnlyOffice 编辑器配置
  → 前端打开编辑器 → 用户编辑 → OnlyOffice 回调把文件回存本地 → 每次保存打版本快照。

为什么这么拆（设计理由）：
- “AI 只管填空，应用层管落盘”：豆包只产出结构化 JSON（标题/章节/段落），
  渲染、落盘、建版本、配回存全是确定性代码。AI 的灵活性被 JSON schema 框死，
  不会出现“模型给你一段 markdown 然后渲染崩了”的不可控情况。
- 文件命名用 doc_id 而非标题：标题会变、会重名，用自增 id 当文件名最稳，
  回滚/删除/回调都能按 id 精确定位，且天然防重名覆盖。
- 当前文件 + 版本快照分离：data/docs/<id>.<ext> 永远是“最新版”，
  每次保存把“这一版”另存为 snapshots/<id>/vN.<ext>，版本链路可追溯、可一键回滚。
- 回存走 OnlyOffice 官方回调协议：编辑后 OO 把文件挂到 responseUrl，我们下载覆盖本地，
  零自己造轮子、和 OO 的编辑/协同能力原生打通。
"""
from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse

from . import db, schemas
from . import config
from .ai.provider import get_provider, MockProvider
from .onlyoffice import build_editor_config


router = APIRouter(prefix="/api/docs", tags=["docs"])

# type -> 文件扩展名 / OnlyOffice fileType / 浏览器 media type
_EXT = {"word": "docx", "excel": "xlsx", "ppt": "pptx"}
_MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _abs(rel: str) -> Path:
    """把相对 DATA_DIR 的路径还原成绝对路径。"""
    return config.DATA_DIR / rel


def _rel(p: Path) -> str:
    """把绝对路径转成相对 DATA_DIR 的字符串，便于入库（可移植）。"""
    return str(p.relative_to(config.DATA_DIR))


def _doc_ext(doc_type: str) -> str:
    return _EXT.get(doc_type, "docx")


def _resolve_doc(doc_id: int, require_file: bool = True) -> dict:
    doc = db.get_doc(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="doc not found")
    if require_file:
        p = _abs(doc["path"])
        if not p.exists():
            raise HTTPException(status_code=404, detail="doc file missing on disk")
    return doc


def _snapshot_dir(doc_id: int) -> Path:
    d = config.DOCS_DIR / "snapshots" / str(doc_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _parse_versions(doc) -> list[dict]:
    raw = doc.get("versions_json")
    try:
        return json.loads(raw) if raw else []
    except (json.JSONDecodeError, TypeError):
        return []


def _append_version(doc_id: int, current_path: Path, note: str) -> list[dict]:
    """把当前文件另存为下一个版本快照，并把版本列表写回 Doc 表。返回新版本列表。"""
    doc = db.get_doc(doc_id)
    versions = _parse_versions(doc)
    version = len(versions) + 1
    ext = current_path.suffix.lstrip(".")
    snap = _snapshot_dir(doc_id) / f"v{version}.{ext}"
    shutil.copyfile(current_path, snap)
    versions.append({
        "version": version,
        "saved_at": _now(),
        "size": current_path.stat().st_size,
        "snapshot_rel": _rel(snap),
        "note": note,
    })
    db.update_doc_versions(doc_id, json.dumps(versions, ensure_ascii=False))
    return versions


# ---------------------------------------------------------------------------
# AI 结构化内容生成（豆包产 JSON；离线用 Mock 兜底，保证链路可跑）
# ---------------------------------------------------------------------------
_SYSTEM_FOR = {
    "word": (
        "你是文档生成助手。根据用户意图产出结构化 JSON（只输出 JSON，不要解释、不要 ```围栏）。"
        "结构：{\"title\":\"文档标题\",\"sections\":[{\"heading\":\"章节标题\","
        "\"paragraphs\":[\"段落文本\"],\"bullets\":[\"要点\"]}]}。"
        "段落要具体、可执行；中文输出。"
    ),
    "excel": (
        "你是表格生成助手。只输出 JSON：{\"title\":\"表名\","
        "\"sheets\":[{\"name\":\"工作表名\",\"headers\":[\"列1\",\"列2\"],"
        "\"rows\":[[\"单元格\",\"单元格\"]]}]}。数据要规整、可落地。"
    ),
    "ppt": (
        "你是演示文稿生成助手。只输出 JSON：{\"title\":\"标题\","
        "\"slides\":[{\"title\":\"页标题\",\"bullets\":[\"要点\"],\"notes\":\"演讲备注\"}]}。"
        "每页要点 3-5 条，逻辑递进。"
    ),
}


def _extract_json(text: str | None) -> dict | None:
    if not text:
        return None
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        text = text[start:end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _build_content(doc_type: str, prompt: str, requirement: dict | None,
                   steps: list | None) -> dict:
    """产出渲染所需的结构化内容。真实模型走豆包，离线走 Mock。"""
    is_mock = isinstance(get_provider(), MockProvider)

    if not is_mock:
        ctx = f"用户意图：{prompt}"
        if requirement:
            ctx += f"\n需求确认卡(JSON)：{json.dumps(requirement, ensure_ascii=False)}"
        if steps:
            ctx += f"\n拆解步骤(JSON)：{json.dumps(steps, ensure_ascii=False)}"
        msg = get_provider().chat([
            {"role": "system", "content": _SYSTEM_FOR[doc_type]},
            {"role": "user", "content": ctx},
        ])
        data = _extract_json(msg.content) or {}
        if data.get("title") and (data.get("sections") or data.get("sheets") or data.get("slides")):
            return data

    # Mock 兜底：尽量利用已有上下文（分析产物 / 周报）造出像样的结构
    return _build_content_mock(doc_type, prompt, requirement, steps)


def _build_content_mock(doc_type: str, prompt: str, requirement: dict | None,
                        steps: list | None) -> dict:
    if doc_type == "word":
        return _mock_word(prompt, requirement, steps)
    if doc_type == "excel":
        return _mock_excel(prompt, requirement, steps)
    return _mock_ppt(prompt, requirement, steps)


def _markdown_to_sections(md: str) -> list[dict]:
    """把周报 Markdown 解析成 word sections（## 当章节，- 当要点，其余当段落）。"""
    sections: list[dict] = []
    cur: dict | None = None
    for line in md.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        if line.startswith("# "):
            continue  # 顶层标题用 content.title
        if line.startswith("## "):
            cur = {"heading": line[3:].strip(), "paragraphs": [], "bullets": []}
            sections.append(cur)
        elif line.startswith("- "):
            (cur or sections.append({"heading": "", "paragraphs": [], "bullets": []})
             or sections[-1])["bullets"].append(line[2:].strip())
        else:
            (cur or sections.append({"heading": "", "paragraphs": [], "bullets": []})
             or sections[-1])["paragraphs"].append(line.strip())
    if not sections:
        sections.append({"heading": "说明", "paragraphs": [md], "bullets": []})
    return sections


def _mock_word(prompt: str, requirement: dict | None, steps: list | None) -> dict:
    if "周报" in prompt or "weekly" in prompt.lower():
        rep = db.generate_weekly_report()
        content = {
            "title": f"工作周报（{rep['period_start']} ~ {rep['period_end']}）",
            "sections": _markdown_to_sections(rep["markdown"]),
        }
        if not content["sections"]:
            content["sections"] = [{"heading": "本周概览", "paragraphs": [rep["markdown"]], "bullets": []}]
        return content

    title = (requirement or {}).get("goal") or prompt or "未命名文档"
    sections = []
    if requirement:
        sec = {"heading": "一、需求概览", "paragraphs": [], "bullets": []}
        for k, label in (("goal", "目标"), ("deliverable", "交付物"),
                         ("deadline", "截止"), ("constraints", "约束"),
                         ("success_criteria", "成功标准")):
            v = requirement.get(k)
            if v and v not in (None, "无", ""):
                sec["bullets"].append(f"{label}：{v}")
        sections.append(sec)
        assumptions = requirement.get("assumptions") or []
        if assumptions:
            sections.append({"heading": "二、关键假设", "paragraphs": [],
                             "bullets": [f"- {a}" if not str(a).startswith("- ") else str(a)
                                         for a in assumptions]})
    if steps:
        step_sec = {"heading": "三、任务拆解", "paragraphs": [], "bullets": [
            f"{s.get('order', i + 1)}. {s.get('desc', '步骤')}"
            f"（预估 {s.get('est_hours', 1)}h"
            f"{'，依赖 ' + ','.join(map(str, s.get('deps', []))) if s.get('deps') else ''}）"
            for i, s in enumerate(steps)
        ]}
        sections.append(step_sec)
    if not sections:
        sections.append({"heading": "正文", "paragraphs": [
            f"本文档由 AI 根据「{prompt}」生成初稿，可在 OnlyOffice 中继续编辑完善。"], "bullets": []})
    return {"title": title, "sections": sections}


def _mock_excel(prompt: str, requirement: dict | None, steps: list | None) -> dict:
    if steps:
        rows = [[s.get("order", i + 1), s.get("desc", ""), s.get("est_hours", 1),
                 ",".join(map(str, s.get("deps", []))),
                 ",".join(s.get("need", [])) + (f" → {s.get('output', '')}" if s.get("output") else "")]
                for i, s in enumerate(steps)]
        return {
            "title": (requirement or {}).get("goal") or prompt or "任务拆解表",
            "sheets": [{"name": "任务拆解", "headers": ["序号", "步骤", "预估工时(h)", "依赖", "需要/产出"],
                        "rows": rows}],
        }
    return {
        "title": prompt or "数据表",
        "sheets": [{"name": "Sheet1", "headers": ["项目", "内容"],
                    "rows": [["主题", prompt or "未命名"], ["生成时间", _now()]]}],
    }


def _mock_ppt(prompt: str, requirement: dict | None, steps: list | None) -> dict:
    slides = []
    if steps:
        for i, s in enumerate(steps):
            slides.append({"title": f"{s.get('order', i + 1)}. {s.get('desc', '步骤')}",
                           "bullets": [f"预估工时：{s.get('est_hours', 1)}h",
                                       f"依赖：{','.join(map(str, s.get('deps', []))) or '无'}",
                                       f"需要：{','.join(s.get('need', [])) or '无'}"],
                           "notes": s.get("output", "")})
    else:
        slides = [
            {"title": "背景与目标", "bullets": [prompt or "介绍主题", "明确本次目标"], "notes": ""},
            {"title": "核心内容", "bullets": ["要点一", "要点二", "要点三"], "notes": ""},
            {"title": "下一步", "bullets": ["行动项", "时间节点"], "notes": ""},
        ]
    return {"title": (requirement or {}).get("goal") or prompt or "演示文稿", "slides": slides}


# ---------------------------------------------------------------------------
# 渲染：结构化内容 → 真实 Office 文件
# ---------------------------------------------------------------------------
def _set_east_asian(run_or_style, font: str = "Microsoft YaHei") -> None:
    """给 run/style 设东亚字体（中文不乱码）。"""
    from docx.oxml.ns import qn
    rpr = run_or_style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        from docx.oxml import OxmlElement
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), font)


def render_docx(content: dict, path: Path) -> None:
    from docx import Document
    from docx.shared import Pt
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Microsoft YaHei"
    normal.font.size = Pt(11)
    _set_east_asian(normal)
    doc.add_heading(content.get("title", "文档"), level=0)
    for sec in content.get("sections", []):
        if sec.get("heading"):
            doc.add_heading(sec["heading"], level=1)
        for p in sec.get("paragraphs", []):
            doc.add_paragraph(p)
        for b in sec.get("bullets", []):
            doc.add_paragraph(str(b), style="List Bullet")
    doc.save(str(path))


def render_xlsx(content: dict, path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = Workbook()
    for i, sh in enumerate(content.get("sheets", [])):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = sh.get("name", f"Sheet{i + 1}")
        headers = sh.get("headers", [])
        ws.append(headers)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="185FA5")
            c.alignment = Alignment(horizontal="center")
        for row in sh.get("rows", []):
            ws.append([str(x) for x in row])
        # 简单自适应列宽
        for col in ws.columns:
            width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
            ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 40)
    wb.save(str(path))


def render_pptx(content: dict, path: Path) -> None:
    from pptx import Presentation
    prs = Presentation()
    # 标题页
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = content.get("title", "演示文稿")
    if len(slide.placeholders) > 1:
        slide.placeholders[1].text = "AI 生成初稿 · 可在 OnlyOffice 中继续编辑"
    for s in content.get("slides", []):
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = s.get("title", "")
        body = slide.placeholders[1]
        body.text = "\n".join(f"• {b}" for b in s.get("bullets", []))
        if s.get("notes"):
            slide.notes_slide.notes_text_frame.text = s["notes"]
    prs.save(str(path))


def render_doc(content: dict, doc_type: str, path: Path) -> None:
    if doc_type == "word":
        render_docx(content, path)
    elif doc_type == "excel":
        render_xlsx(content, path)
    else:
        render_pptx(content, path)


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
@router.post("/generate", response_model=dict)
def generate(payload: schemas.DocsGenerateIn):
    """AI 生成真实 Office 文件并打开到 OnlyOffice。

    链路：意图 → 结构化内容 → 渲染真实文件 → 落盘 → 写 Doc 表 → 返回编辑器配置。
    返回 { doc, editor_config }，前端把 editor_config 直接喂给 DocEditor 即可。
    """
    doc_type = payload.doc_type if payload.doc_type in _EXT else "word"
    ext = _EXT[doc_type]

    content = _build_content(doc_type, payload.prompt, payload.requirement, payload.steps)
    title = payload.title or content.get("title") or f"未命名{payload.doc_type}"

    # 1) 先渲染到临时文件
    tmp = config.DOCS_DIR / f"tmp_{uuid.uuid4().hex}.{ext}"
    config.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    render_doc(content, doc_type, tmp)

    # 2) 入库拿 id（path 先占位，拿到 id 再改名）
    doc_id = db.insert_doc(path="", doc_type=doc_type,
                           linked_task_id=payload.linked_task_id)

    # 3) 用 id 命名最终文件
    final = config.DOCS_DIR / f"{doc_id}.{ext}"
    tmp.replace(final)

    # 4) 打 v1 版本快照
    versions = _append_version(doc_id, final, note="AI 生成")

    # 5) 回填 path
    conn = db.get_conn()
    conn.execute("UPDATE doc SET path=? WHERE id=?", (_rel(final), doc_id))
    conn.commit()
    conn.close()

    doc = db.get_doc(doc_id)
    return {"doc": _doc_view(doc, versions), "editor_config": _editor_config_for(doc, versions)}


@router.get("/oo-status", response_model=dict)
async def oo_status():
    """OnlyOffice 部署体检：返回两个视角的地址 + OO 可达性探针 + 常见坑告警。

    为用户排查“编辑器打不开 / 保存不回存”准备，一眼看清三处地址配得对不对。
    （定义在此处、所有 /{doc_id} 参数路由之前，避免被字面量 'oo-status' 误匹配。）
    """
    from urllib.parse import urljoin

    oo_public = config.ONLYOFFICE_PUBLIC_URL
    backend_public = config.BACKEND_PUBLIC_URL

    reachable = False
    detail = ""
    try:
        async with httpx.AsyncClient(timeout=3.0, follow_redirects=True) as client:
            r = await client.get(urljoin(oo_public.rstrip("/") + "/", "healthcheck"))
            reachable = r.status_code == 200 and r.text.strip().lower() in ("true", "ok")
            detail = f"HTTP {r.status_code}"
    except Exception as e:
        detail = f"unreachable: {e}"

    warnings = []
    if "localhost" in backend_public or "127.0.0.1" in backend_public:
        warnings.append(
            "BACKEND_PUBLIC_URL 仍是 localhost/127.0.0.1：当 OnlyOffice 在 Docker/远程时，"
            "它无法用该地址回源拉文件或回调后端。请设为 http://host.docker.internal:<port> "
            "或电脑局域网 IP:<port>。"
        )
    if "localhost" in oo_public or "127.0.0.1" in oo_public:
        warnings.append(
            "ONLYOFFICE_PUBLIC_URL 仍是 localhost：仅当你的浏览器就在本机、且 OO 端口已映射到"
            "本机时才有效。若 OO 在 Docker/远程，请把它设为浏览器能访问的 OO 地址"
            "（如 http://<宿主机IP>:8080）。"
        )

    return {
        "editor_server_url_for_browser": oo_public,
        "backend_public_url_for_onlyoffice": backend_public,
        "file_url_example": f"{backend_public}/api/docs/file/1",
        "callback_url_example": f"{backend_public}/api/docs/callback/1",
        "onlyoffice_reachable": reachable,
        "reachable_detail": detail,
        "warnings": warnings,
    }


@router.get("", response_model=list)
def list_docs(limit: int = 50):
    """列出全部文档（含版本数与关联任务）。"""
    rows = db.list_docs(limit)
    out = []
    for r in rows:
        vs = _parse_versions(r)
        out.append({**_doc_view(r, vs), "version_count": len(vs)})
    return out


@router.get("/{doc_id}", response_model=dict)
def get_doc(doc_id: int):
    doc = _resolve_doc(doc_id, require_file=False)
    vs = _parse_versions(doc)
    return {"doc": _doc_view(doc, vs), "editor_config": _editor_config_for(doc, vs)}


@router.get("/{doc_id}/versions", response_model=dict)
def get_versions(doc_id: int):
    """版本快照列表（每次保存一条）。"""
    doc = _resolve_doc(doc_id, require_file=False)
    vs = _parse_versions(doc)
    return {"doc_id": doc_id, "versions": vs, "current_version": len(vs)}


@router.get("/file/{doc_id}")
def serve_file(doc_id: int):
    """OnlyOffice 回源拉文件用：返回当前版本文档字节。"""
    doc = _resolve_doc(doc_id, require_file=True)
    p = _abs(doc["path"])
    ext = _doc_ext(doc["type"] or "word")
    return FileResponse(str(p), media_type=_MEDIA[ext], filename=p.name)


@router.post("/{doc_id}/rollback/{version}", response_model=dict)
def rollback(doc_id: int, version: int):
    """回滚到指定版本：把该版本快照复制回当前文件，并作为新版本记录（可追溯）。"""
    doc = _resolve_doc(doc_id, require_file=False)
    vs = _parse_versions(doc)
    target = next((v for v in vs if v["version"] == version), None)
    if not target:
        raise HTTPException(status_code=404, detail="version not found")
    snap = _abs(target["snapshot_rel"])
    if not snap.exists():
        raise HTTPException(status_code=404, detail="snapshot file missing")
    current = _abs(doc["path"])
    shutil.copyfile(snap, current)
    versions = _append_version(doc_id, current, note=f"回滚到 v{version}")
    fresh = db.get_doc(doc_id)
    return {"doc": _doc_view(fresh, versions), "editor_config": _editor_config_for(fresh, versions)}


@router.get("/{doc_id}/export")
def export_doc(doc_id: int, version: int | None = None):
    """导出文档；不传 version 导当前版，传了导对应快照版。"""
    doc = _resolve_doc(doc_id, require_file=False)
    ext = _doc_ext(doc["type"] or "word")
    if version is not None:
        vs = _parse_versions(doc)
        target = next((v for v in vs if v["version"] == version), None)
        if not target:
            raise HTTPException(status_code=404, detail="version not found")
        p = _abs(target["snapshot_rel"])
        if not p.exists():
            raise HTTPException(status_code=404, detail="snapshot file missing")
        return FileResponse(str(p), media_type=_MEDIA[ext], filename=f"{doc_id}_v{version}.{ext}")
    p = _abs(doc["path"])
    if not p.exists():
        raise HTTPException(status_code=404, detail="doc file missing on disk")
    return FileResponse(str(p), media_type=_MEDIA[ext], filename=p.name)


@router.post("/callback/{doc_id}")
async def onlyoffice_callback(doc_id: int, body: dict):
    """OnlyOffice 编辑回存回调（官方协议）。

    OO 在保存时把编辑后的文件挂到 body['url']，并 POST 到这里。
    - status 2/3：有文件可回存 → 下载覆盖本地 + 打新版本快照；
    - 其它状态（1 打开中 / 4 无改动 / 6 开始编辑）：仅确认收到，不写文件。
    必须返回 {"error": 0}，否则 OO 会重试。
    """
    doc = db.get_doc(doc_id)
    if not doc:
        return {"error": 1, "message": "doc not found"}

    status = body.get("status")
    # OnlyOffice 期望收到 {"error":0} 才认为回存成功
    if status not in (2, 3) or not body.get("url"):
        return {"error": 0}

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get(body["url"])
            r.raise_for_status()
            edited = r.content
    except Exception as e:
        # 下载失败不能算成功，返回非 0 让 OO 重试
        return {"error": 1, "message": f"download failed: {e}"}

    current = _abs(doc["path"])
    current.write_bytes(edited)
    versions = _append_version(doc_id, current, note="OnlyOffice 编辑回存")
    print(f"[docs] 文档 {doc_id} 回存成功，当前版本 v{len(versions)}")
    return {"error": 0}


# ---------------------------------------------------------------------------
# 视图 & 编辑器配置
# ---------------------------------------------------------------------------
def _doc_view(doc: dict, versions: list[dict]) -> dict:
    return {
        "id": doc["id"],
        "path": doc["path"],
        "type": doc["type"],
        "linked_task_id": doc["linked_task_id"],
        "versions_json": json.dumps(versions, ensure_ascii=False),
        "created_at": doc.get("created_at"),
        "current_version": len(versions),
    }


def _editor_config_for(doc: dict, versions: list[dict]) -> dict:
    """构造 OnlyOffice 编辑器配置（含真实回调地址 + 按版本换 key 防缓存）。

    关键：两个视角的地址分开拼——
    - file_url / callback_url 用 BACKEND_PUBLIC_URL：这是 OnlyOffice **服务端**回源拉
      文件、回存文件要访问的后端地址，必须能被 OO 容器/机器访问；
    - onlyofficeUrl 用 ONLYOFFICE_PUBLIC_URL：这是**前端浏览器**加载编辑器脚本的 OO
      地址。OO 在 Docker / 远程时，二者往往不同（典型坑就在这）。
    """
    ext = _doc_ext(doc["type"] or "word")
    doc_id = doc["id"]
    version = len(versions)
    file_url = f"{config.BACKEND_PUBLIC_URL}/api/docs/file/{doc_id}"
    callback_url = f"{config.BACKEND_PUBLIC_URL}/api/docs/callback/{doc_id}"
    cfg = build_editor_config(
        file_url=file_url,
        callback_url=callback_url,
        file_type=ext,
        title=Path(doc["path"]).name,
        key=f"{doc_id}-{version}",
        server_url=config.ONLYOFFICE_PUBLIC_URL,
    )
    return cfg


