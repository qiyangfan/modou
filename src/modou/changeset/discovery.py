"""变更集发现：目录扫描、V 命名解析、manifest 一致性校验。

规范来源：ADR-0007（Flyway 式 V<序号>__<描述>.sql 命名）与 spec「变更集打包零遗漏」。
错误级（errors）阻塞打包；警告级（warnings）仅提示不阻塞。
"""

import itertools
import re
from dataclasses import dataclass, field
from pathlib import Path

# V<序号>__<描述>.sql：序号至少两位数字零填充（允许更多位），描述为字母/数字/连字符/下划线
_NAME_PATTERN = re.compile(r"^V(?P<seq>\d{2,})__(?P<desc>[A-Za-z0-9_-]+)\.sql$")
MANIFEST_NAME = "manifest.txt"


@dataclass(frozen=True)
class ChangeFile:
    """单个变更脚本：序号决定回放顺序。"""

    path: Path
    filename: str
    seq: int
    description: str


@dataclass
class DiscoveryResult:
    """发现结果：items 按 seq 排序（legacy 文件缀于其后按文件名排序）。"""

    items: list[ChangeFile] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _parse_manifest(directory: Path, errors: list[str]) -> set[str]:
    """读取 manifest.txt，返回声明的文件名集合；manifest 缺失、不可读或行非法记入 errors。"""
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.is_file():
        errors.append(f"manifest missing: {directory / MANIFEST_NAME} is required for packing")
        return set()
    try:
        manifest_text = manifest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # 不可读（权限）或非 UTF-8 编码都按校验错误处理，收敛到确定性退出码而非裸 traceback
        errors.append(f"cannot read {manifest_path}: {exc}")
        return set()
    declared: set[str] = set()
    for raw in manifest_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "/" in line or "\\" in line or ".." in line:
            errors.append(f"manifest entry must be a bare filename, got: {line}")
            continue
        declared.add(line)
    return declared


def discover_changeset(directory: Path, *, allow_legacy_names: bool = False) -> DiscoveryResult:
    """扫描变更集目录，产出按序号排序的脚本清单与校验结论。

    - manifest 声明与目录 .sql 文件必须一一对应（缺/多均错误级）；
    - 序号重复错误级（spec 明确拒绝打包）；跳号警告级（ADR-0007）；
    - 非 V 命名的 .sql 文件默认拒绝，allow_legacy_names=True 时按文件名缀后收录并警告。
    """
    result = DiscoveryResult()
    if not directory.is_dir():
        result.errors.append(f"changeset directory not found: {directory}")
        return result

    declared = _parse_manifest(directory, result.errors)
    sql_files = sorted(p.name for p in directory.glob("*.sql"))
    nested_sql = [str(p.relative_to(directory)) for p in directory.rglob("*.sql") if p.parent != directory]
    if nested_sql:
        result.warnings.append(
            f"subdirectory contains .sql files that are NOT part of the changeset: {', '.join(sorted(nested_sql))}"
        )

    undeclared = sorted(set(sql_files) - declared)
    for name in undeclared:
        result.errors.append(f"file not declared in {MANIFEST_NAME}: {name}")
    missing = sorted(declared - set(sql_files))
    for name in missing:
        result.errors.append(f"manifest declares missing file: {name}")

    numbered: list[ChangeFile] = []
    legacy: list[ChangeFile] = []
    seq_by_name: dict[str, int] = {}
    for name in sql_files:
        match = _NAME_PATTERN.match(name)
        if match is None:
            if allow_legacy_names:
                legacy.append(ChangeFile(directory / name, name, seq=0, description=name))
                result.warnings.append(f"legacy filename admitted by flag (appended after numbered files): {name}")
            else:
                result.errors.append(
                    f"filename not matching V<seq>__<desc>.sql: {name} "
                    "(rename, or pass --allow-legacy-names to admit legacy directory)"
                )
            continue
        seq = int(match.group("seq"))
        seq_by_name[name] = seq
        numbered.append(ChangeFile(directory / name, name, seq=seq, description=match.group("desc")))

    seq_to_names: dict[int, list[str]] = {}
    for name, seq in seq_by_name.items():
        seq_to_names.setdefault(seq, []).append(name)
    for seq, names in sorted(seq_to_names.items()):
        if len(names) > 1:
            result.errors.append(f"duplicate sequence number {seq}: {', '.join(sorted(names))}")

    numbered.sort(key=lambda item: item.seq)
    for prev, curr in itertools.pairwise(item.seq for item in numbered):
        if curr - prev > 1:
            result.warnings.append(f"sequence gap: {prev} -> {curr} (missing {prev + 1})")

    result.items = numbered + sorted(legacy, key=lambda item: item.filename)
    return result
