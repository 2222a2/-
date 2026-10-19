"""M7 专注计时 端到端联调：start → 计时 → stop → 周报聚合，并顺带验证 OO 部署诊断接口。

运行前提：后端已在 8000 启动（BACKEND_PUBLIC_URL=http://localhost:8000）。
本脚本：起在 backend/ 目录下，sqlite 连 data/app.db，跑完自动清理测试 session。
"""
import time
import sqlite3
import httpx

BASE = "http://localhost:8000"


def check(name, cond, extra=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}")


def main():
    # 取一个真实 task id 用于关联专注
    r = httpx.get(f"{BASE}/api/tasks")
    tasks = r.json()
    task_id = tasks[0]["id"] if tasks else None
    print(f"任务总数: {len(tasks)}，取 task_id={task_id}")

    # 1) 无任务专注
    r = httpx.post(f"{BASE}/api/focus/start", json={})
    sid1 = r.json()["id"]
    check("start(无task) 返回 session_id", isinstance(sid1, int) and sid1 > 0, f"id={sid1}")
    time.sleep(3)

    # 2) active 应能看到进行中的会话
    r = httpx.get(f"{BASE}/api/focus/active")
    active = r.json()["session"]
    check("active 返回进行中会话", bool(active) and active["id"] == sid1, f"active={active}")

    # 3) 停止 sid1
    r = httpx.post(f"{BASE}/api/focus/stop", json={"session_id": sid1})
    dur1 = r.json().get("duration", 0)
    check("stop 计算时长≈3s", dur1 >= 2, f"duration={dur1}")

    # 4) stop 后 active 应为空
    r = httpx.get(f"{BASE}/api/focus/active")
    check("stop 后 active 为空", r.json()["session"] is None)

    # 5) 带任务专注
    sid2 = httpx.post(f"{BASE}/api/focus/start", json={"task_id": task_id}).json()["id"]
    time.sleep(2)
    r = httpx.post(f"{BASE}/api/focus/stop", json={"session_id": sid2})
    dur2 = r.json().get("duration", 0)
    check("带task stop 时长≈2s", dur2 >= 1, f"duration={dur2}")

    # 6) 周报 focus_seconds 应 > 0（专注工时自动喂周报）
    r = httpx.get(f"{BASE}/api/reports/weekly")
    rep = r.json()
    check("周报 focus_seconds > 0", rep["focus_seconds"] > 0, f"focus_seconds={rep['focus_seconds']}")

    # 7) history 含本次两条
    r = httpx.get(f"{BASE}/api/focus/history")
    hist = r.json()
    hit = [h for h in hist if h["id"] in (sid1, sid2)]
    check("history 含本次两条", len(hit) == 2, f"hit={len(hit)}")

    # 8) OO 部署诊断接口
    r = httpx.get(f"{BASE}/api/docs/oo-status")
    st = r.json()
    ok = ("editor_server_url_for_browser" in st
          and "backend_public_url_for_onlyoffice" in st
          and "onlyoffice_reachable" in st
          and "warnings" in st)
    check("oo-status 返回双视角地址+告警", ok)
    print("  oo-status 摘要:", {
        "editor(browser)": st.get("editor_server_url_for_browser"),
        "backend(oo_view)": st.get("backend_public_url_for_onlyoffice"),
        "reachable": st.get("onlyoffice_reachable"),
        "warnings": st.get("warnings"),
    })

    # 清理测试数据
    conn = sqlite3.connect("data/app.db")
    conn.execute("DELETE FROM focus_session WHERE id IN (?,?)", (sid1, sid2))
    conn.commit()
    conn.close()
    print(f"已清理测试 session {sid1}, {sid2}；周报 focus_seconds 已回 0")


if __name__ == "__main__":
    main()
