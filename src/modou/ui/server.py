"""报告加载与回环 HTTP 服务：薄报告层的 Python 侧（渲染在前端产物内完成）。

职责严格限于：读报告文件（kind+version 门禁）、伺服包内静态产物、把已加载的
报告经本机端点交给前端。不解析、不重算、不存储。
"""

from __future__ import annotations

import json
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# 支持的报告类型与版本（未知组合明确报错，向前演进靠版本门禁不靠猜）
SUPPORTED_REPORTS: dict[str, int] = {
    "verify": 1,
    "optimize": 1,
    "lint": 1,
    "patrol_drift": 1,
    "patrol_unused_indexes": 1,
    "patrol_slowlog": 1,
    "patrol_summary": 1,
}

# 回环绑定白名单：仅 IPv4 回环（::1 需要 IPv6 栈与 getfqdn 配合，且浏览器侧地址
# 固定 127.0.0.1，双层不一致说明从未真正支持）
_LOOPBACK_BINDS = {"127.0.0.1", "localhost"}


class ReportLoadError(Exception):
    """报告不可读/类型或版本不受支持（输入错误，退出码 2）。"""

    def __init__(self, reason: str) -> None:
        supported = ", ".join(f"{kind} v{version}" for kind, version in sorted(SUPPORTED_REPORTS.items()))
        super().__init__(f"{reason} (supported reports: {supported})")


class UiBindError(Exception):
    """绑定非回环地址（报告内容含 schema 元数据，回环是数据不出本地的最后一道闸）。"""


@dataclass
class LoadedReport:
    id: str
    kind: str
    version: int
    source: str
    data: dict


def load_report(path: Path) -> LoadedReport:
    """加载单份报告：类型识别（显式 report_kind，verify 走 v1 形状识别）+ 版本门禁。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReportLoadError(f"cannot read report {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ReportLoadError(f"report {path} is not a JSON object")
    kind = raw.get("report_kind")
    if kind is None:
        # verify 报告（v0.1 冻结契约）无 report_kind 字段：按 summary 形状识别
        summary = raw.get("summary")
        if isinstance(summary, dict) and "missing_execution" in summary and raw.get("report_version") == 1:
            kind = "verify"
    if not isinstance(kind, str) or kind not in SUPPORTED_REPORTS:
        raise ReportLoadError(f"unknown report kind {kind!r} in {path}")
    version = raw.get("report_version")
    # bool 是 int 子类、1.0 == 1：版本必须是真整数，两者都不得冒充 v1 门禁通过
    if isinstance(version, bool) or not isinstance(version, int) or version != SUPPORTED_REPORTS[kind]:
        raise ReportLoadError(
            f"unsupported {kind} report version {version!r} in {path} (expected v{SUPPORTED_REPORTS[kind]})"
        )
    return LoadedReport(id=str(path.resolve()), kind=kind, version=int(version), source=path.name, data=raw)


def dist_dir() -> Path:
    """前端构建产物目录：包内 dist（安装态）或仓库 ui/dist（开发态）。"""
    packaged = Path(__file__).resolve().parent / "dist"
    if packaged.is_dir():
        return packaged
    repo = Path(__file__).resolve().parents[3] / "ui" / "dist"
    if repo.is_dir():
        return repo
    raise ReportLoadError("report UI assets not found (built ui/dist missing); rebuild with: cd ui && npm run build")


def run_ui(
    report_paths: list[Path],
    *,
    port: int = 0,
    bind: str = "127.0.0.1",
    open_browser: bool = True,
) -> tuple[ThreadingHTTPServer, list[LoadedReport]]:
    """起回环服务并返回（server, reports）；调用方负责等待中断与收尾。

    同一报告路径重复给出时按解析后路径去重（侧栏不出现重复条目）。
    """
    if bind not in _LOOPBACK_BINDS:
        raise UiBindError(
            f"bind address {bind!r} rejected: the report UI listens on loopback only "
            "(report content contains schema metadata)"
        )
    unique_paths = list(dict.fromkeys(str(Path(p).resolve()) for p in report_paths))
    reports = [load_report(Path(p)) for p in unique_paths]
    assets_dir = dist_dir().resolve()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if not self._host_is_loopback():
                # DNS rebinding：恶意页面可借域名回连 127.0.0.1 读取报告（schema 元数据）
                self.send_error(403)
                return
            if self.path == "/api/reports":
                self._json(
                    {
                        "reports": [
                            {"id": report.id, "kind": report.kind, "version": report.version, "source": report.source}
                            for report in reports
                        ]
                    }
                )
                return
            if self.path.startswith("/api/reports/"):
                # 浏览器对非 ASCII/空格 id 必然百分号编码，先解码再比对
                report_id = urllib.parse.unquote(self.path.removeprefix("/api/reports/"))
                for report in reports:
                    if report.id == report_id:
                        self._json(
                            {
                                "id": report.id,
                                "kind": report.kind,
                                "version": report.version,
                                "source": report.source,
                                "data": report.data,
                            }
                        )
                        return
                self.send_error(404)
                return
            self._serve_static(self.path)

        def _host_is_loopback(self) -> bool:
            host = self.headers.get("Host", "")
            hostname = host.rsplit(":", 1)[0].strip("[]") if host else ""
            return hostname in _LOOPBACK_BINDS

        def _serve_static(self, path: str) -> None:
            relative = "index.html" if path in ("/", "") else path.removeprefix("/")
            target = (assets_dir / relative).resolve()
            # 目录穿越防护：仅伺服包内产物目录（relative_to 含路径边界，前缀兄弟目录放不进来）
            try:
                target.relative_to(assets_dir)
            except ValueError:
                self.send_error(404)
                return
            if not target.is_file():
                self.send_error(404)
                return
            content_type = {
                ".html": "text/html; charset=utf-8",
                ".js": "text/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".svg": "image/svg+xml",
            }.get(target.suffix, "application/octet-stream")
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: object) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass  # 静默访问日志（本地工具，不产生噪音）

    server = ThreadingHTTPServer((bind, port), Handler)
    server.daemon_threads = True  # 请求线程不阻塞进程退出（Ctrl-C 干净退出，退出码 0）
    # 服务线程在 run_ui 内启动：调用方（CLI）只负责等待中断与收尾；测试可直接请求端点
    threading.Thread(target=server.serve_forever, daemon=True, name="modou-ui-http").start()
    if open_browser:
        # lazygit 模式：起服务即开浏览器；失败不影响服务本身（服务地址由 CLI 打印到 stderr）
        webbrowser.open(f"http://127.0.0.1:{server.server_address[1]}")
    return server, reports
