"""本地只读报告 UI：仅监听回环地址，使用本地资源，不持久化状态。"""

from modou.ui.server import ReportLoadError, load_report, run_ui

__all__ = ["ReportLoadError", "load_report", "run_ui"]
