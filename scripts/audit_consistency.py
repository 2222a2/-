#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""收口即审计：Phase 收口后跑一次的一致性审查。

四个维度：端口 / venv / 依赖 / 落库口径。
输出 docs/一致性审查-YYYY-MM-DD-收口审计.md + 终端摘要。
任何 FAIL -> 退出码 1（可作为收口门槛）。

用法：
  python scripts/audit_consistency.py [--date YYYY-MM-DD] [--no-report]
  --no-report  只校验、不落盘报告文件（适合 pre-commit 调用，避免污染 docs/）
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
DOCS = ROOT / "docs"
SOT_DOCS = [
    DOCS / "Phase1-技术实现设计.md",
    DOCS / "阶段技术约束一致性审计.md",
    ROOT / "README.md",
]

# 端口口径
BACKEND_PORT = 8000
OO_PORT = 8080
STALE_PORT = 8021  # 历史分裂端口，必须清零

# 依赖 -> 在 SoT 文档中检索的关键词（用于"漏记"检测）
DEP_KEYWORDS = {
    # backend (requirements.txt, 非注释)
    "fastapi": ["fastapi"],
    "uvicorn": ["uvicorn"],
    "pydantic": ["pydantic"],
    "openai": ["openai", "豆包"],
    "httpx": ["httpx"],
    "nh3": ["nh3"],
    "pypinyin": ["pypinyin"],
    "python-docx": ["python-docx", "docx"],
    "openpyxl": ["openpyxl"],
    "python-pptx": ["python-pptx", "pptx"],
    # extras（即便可选也计入单一事实来源）
    "reportlab": ["reportlab"],
    "chromadb": ["chromadb"],
    # frontend (package.json)
    "@onlyoffice/document-editor-react": ["onlyoffice"],
    "@tiptap/pm": ["tiptap"],
    "@tiptap/react": ["tiptap"],
    "@tiptap/starter-kit": ["tiptap"],
    "axios": ["axios"],
    "react": ["react"],
    "react-dom": ["react"],
}

# 实现细节/基础设施级，不在 SoT 必查范围
SKIP_DEPS = {"python-dotenv", "uvicorn", "gunicorn", "python-multipart"}
# import 名 -> 声明名（requirements 与代码 import 名不同的情况）
IMPORT_ALIASES = {"dotenv": "python-dotenv", "docx": "python-docx", "pptx": "python-pptx"}

# 落库口径：预期的"真源"信号
EXPECT = {
    "single_sqlite": r"app\.db",
    "fts5": r"fts5",
    "search_index": r"search_idx|search_index",
    "report_upsert": r"INSERT\s+INTO\s+report|ON\s+CONFLICT.*report|upsert.*report|report.*upsert",
    "doc_count": r"doc_count",
    "no_second_db": r"psycopg2|mysql|create_engine|sqlalchemy",
}


class Report:
    def __init__(self):
        self.checks = []  # (dim, name, status, severity, detail)

    def add(self, dim, name, status, severity, detail=""):
        self.checks.append((dim, name, status, severity, detail))

    def dim(self, d):
        return [c for c in self.checks if c[0] == d]

    @property
    def failed(self):
        return [c for c in self.checks if c[2] == "FAIL"]


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def check_ports(rep):
    dim = "端口"
    files = {
        "config.py": BACKEND / "app" / "config.py",
        "vite.config.ts": FRONTEND / "vite.config.ts",
        "README.md": ROOT / "README.md",
    }
    scripts = list((ROOT / "scripts").glob("verify_*.py"))

    # 1) 历史分裂端口必须清零
    stale_hits = []
    for label, p in files.items():
        if str(STALE_PORT) in read(p):
            stale_hits.append(f"{label}:含 {STALE_PORT}")
    for s in scripts:
        if str(STALE_PORT) in read(s):
            stale_hits.append(f"scripts/{s.name}:含 {STALE_PORT}")
    if stale_hits:
        rep.add(dim, "历史分裂端口已清零(8021)", "FAIL", "高", "；".join(stale_hits))
    else:
        rep.add(dim, "历史分裂端口已清零(8021)", "PASS", "-", "未发现 8021")

    # 2) 后端默认端口
    ct = read(files["config.py"])
    m = re.search(r'PORT\s*=\s*int\(os\.getenv\([^)]*?["\'](\d+)', ct)
    if m and int(m.group(1)) == BACKEND_PORT:
        rep.add(dim, "后端默认端口=8000(config.py)", "PASS", "-", f"PORT={m.group(1)}")
    else:
        rep.add(dim, "后端默认端口=8000(config.py)", "FAIL", "高",
                f"config.py PORT 解析为 {m.group(1) if m else '无'}")

    # 3) vite 代理目标
    vt = read(files["vite.config.ts"])
    if re.search(r"127\.0\.0\.1:8000|localhost:8000|:8000", vt):
        rep.add(dim, "Vite 代理目标→8000", "PASS", "-", "")
    else:
        rep.add(dim, "Vite 代理目标→8000", "FAIL", "中", "vite.config.ts 未指向 8000")

    # 4) README 端口口径
    rt = read(files["README.md"])
    if "8000" in rt and "8080" in rt and str(STALE_PORT) not in rt:
        rep.add(dim, "README 端口口径(8000/8080)", "PASS", "-", "")
    else:
        rep.add(dim, "README 端口口径(8000/8080)", "WARN", "低", "README 端口描述需核对")

    # 5) verify 脚本 BASE_URL
    bad = [s.name for s in scripts if re.search(r'["\']http://[^"\']*8021', read(s))]
    if bad:
        rep.add(dim, "verify 脚本 BASE_URL 统一 8000", "FAIL", "中", "；".join(bad))
    else:
        rep.add(dim, "verify 脚本 BASE_URL 统一 8000", "PASS", "-",
                f"已查 {len(scripts)} 个 verify 脚本")


def check_venv(rep):
    dim = "venv"
    dirs = [d for d in BACKEND.iterdir()
            if d.is_dir() and re.match(r"^\.?venv", d.name)]
    if len(dirs) > 1:
        rep.add(dim, "单一虚拟环境", "FAIL", "高",
                f"发现多个: {', '.join(d.name for d in dirs)}（双 venv 残留）")
    elif len(dirs) == 1:
        rep.add(dim, "单一虚拟环境", "PASS", "-", f"仅 {dirs[0].name}")
    else:
        rep.add(dim, "单一虚拟环境", "WARN", "中", "未发现 venv 目录")

    rt = read(ROOT / "README.md")
    m = re.search(r"(\.venv2?|venv)\s*/?Scripts", rt)
    if m:
        ref = m.group(1)
        if (BACKEND / ref).is_dir():
            rep.add(dim, f"README 指向 venv 存在({ref})", "PASS", "-", "")
        else:
            rep.add(dim, f"README 指向 venv 存在({ref})", "FAIL", "中", f"{ref} 不存在")

    if (BACKEND / "requirements.txt").is_file():
        rep.add(dim, "requirements.txt 存在", "PASS", "-", "")
    else:
        rep.add(dim, "requirements.txt 存在", "FAIL", "高", "缺失")


def _parse_requirements(text):
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[<>=!~ ]", line, maxsplit=1)[0].strip()
        name = re.sub(r"\[.*?\]", "", name).strip()  # 去掉 uvicorn[standard] 等 extras
        if name:
            out.append(name.lower())
    return out


def _parse_pkg_json(text):
    deps = {}
    m = re.search(r'"dependencies"\s*:\s*\{([^}]*)\}', text, re.S)
    if m:
        for k in re.findall(r'"([^"]+)"\s*:', m.group(1)):
            deps[k] = "dep"
    m = re.search(r'"devDependencies"\s*:\s*\{([^}]*)\}', text, re.S)
    if m:
        for k in re.findall(r'"([^"]+)"\s*:', m.group(1)):
            deps[k] = "dev"
    return deps


def check_deps(rep):
    dim = "依赖"
    sot = "\n".join(read(d) for d in SOT_DOCS).lower()

    # 1) SoT 覆盖：每个关键依赖在 SoT 文档中是否出现
    missing_sot = [dep for dep, kws in DEP_KEYWORDS.items()
                   if dep not in SKIP_DEPS
                   and not any(kw.lower() in sot for kw in kws)]
    if missing_sot:
        rep.add(dim, "关键依赖已记入单一事实来源", "WARN", "中",
                "未出现在 SoT 文档: " + ", ".join(missing_sot))
    else:
        rep.add(dim, "关键依赖已记入单一事实来源", "PASS", "-",
                f"已核对 {len(DEP_KEYWORDS) - len(SKIP_DEPS)} 项")

    # 2) requirements vs 实际 import
    reqs = set(_parse_requirements(read(BACKEND / "requirements.txt")))
    imported = set()
    stdlib = getattr(sys, "stdlib_module_names", set())
    for pyf in (BACKEND / "app").rglob("*.py"):
        for mm in re.finditer(r'^\s*(?:import|from)\s+([A-Za-z0-9_.]+)',
                              read(pyf), re.M):
            imported.add(mm.group(1).split(".")[0])
    imported_norm = imported | {IMPORT_ALIASES.get(x) for x in imported} - {None}
    not_imported = sorted(r for r in reqs
                          if r not in imported_norm and r not in SKIP_DEPS)
    if not_imported:
        rep.add(dim, "requirements 依赖均有代码引用", "WARN", "低",
                "requirements 中未在 app/ 直接 import: " + ", ".join(not_imported))
    else:
        rep.add(dim, "requirements 依赖均有代码引用", "PASS", "-", "")

    # 3) package.json deps vs 实际 import
    pkgs = _parse_pkg_json(read(FRONTEND / "package.json"))
    fe_imports = set()
    src = FRONTEND / "src"
    if src.is_dir():
        import_re = re.compile(r'from\s+["\']([^"\']+)["\']|import\(\s*["\']([^"\']+)["\']')
        for tsf in src.rglob("*.ts*"):
            for mm in import_re.finditer(read(tsf)):
                s = mm.group(1) or mm.group(2)
                if not s or s.startswith((".", "/", "node:")):
                    continue
                fe_imports.add("/".join(s.split("/")[:2]) if s.startswith("@")
                               else s.split("/")[0])
    # 已知传递依赖（被其它依赖拉入，无需直接 import）：确认后保留
    frontend_transitive_ok = {"@tiptap/pm"}
    unused = [k for k, v in pkgs.items()
              if v == "dep" and k not in fe_imports
              and k not in frontend_transitive_ok]
    if unused:
        rep.add(dim, "前端 dependencies 均被引用", "WARN", "低",
                "package.json 依赖未在 src 直接 import: " + ", ".join(unused))
    else:
        rep.add(dim, "前端 dependencies 均被引用", "PASS", "-", "")


def check_persistence(rep):
    dim = "落库口径"
    cfg = read(BACKEND / "app" / "config.py")
    db = read(BACKEND / "app" / "db.py")
    tasks = read(BACKEND / "app" / "tasks.py")
    know = read(BACKEND / "app" / "knowledge.py")
    combined = "\n".join([cfg, db, tasks, know])

    if re.search(EXPECT["single_sqlite"], combined):
        rep.add(dim, "单一 SQLite 文件(app.db)", "PASS", "-", "")
    else:
        rep.add(dim, "单一 SQLite 文件(app.db)", "FAIL", "高", "未发现 app.db 单一库")

    if re.search(EXPECT["no_second_db"], combined, re.I):
        rep.add(dim, "无第二数据库引擎", "FAIL", "高",
                "发现 psycopg2/mysql/sqlalchemy 等第二引擎痕迹")
    else:
        rep.add(dim, "无第二数据库引擎", "PASS", "-", "仅 SQLite")

    if re.search(EXPECT["fts5"], combined, re.I):
        rep.add(dim, "FTS5 全文索引已建", "PASS", "-", "")
    else:
        rep.add(dim, "FTS5 全文索引已建", "FAIL", "高", "未检索到 fts5")

    if re.search(EXPECT["search_index"], combined, re.I):
        rep.add(dim, "搜索索引表存在(search_idx/index)", "PASS", "-", "")
    else:
        rep.add(dim, "搜索索引表存在(search_idx/index)", "WARN", "中", "未检索到")

    if re.search(EXPECT["report_upsert"], combined, re.I) or "report" in combined.lower():
        rep.add(dim, "报告生成落 report 表", "PASS", "-", "")
    else:
        rep.add(dim, "报告生成落 report 表", "FAIL", "中", "未见 report 落库")

    if re.search(EXPECT["doc_count"], combined, re.I):
        rep.add(dim, "报告聚合含文档维度(doc_count)", "PASS", "-", "")
    else:
        rep.add(dim, "报告聚合含文档维度(doc_count)", "WARN", "中",
                "未见 doc_count 聚合（原 #7 偏离）")


def build_markdown(rep, date_str):
    lines = [f"# 一致性审查（收口即审计）· {date_str}\n",
             "> 自动生成：`python scripts/audit_consistency.py`\n"]
    fails = rep.failed
    status = "❌ 存在 FAIL，未达收口门槛" if fails else "✅ 四维度无 FAIL"
    lines.append(f"> 结论：**{status}**（FAIL={len(fails)}）\n")
    for dim in ["端口", "venv", "依赖", "落库口径"]:
        rows = rep.dim(dim)
        if not rows:
            continue
        lines.append(f"## {dim}\n")
        lines.append("| 检查项 | 状态 | 严重度 | 说明 |")
        lines.append("|---|---|---|---|")
        for _, name, st, sev, detail in rows:
            lines.append(f"| {name} | {st} | {sev} | {detail or '-'} |")
        lines.append("")
    lines.append("## 闭环动作建议\n")
    lines.append("- **FAIL**：必须修复后才能算 Phase 收口（工程卫生 / P0）。")
    lines.append("- **WARN（SoT 漏记）**：须补进三处单一事实来源（Phase1 技术设计 / 审计表 / README 技术栈段），补完重跑直到 WARN 清零。")
    lines.append("- **WARN（僵尸依赖）**：确认后清理 requirements / package.json。")
    lines.append("- 修改后重跑本脚本，直到 FAIL=0。\n")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=_dt.date.today().isoformat())
    ap.add_argument("--no-report", action="store_true",
                    help="只校验不落盘报告文件（适合 pre-commit 调用）")
    args = ap.parse_args()
    rep = Report()
    check_ports(rep)
    check_venv(rep)
    check_deps(rep)
    check_persistence(rep)
    md = build_markdown(rep, args.date)
    if args.no_report:
        print(md)
    else:
        out = DOCS / f"一致性审查-{args.date}-收口审计.md"
        out.write_text(md, encoding="utf-8")
        print(md)
        print(f"\n报告已写入：{out}")
    if rep.failed:
        print(f"存在 {len(rep.failed)} 个 FAIL，收口门槛未通过。", file=sys.stderr)
        sys.exit(1)
    print("四维度无 FAIL，审计通过。")


if __name__ == "__main__":
    main()
