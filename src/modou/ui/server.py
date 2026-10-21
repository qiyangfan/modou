"""校验并加载报告，通过本机 HTTP 端点提供报告数据和前端静态资源。"""

from __future__ import annotations

import json
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# 支持的报告类型与格式版本。
SUPPORTED_REPORTS: dict[str, int] = {
    "verify": 1,
    "optimize": 1,
    "lint": 1,
    "patrol_drift": 1,
    "patrol_unused_indexes": 1,
    "patrol_slowlog": 1,
    "patrol_summary": 1,
}

# 只允许绑定回环地址。
_LOOPBACK_BINDS = {"127.0.0.1", "localhost"}


class ReportLoadError(Exception):
    """报告不可读/类型或版本不受支持（输入错误，退出码 2）。"""

    def __init__(self, reason: str) -> None:
        supported = ", ".join(f"{kind} v{version}" for kind, version in sorted(SUPPORTED_REPORTS.items()))
        super().__init__(f"{reason} (supported reports: {supported})")


class UiBindError(Exception):
    """非回环绑定被拒绝；报告含 schema 元数据，只能在本机访问。"""


@dataclass
class LoadedReport:
    id: str
    kind: str
    version: int
    source: str
    data: dict


def load_report(path: Path) -> LoadedReport:
    """加载并校验报告；verify v1 无 report_kind，按 summary 形状识别。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReportLoadError(f"cannot read report {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ReportLoadError(f"report {path} is not a JSON object")
    kind = raw.get("report_kind")
    if kind is None:
        # verify v1 没有 report_kind，按 summary 形状识别。
        summary = raw.get("summary")
        if isinstance(summary, dict) and "missing_execution" in summary and raw.get("report_version") == 1:
            kind = "verify"
    if not isinstance(kind, str) or kind not in SUPPORTED_REPORTS:
        raise ReportLoadError(f"unknown report kind {kind!r} in {path}")
    version = raw.get("report_version")
    # bool 是 int 子类，1.0 == 1；版本必须是真整数
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
                # 阻止 DNS rebinding 读取本机报告。
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
                # 先解码报告 ID 再匹配。
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
            # 只允许读取静态资源目录内的文件。
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
            pass  # 不输出访问日志。

    server = ThreadingHTTPServer((bind, port), Handler)
    server.daemon_threads = True  # 请求线程不阻塞进程退出。
    threading.Thread(target=server.serve_forever, daemon=True, name="modou-ui-http").start()
    if open_browser:
        # CLI 也会输出服务地址。
        webbrowser.open(f"http://127.0.0.1:{server.server_address[1]}")
    return server, reports
