# OnlyOffice 部署与回存 · 避坑指南

> 适用范围：本项目 M1 文档中心（OnlyOffice 嵌入 + AI 生成真实 Office + 版本管理）。
> 本文专治 OnlyOffice 部署最常见的两类故障：**编辑器打不开** 和 **保存后不回存**。

---

## 一、一句话核心：两个"地址视角"必须分开

OnlyOffice（以下简称 OO）在整个链路里被 **三个不同角色** 从不同地址访问，这三个地址常常不是同一个，混为一谈就是所有坑的根源：

| 地址配置 | 给谁用 | 视角 | 错了会怎样 |
|---|---|---|---|
| `ONLYOFFICE_URL` | **后端**访问 OO 服务（健康检查 `/healthcheck`、能力探测） | 后端 → OO | 后端探活失败 |
| `ONLYOFFICE_PUBLIC_URL` | **前端浏览器**加载 OO 编辑器脚本（`documentServerUrl`） | 浏览器 → OO | 编辑器打不开 / 白屏 |
| `BACKEND_PUBLIC_URL` | **OO 服务端**回源拉文件 + 保存回调后端 | OO 容器 → 后端 | 保存不回存 / 打不开文件 |

代码里（`onlyoffice.py` / `docs.py`）已经把后两个彻底分离：
- `ONLYOFFICE_PUBLIC_URL` → 进 `editorConfig` 的 `onlyofficeUrl`（给前端）；
- `BACKEND_PUBLIC_URL` → 拼 `file_url` 和 `callback_url`（给 OO 服务端）。

---

## 二、最经典的四个坑

### 坑 A：把"后端怎么访问 OO"当成了"前端怎么访问 OO"
OO 在 Docker 里，后端用 `http://onlyoffice:80` 能访问，但**浏览器**访问不到容器名 `onlyoffice`。
→ 前端要的是 **浏览器能打开** 的地址：本机开发 `http://localhost:8080`，或 Docker 把 8080 映射到的宿主机端口 / 局域网 IP。这就是 `ONLYOFFICE_PUBLIC_URL` 存在的意义。

### 坑 B：OO 在 Docker，回调还在用 `localhost:8000`
`BACKEND_PUBLIC_URL=http://localhost:8000` 时，OO 容器收到回调地址是 `localhost:8000`，它访问的是**自己的 localhost**，不是宿主机的后端 → 回存永远失败。
→ OO 在 Docker 里时，`BACKEND_PUBLIC_URL` 必须设为 `http://host.docker.internal:8000` 或电脑**局域网 IP:8000`（见第三节）。

### 坑 C：Linux 上 Docker 不认识 `host.docker.internal`
Mac/Win 的 Docker 默认能解析 `host.docker.internal`；**Linux 不行**，OO 容器解析不到宿主机。
→ `docker-compose.yml` 已加 `extra_hosts: - "host.docker.internal:host-gateway"`，把宿主机暴露给 OO 容器。

### 坑 D：OO 拒绝非 localhost/非 https 的回调
OO 出于安全，对回调地址有要求。本项目 MVP 关掉了 JWT（`JWT_ENABLED=false`），同机/局域网调试通常可直接回调；若以后开启 JWT，需在 `build_editor_config` 里带上 `token` 或配置 OO 的 `rejectUnauthorized=false`。

---

## 三、推荐部署（docker-compose 已就绪）

`docker-compose.yml` 已包含 onlyoffice 服务 + `extra_hosts`。启动方式分两步：

**1）起 OnlyOffice（Docker）**
```bash
docker compose up -d onlyoffice
# 端口映射 8080:80，浏览器访问 http://localhost:8080 应能看到文档服务
```

**2）起后端（关键：设对两个 PUBLIC_URL）**
```bash
cd backend
# 本机同机开发（浏览器和后端都在本机，OO 也映射到本机 8080）
BACKEND_PUBLIC_URL=http://localhost:8000 \
ONLYOFFICE_PUBLIC_URL=http://localhost:8080 \
.venv2/Scripts/python.exe -m uvicorn app.main:app --port 8000

# OO 在 Docker 里、后端也在本机时的正确写法
BACKEND_PUBLIC_URL=http://host.docker.internal:8000 \
ONLYOFFICE_PUBLIC_URL=http://localhost:8080 \
.venv2/Scripts/python.exe -m uvicorn app.main:app --port 8000
```

> 前端 Vite 走 `/api` 代理到后端 8000，无需额外配置。

---

## 四、自检命令（三步定位问题）

```bash
# 1) OO 服务本身活着吗？（返回 true 即正常）
curl -s http://localhost:8080/healthcheck

# 2) 本项目的 OO 部署体检（一眼看清三个地址配得对不对、OO 是否可达）
curl -s http://localhost:8000/api/docs/oo-status | python -m json.tool
# 正常应能看到 editor_server_url_for_browser / backend_public_url_for_onlyoffice /
# onlyoffice_reachable=true / warnings=[]；若有坑，warnings 会直接告诉你。

# 3) 保存后回存成功吗？（在 OO 里改一字点保存，后端日志应出现）
# [docs] 文档 N 回存成功，当前版本 vM
```

---

## 五、故障排查表

| 现象 | 最可能原因 | 解决 |
|---|---|---|
| 编辑器区域白屏 / 一直"加载中" | `ONLYOFFICE_PUBLIC_URL` 浏览器访问不到 | 改成 `http://localhost:8080`（本机）或宿主机 IP:8080 |
| 打开文档报"下载失败" | `BACKEND_PUBLIC_URL` 拼的 file_url OO 拉不到 | 改成 `host.docker.internal:8000` 或局域网 IP |
| 编辑后保存、但本地文件没变 | 回调地址 OO 打不到后端 | 同上；并检查 `oo-status` 的 warnings |
| 保存时 OO 报 1000/回调错误 | JWT 未配或 `rejectUnauthorized` | MVP 关 `JWT_ENABLED=false`；生产配 token |
| `oo-status` 返回 reachable=false | OO 容器没起 / 地址错 | `docker compose ps` + `curl /healthcheck` |
| Linux 下 OO 回源超时 | 不认识 host.docker.internal | 确认 compose 的 `extra_hosts` 已生效 |

---

## 六、小结

记住一条：**OO 不是"一个服务一个地址"，而是"三个角色三个地址"**——浏览器看 `ONLYOFFICE_PUBLIC_URL`，OO 服务端看 `BACKEND_PUBLIC_URL`，后端自己看 `ONLYOFFICE_URL`。把这三处设对，编辑器打开、保存回存、版本快照三件事自然就通了。项目里的 `/api/docs/oo-status` 就是这个判断的自动化版，部署完先打一下它再验收。
