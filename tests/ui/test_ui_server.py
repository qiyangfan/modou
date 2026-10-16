"""薄报告层 Python 侧测试：加载器门禁、回环绑定拒绝、静态伺服边界、端到端冒烟。"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from modou.ui import ReportLoadError, load_report, run_ui
from modou.ui.server import UiBindError


def _write_report(tmp_path: Path, name: str, payload: dict) -> Path:
    f = tmp_path / name
    f.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return f


VERIFY_OK = {
    "report_version": 1,
    "exit_code": 0,
    "summary": {"missing_execution": 0, "wrong_execution": 0, "historical_drift": 0},
    "env_errors": [],
    "databases": {},
}
OPTIMIZE_OK = {"report_kind": "optimize", "report_version": 1, "exit_code": 0, "databases": {}}
LINT_OK = {"report_kind": "lint", "report_version": 1, "exit_code": 0, "summary": {"hits": 0}, "hits": []}
DRIFT_OK = {"report_kind": "patrol_drift", "report_version": 1, "exit_code": 0, "databases": {}}
SUMMARY_OK = {
    "report_kind": "patrol_summary",
    "report_version": 1,
    "exit_code": 1,
    "inputs": {"drift": "drift.json", "unused": None, "slowlog": None},
    "signals": {"drift": {"exit_code": 1, "added": 1, "removed": 0, "changed": 0, "objects": []}},
}


class TestLoadReport:
    def test_verify_shape_detected(self, tmp_path) -> None:
        report = load_report(_write_report(tmp_path, "verify.json", VERIFY_OK))
        assert report.kind == "verify"
        assert report.version == 1

    def test_explicit_kinds(self, tmp_path) -> None:
        for name, payload in (
            ("optimize.json", OPTIMIZE_OK),
            ("lint.json", LINT_OK),
            ("drift.json", DRIFT_OK),
            ("summary.json", SUMMARY_OK),
        ):
            report = load_report(_write_report(tmp_path, name, payload))
            assert report.kind == payload["report_kind"]

    def test_unknown_kind_rejected_listing_supported(self, tmp_path) -> None:
        f = _write_report(tmp_path, "x.json", {"report_kind": "alien", "report_version": 1})
        with pytest.raises(ReportLoadError, match="supported reports"):
            load_report(f)

    def test_wrong_version_rejected(self, tmp_path) -> None:
        f = _write_report(tmp_path, "x.json", {"report_kind": "lint", "report_version": 99})
        with pytest.raises(ReportLoadError, match="version"):
            load_report(f)

    def test_unreadable_rejected(self, tmp_path) -> None:
        with pytest.raises(ReportLoadError, match="cannot read"):
            load_report(tmp_path / "missing.json")

    def test_malformed_json_rejected(self, tmp_path) -> None:
        f = tmp_path / "broken.json"
        f.write_text("{not json", encoding="utf-8")
        with pytest.raises(ReportLoadError, match="cannot read"):
            load_report(f)


class TestBindGuard:
    def test_non_loopback_rejected(self, tmp_path) -> None:
        f = _write_report(tmp_path, "v.json", VERIFY_OK)
        with pytest.raises(UiBindError, match="loopback"):
            run_ui([f], bind="0.0.0.0", open_browser=False)


class TestServerE2E:
    def test_api_and_static_served_loopback_only(self, tmp_path) -> None:
        f = _write_report(tmp_path, "v.json", VERIFY_OK)
        server, _reports = run_ui([f], port=0, bind="127.0.0.1", open_browser=False)
        base = f"http://127.0.0.1:{server.server_address[1]}"
        # 回环绑定实证：监听地址必须是 127.0.0.1，不存在任何外部监听
        assert server.server_address[0] == "127.0.0.1"
        try:
            # 报告清单端点
            with urllib.request.urlopen(f"{base}/api/reports", timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            assert payload["reports"][0]["kind"] == "verify"
            # 报告数据端点（id 为绝对路径，非 ASCII 场景由 percent-encoding 覆盖测试守护）
            report_id = payload["reports"][0]["id"]
            with urllib.request.urlopen(f"{base}/api/reports/{report_id}", timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
            assert data["data"]["exit_code"] == 0
            # 页面与静态资源
            with urllib.request.urlopen(base + "/", timeout=10) as response:
                assert b'<div id="app">' in response.read()
            # 未知报告 id → 404
            try:
                urllib.request.urlopen(f"{base}/api/reports/nonexistent", timeout=10)
                raise AssertionError("expected 404")
            except urllib.error.HTTPError as exc:
                assert exc.code == 404
        finally:
            server.shutdown()
            server.server_close()


class TestReviewRegressions:
    """评审回归：清单契约/URL 编码/Host 校验/版本门禁/去重。"""

    def test_boolean_version_rejected(self, tmp_path) -> None:
        # bool 是 int 子类：True == 1 不得冒充 v1
        f = _write_report(tmp_path, "b.json", {"report_kind": "lint", "report_version": True})
        with pytest.raises(ReportLoadError, match="version"):
            load_report(f)

    def test_duplicate_report_paths_deduped(self, tmp_path) -> None:
        f = _write_report(tmp_path, "v.json", VERIFY_OK)
        server, reports = run_ui([f, f], port=0, bind="127.0.0.1", open_browser=False)
        try:
            assert len(reports) == 1
        finally:
            server.shutdown()
            server.server_close()

    def test_non_ascii_report_path_loads_via_encoded_id(self, tmp_path) -> None:
        d = tmp_path / "中文 目录"
        d.mkdir()
        f = _write_report(d, "验 证.json", VERIFY_OK)
        server, _reports = run_ui([f], port=0, bind="127.0.0.1", open_browser=False)
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urllib.request.urlopen(f"{base}/api/reports", timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            report_id = payload["reports"][0]["id"]
            assert "中文" in report_id
            encoded = urllib.parse.quote(report_id, safe="")
            with urllib.request.urlopen(f"{base}/api/reports/{encoded}", timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
            assert data["data"]["exit_code"] == 0
        finally:
            server.shutdown()
            server.server_close()

    def test_non_loopback_host_header_rejected(self, tmp_path) -> None:
        """DNS rebinding 防护：非回环 Host 头一律 403。"""
        f = _write_report(tmp_path, "v.json", VERIFY_OK)
        server, _reports = run_ui([f], port=0, bind="127.0.0.1", open_browser=False)
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            req = urllib.request.Request(f"{base}/api/reports")
            req.add_header("Host", "evil.example.com")
            try:
                urllib.request.urlopen(req, timeout=10)
                raise AssertionError("expected 403")
            except urllib.error.HTTPError as exc:
                assert exc.code == 403
        finally:
            server.shutdown()
            server.server_close()

    def test_traversal_attempts_rejected(self, tmp_path) -> None:
        f = _write_report(tmp_path, "v.json", VERIFY_OK)
        server, _reports = run_ui([f], port=0, bind="127.0.0.1", open_browser=False)
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            for path in (
                "/../pyproject.toml",
                "/%2e%2e/pyproject.toml",
                "/..%2fpyproject.toml",
                "/%00",
                "//etc/passwd",
            ):
                try:
                    urllib.request.urlopen(f"{base}{path}", timeout=10)
                    raise AssertionError(f"expected 404 for {path}")
                except urllib.error.HTTPError as exc:
                    assert exc.code == 404, path
        finally:
            server.shutdown()
            server.server_close()

    def test_bind_ipv6_loopback_rejected(self) -> None:
        # ::1 从未真正可用（getfqdn 崩溃 + 浏览器地址固定 127.0.0.1）：白名单显式拒绝
        with pytest.raises(UiBindError, match="loopback"):
            run_ui([], bind="::1", open_browser=False)
