"""影子库容器编排：经 podman/docker CLI 拉起一次性 MySQL 容器。

选择 CLI 而非 testcontainers：零额外依赖（重依赖红线），podman/docker 命令面同构，
本地与 CI 行为一致。容器仅监听 127.0.0.1 随机端口，root 口令随机生成，用后即焚。
"""

from __future__ import annotations

import contextlib
import secrets
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass

import pymysql

from modou.db import MysqlParams

STARTUP_TIMEOUT_SECONDS = 180


class ContainerRuntimeError(Exception):
    """容器拉起/销毁失败（环境问题，verify 映射退出码 2）。"""


def detect_container_cli() -> str | None:
    """探测可用的容器 CLI：podman 优先，docker 兼容兜底。"""
    for cli in ("podman", "docker"):
        if shutil.which(cli):
            return cli
    return None


@dataclass
class ShadowMySQL:
    image: str
    cli: str
    container_name: str
    root_password: str
    host: str = "127.0.0.1"
    port: int = 0

    @classmethod
    def start(
        cls, image: str, *, cli: str | None = None, startup_timeout: int = STARTUP_TIMEOUT_SECONDS
    ) -> ShadowMySQL:
        """拉起容器并等待 MySQL 就绪；失败时清理残留容器。"""
        resolved_cli = cli or detect_container_cli()
        if resolved_cli is None:
            raise ContainerRuntimeError("no container runtime found (tried: podman, docker)")
        shadow = cls(
            image=image,
            cli=resolved_cli,
            container_name=f"modou-shadow-{uuid.uuid4().hex[:12]}",
            root_password=secrets.token_urlsafe(24),
        )
        try:
            shadow._run_container()
            shadow._resolve_port()
            shadow._wait_ready(startup_timeout)
        except Exception:
            # 清理尽力而为：close 失败不得掩盖原始启动错误
            with contextlib.suppress(Exception):
                shadow.close()
            raise
        return shadow

    def close(self) -> None:
        """销毁容器（幂等）。"""
        try:
            subprocess.run(
                [self.cli, "rm", "-f", self.container_name],
                capture_output=True,
                timeout=60,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise ContainerRuntimeError(f"failed to remove container {self.container_name}: {exc}") from exc

    def connect_params(self) -> MysqlParams:
        return MysqlParams(host=self.host, port=self.port, user="root", password=self.root_password)

    def _run_container(self) -> None:
        try:
            result = subprocess.run(
                [
                    self.cli,
                    "run",
                    "-d",
                    "--name",
                    self.container_name,
                    "-e",
                    f"MYSQL_ROOT_PASSWORD={self.root_password}",
                    "-p",
                    "127.0.0.1::3306",
                    self.image,
                ],
                capture_output=True,
                text=True,
                timeout=300,  # 首次拉取镜像可能远超容器启动本身
            )
        except subprocess.TimeoutExpired as exc:
            raise ContainerRuntimeError(f"container start timed out: {exc}") from exc
        except OSError as exc:
            raise ContainerRuntimeError(f"container CLI failed: {exc}") from exc
        if result.returncode != 0:
            raise ContainerRuntimeError(f"container start failed: {result.stderr.strip()}")

    def _resolve_port(self) -> None:
        try:
            result = subprocess.run(
                [self.cli, "port", self.container_name, "3306"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            # 与 _run_container 同款归一：容器 CLI 的异常不得裸穿破坏退出码契约
            raise ContainerRuntimeError(f"cannot resolve container port: {exc}") from exc
        if result.returncode != 0 or not result.stdout.strip():
            raise ContainerRuntimeError(f"cannot resolve container port: {result.stderr.strip()}")
        # 输出形如 "127.0.0.1:32768"（可能多行，取首行最后一列的端口）；畸形输出归一为
        # ContainerRuntimeError，不得以 IndexError/ValueError 裸穿破坏退出码契约
        line = result.stdout.strip().splitlines()[0]
        try:
            self.port = int(line.rsplit(":", 1)[1])
        except (IndexError, ValueError) as exc:
            raise ContainerRuntimeError(f"cannot parse container port from {line!r}") from exc

    def _wait_ready(self, timeout: int) -> None:
        """轮询直到 MySQL 可连且 SELECT 1 成功（镜像初始化期间会重启内部服务）。"""

        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                conn = self.connect_params().connect(connect_timeout=3)
                try:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT 1")
                        cursor.fetchone()
                finally:
                    conn.close()
                return
            except pymysql.err.MySQLError as exc:
                last_error = exc
                time.sleep(1.0)
        raise ContainerRuntimeError(f"mysql not ready within {timeout}s: {last_error}")
