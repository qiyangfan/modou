"""影子库集成测试夹具：容器拉起/灌入/销毁（宪法：禁止依赖本机手工起库）。

开关与镜像：
- MOUDO_TEST_SHADOW=1 才运行（CI core 门禁保持秒级；本地全量验证显式开启）；
- MOUDO_TEST_MYSQL_IMAGE 覆盖镜像，默认 mysql:8.4（与 ADR-0005 版本矩阵一致）。
"""

from __future__ import annotations

import os
import uuid

import pymysql.connections
import pytest

from modou.replay.container import ShadowMySQL, detect_container_cli

IMAGE_ENV = "MOUDO_TEST_MYSQL_IMAGE"
GATE_ENV = "MOUDO_TEST_SHADOW"
DEFAULT_IMAGE = "mysql:8.4"


@pytest.fixture(scope="session")
def mysql_server() -> ShadowMySQL:
    if os.environ.get(GATE_ENV) != "1":
        pytest.skip(f"shadow integration gated: set {GATE_ENV}=1 to run container tests")
    cli = detect_container_cli()
    if cli is None:
        # 无容器 CLI 同属「拉起失败」：strict 语义要求 fail 而非 skip，不得假性通过
        if os.environ.get("MOUDO_TEST_SHADOW_STRICT") == "1":
            pytest.fail("no container runtime (podman/docker) available (strict mode)")
        pytest.skip("no container runtime (podman/docker) available")
    image = os.environ.get(IMAGE_ENV, DEFAULT_IMAGE)
    try:
        server = ShadowMySQL.start(image, cli=cli)
    except Exception as exc:
        if os.environ.get("MOUDO_TEST_SHADOW_STRICT") == "1":
            pytest.fail(f"shadow mysql unavailable (strict mode): {exc}")
        pytest.skip(f"shadow mysql unavailable: {exc}")
    yield server
    server.close()


@pytest.fixture()
def mysql_conn(mysql_server: ShadowMySQL) -> pymysql.connections.Connection:
    conn = mysql_server.connect_params().connect()
    yield conn
    conn.close()


def unique_db(prefix: str = "modou_t") -> str:
    """每测试独立库名：容器级复用下的测试间隔离。"""
    return f"{prefix}_{uuid.uuid4().hex[:10]}"
