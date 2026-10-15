"""本地薄报告层（v0.4c）：加载报告 JSON 并以回环 HTTP 服务渲染（ADR-0002）。

红线：仅监听回环地址、只读渲染（无编辑/执行）、页面资源全部本地（零外部请求）、
不落任何状态文件。渲染职责之外一概不做——做厚即变成自己反对的平台。
"""

from modou.ui.server import ReportLoadError, load_report, run_ui

__all__ = ["ReportLoadError", "load_report", "run_ui"]
