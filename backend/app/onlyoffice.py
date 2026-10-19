"""OnlyOffice 编辑器配置生成。

逻辑：前端要嵌入 OnlyOffice 编辑器时，后端先算好一份 config（文档地址、回调地址、权限），
OnlyOffice Docs 服务据此打开/编辑文件；用户编辑后，OnlyOffice 通过 callbackUrl 把文件回存到我们本地。

M1 阶段把 config 从骨架升级为“真实可回存”：
- 补上 document.key：OO 靠 key 区分不同文档/版本，编辑后回写时靠它定位会话；
  改版本时必须换 key（否则 OO 会命中缓存，打开的还是旧文件）。
- 补上 document.permissions.edit：明确允许在线编辑（MVP 关了 JWT，这里直接放开）。
"""
from .config import ONLYOFFICE_URL, ONLYOFFICE_PUBLIC_URL

# 文件类型 -> OnlyOffice documentType 映射
_DOC_TYPE_MAP = {
    "docx": "word",
    "doc": "word",
    "xlsx": "cell",
    "pptx": "slide",
    "ppt": "slide",
}


def build_editor_config(
    file_url: str,
    callback_url: str,
    file_type: str = "docx",
    title: str = "document",
    mode: str = "edit",
    user_id: str = "local",
    user_name: str = "郭郭",
    key: str | None = None,
    server_url: str | None = None,
) -> dict:
    """生成 OnlyOffice 编辑器 config。

    key: 文档会话标识，建议传 "{doc_id}-{version}"，每次新版本换值以绕过 OO 缓存。
    server_url: 前端浏览器加载编辑器脚本的 OO 地址（前端视角）。默认用
      ONLYOFFICE_PUBLIC_URL（与后端视角的 ONLYOFFICE_URL 分离）。这正是 OO 部署
      经典坑的落点：浏览器和 OO 服务端看到的“OO 地址”可能不是同一个。
    file_url / callback_url: 必须能被 OO 服务端访问（用 BACKEND_PUBLIC_URL 拼）。
    """
    return {
        "document": {
            "fileType": file_type,
            "title": title,
            "url": file_url,
            # key 缺失时回退为标题哈希，但强烈建议调用方显式传入 doc_id+version
            "key": key or f"doc-{abs(hash(title))}",
            "permissions": {"edit": True, "download": True},
        },
        "documentType": _DOC_TYPE_MAP.get(file_type, "word"),
        "editorConfig": {
            "callbackUrl": callback_url,
            "mode": mode,
            "user": {"id": user_id, "name": user_name},
        },
        "onlyofficeUrl": server_url or ONLYOFFICE_PUBLIC_URL,
    }
