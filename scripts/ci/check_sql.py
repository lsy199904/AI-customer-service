#!/usr/bin/env python3
"""PostgreSQL SQL 风格与迁移安全检查。

范围：database/postgres
用法：
    python3 scripts/ci/check_sql.py

环境变量：
    BASE_REF          迁移不可变性比较基线，默认 origin/main → origin/master → HEAD
    SQLFLUFF_BIN      sqlfluff 可执行文件路径；默认从 PATH 查找
    REQUIRE_SQLFLUFF  设为 1 时，找不到 sqlfluff 直接失败（CI 推荐）
    CI                设为 true 时，等价于 REQUIRE_SQLFLUFF=1

退出码：
    0  通过（可能有警告）
    1  存在错误
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(
    subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], text=True
    ).strip()
)
DB_DIR = ROOT / "database" / "postgres"
MIG_DIR = DB_DIR / "migrations"
CHECKS_DIR = DB_DIR / "checks"
BASELINE = MIG_DIR / "V1.0.0__baseline.sql"
DOCKERFILE = DB_DIR.parent.parent / "deploy/docker/db-migrate/Dockerfile"
SQLFLUFF_CONFIG = ROOT / ".sqlfluff"

# 基线一旦发布即不可变；如确需合法重建基线，走变更评审并同步更新此值与 README.md。
BASELINE_SHA256 = "0e2798bae904e0e73a96a4ca2ebac76092410b1bddaa3942aeb1e8193209953a"

VERSIONED_RE = re.compile(r"^V(\d+\.\d+\.\d+)__[a-z0-9_]+\.sql$")
REPEATABLE_RE = re.compile(r"^R__[a-z0-9_]+\.sql$")
CALLBACK_RE = re.compile(r"^(?:before|after)[A-Za-z]+__[a-z0-9_]+\.sql$")

# 版本化迁移必须放在这些领域目录下；基线 V1.0.0 例外，留在 migrations/ 根。
DOMAINS = ("conversation", "quota", "knowledge", "workflow", "platform")
HEADER_KEYS = ("目的：", "领域：", "影响表：", "回滚/修复：")

errors: list[str] = []
warnings: list[str] = []


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=ROOT, text=True, capture_output=True, check=False
    )


def git(*args: str) -> str:
    result = run(["git", *args])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_naming() -> None:
    for path in sorted(MIG_DIR.rglob("*.sql")):
        name = path.name
        if (
            VERSIONED_RE.match(name)
            or REPEATABLE_RE.match(name)
            or CALLBACK_RE.match(name)
        ):
            continue
        errors.append(
            "迁移文件名不符合约定（V<semver>__desc.sql / R__desc.sql / "
            f"beforeMigrate|afterMigrate__desc.sql）: {rel(path)}"
        )


def check_duplicate_versions() -> None:
    seen: dict[str, str] = {}
    for path in sorted(MIG_DIR.rglob("V*.sql")):
        match = VERSIONED_RE.match(path.name)
        if not match:
            continue
        version = match.group(1)
        if version in seen:
            errors.append(
                f"重复迁移版本号 {version}: {seen[version]} 与 {path.name}"
            )
        else:
            seen[version] = path.name


def check_baseline_checksum() -> None:
    if not BASELINE.is_file():
        errors.append("缺少基线文件: migrations/V1.0.0__baseline.sql")
        return
    actual = sha256_file(BASELINE)
    if actual != BASELINE_SHA256:
        errors.append(
            "V1.0.0__baseline.sql 内容被修改（checksum 不一致）。"
            "已应用迁移不可重排、改注释或改空白；如确需变更，请走 "
            "flyway repair 流程并同步更新 database/postgres/README.md 与本脚本常量。"
        )


def check_placeholders() -> None:
    """非迁移脚本不应出现 Flyway 占位符，避免误替换。"""
    for path in sorted(CHECKS_DIR.glob("*.sql")):
        if "${" in path.read_text(encoding="utf-8"):
            errors.append(f"checks 脚本不应包含 Flyway 占位符: {rel(path)}")


def strip_sql_comments(sql: str) -> str:
    """去掉注释后再做关键字检查，避免说明文字被误判。"""
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", "", sql)


def check_concurrent_index() -> None:
    """CREATE INDEX CONCURRENTLY 不能在 Flyway 的迁移事务内执行。"""
    pattern = re.compile(r"CREATE\s+INDEX\s+CONCURRENTLY", re.IGNORECASE)
    for path in sorted(MIG_DIR.rglob("V*.sql")):
        if pattern.search(strip_sql_comments(path.read_text(encoding="utf-8"))):
            errors.append(
                f"{path.name}: 检测到 CREATE INDEX CONCURRENTLY。"
                "Flyway 默认每个迁移一个事务，请拆为独立运维步骤或改用普通 CREATE INDEX。"
            )


def resolve_base_ref() -> str | None:
    explicit = os.getenv("BASE_REF", "").strip()
    if explicit:
        return explicit
    for candidate in ("origin/main", "origin/master"):
        if run(["git", "rev-parse", "--verify", candidate]).returncode == 0:
            return candidate
    if run(["git", "rev-parse", "--verify", "HEAD"]).returncode == 0:
        return "HEAD"
    return None


def check_immutability() -> None:
    """已存在的 V*.sql 只允许新增，不允许修改/删除。

    纯移动（例如归档）允许，但移动后的文件内容必须与基线提交中的 blob 完全一致。
    """
    explicit = os.getenv("BASE_REF", "").strip()
    if explicit and run(["git", "rev-parse", "--verify", explicit]).returncode != 0:
        errors.append(
            f"BASE_REF={explicit} 不存在或不可解析，无法执行迁移不可变性检查"
        )
        return

    base_ref = resolve_base_ref()
    if not base_ref:
        warnings.append("找不到可用的 BASE_REF，跳过迁移不可变性检查")
        return

    merge_base = run(["git", "merge-base", base_ref, "HEAD"])
    base_commit = merge_base.stdout.strip() if merge_base.returncode == 0 else base_ref

    tree = run(
        ["git", "ls-tree", "-r", "--name-only", base_commit, "--", rel(MIG_DIR)]
    )
    if tree.returncode != 0:
        errors.append(f"无法读取基线 {base_commit} 的迁移目录，迁移不可变性检查失败")
        return

    base_files = [
        line
        for line in tree.stdout.splitlines()
        if VERSIONED_RE.match(Path(line).name)
    ]

    archive_root = ROOT / "database" / "archive"
    for repo_path in base_files:
        base_blob = run(["git", "rev-parse", f"{base_commit}:{repo_path}"])
        if base_blob.returncode != 0:
            continue
        expected = base_blob.stdout.strip()
        current = ROOT / repo_path

        if current.is_file():
            actual = run(["git", "hash-object", str(current)])
            if actual.returncode == 0 and actual.stdout.strip() != expected:
                errors.append(f"已存在的迁移被修改: {repo_path}")
            continue

        # 文件不在原路径：允许纯移动，但必须在归档目录找到同内容副本
        moved = False
        if archive_root.is_dir():
            for candidate in archive_root.rglob("*.sql"):
                hashed = run(["git", "hash-object", str(candidate)])
                if hashed.returncode == 0 and hashed.stdout.strip() == expected:
                    moved = True
                    break
        if not moved:
            errors.append(f"已存在的迁移被删除或移动且找不到同内容副本: {repo_path}")


def check_sqlfluff() -> None:
    executable = os.getenv("SQLFLUFF_BIN") or shutil.which("sqlfluff")
    required = os.getenv("REQUIRE_SQLFLUFF") == "1" or os.getenv("CI") == "true"

    if not executable:
        message = (
            "未找到 sqlfluff，跳过格式检查。CI 中请安装 sqlfluff，"
            "或设置 REQUIRE_SQLFLUFF=1 强制失败。"
        )
        (errors if required else warnings).append(message)
        return

    targets = [
        path
        for path in sorted(MIG_DIR.rglob("V*.sql"))
        if path.name != BASELINE.name
    ]
    fingerprint = CHECKS_DIR / "schema_fingerprint.sql"
    if fingerprint.is_file():
        targets.append(fingerprint)

    if not targets:
        return

    result = run(
        [
            executable,
            "lint",
            "--config",
            str(SQLFLUFF_CONFIG),
            *[str(path) for path in targets],
        ]
    )
    if result.returncode != 0:
        details = (result.stdout + result.stderr).strip()
        errors.append("sqlfluff 检查未通过:\n" + details)


def version_key(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def current_version_files() -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in sorted(MIG_DIR.rglob("V*.sql")):
        match = VERSIONED_RE.match(path.name)
        if match:
            result[match.group(1)] = path
    return result


def base_version_files() -> dict[str, Path] | None:
    base_ref = resolve_base_ref()
    if not base_ref:
        warnings.append("找不到可用的 BASE_REF，跳过新增迁移的版本顺序/文件头检查")
        return None
    merge_base = run(["git", "merge-base", base_ref, "HEAD"])
    base_commit = merge_base.stdout.strip() if merge_base.returncode == 0 else base_ref
    tree = run(
        ["git", "ls-tree", "-r", "--name-only", base_commit, "--", rel(MIG_DIR)]
    )
    if tree.returncode != 0:
        errors.append(f"无法读取基线 {base_commit} 的迁移目录，版本顺序检查失败")
        return None
    result: dict[str, Path] = {}
    for line in tree.stdout.splitlines():
        path = Path(line)
        match = VERSIONED_RE.match(path.name)
        if match:
            result[match.group(1)] = ROOT / line
    return result


def check_migrations_packaging() -> None:
    """迁移镜像按目录显式 COPY，必须与 migrations/ 下的实际目录一一对应。

    显式 COPY 的好处是镜像内容可读，代价是新增领域目录容易漏改 Dockerfile；
    这里在 CI 阶段把漏改拦下来，避免“迁移写好了但镜像里没有”。
    """
    if not DOCKERFILE.exists():
        errors.append(f"缺少迁移镜像 Dockerfile: {rel(DOCKERFILE)}")
        return

    text = DOCKERFILE.read_text(encoding="utf-8")
    pattern = re.compile(
        r"^COPY\s+database/postgres/migrations/([A-Za-z0-9_.-]+)/\s+"
        r"/flyway/migrations/([A-Za-z0-9_.-]+)/",
        re.MULTILINE,
    )
    copied = {m.group(1) for m in pattern.finditer(text) if m.group(1) == m.group(2)}

    actual = {
        item.name
        for item in MIG_DIR.iterdir()
        if item.is_dir() and not item.name.startswith(".")
    }

    for name in sorted(actual - copied):
        errors.append(
            f"migrations/{name}/ 未在 {rel(DOCKERFILE)} 中 COPY，镜像会缺少该目录"
        )
    for name in sorted(copied - actual):
        errors.append(
            f"{rel(DOCKERFILE)} 复制了不存在的目录 migrations/{name}/，构建会失败"
        )

    if not re.search(
        r"^COPY\s+database/postgres/migrations/\*\.sql\s+/flyway/migrations/",
        text,
        re.MULTILINE,
    ):
        errors.append(
            f"{rel(DOCKERFILE)} 缺少根目录 V*.sql 的 COPY，版本脚本不会进入镜像"
        )


def check_domain_layout() -> None:
    allowed = "、".join(DOMAINS)
    for path in sorted(MIG_DIR.rglob("V*.sql")):
        if path == BASELINE:
            continue
        relative = path.relative_to(MIG_DIR)
        if len(relative.parts) != 2 or relative.parts[0] not in DOMAINS:
            errors.append(
                f"版本化迁移必须放在 migrations/<domain>/ 下（{allowed}），"
                f"基线 {BASELINE.name} 除外: {rel(path)}"
            )


def check_new_migrations() -> None:
    base = base_version_files()
    if base is None:
        return
    current = current_version_files()
    new_files = {
        version: path
        for version, path in current.items()
        if version not in base and path != BASELINE
    }
    if not new_files:
        return

    if not base and BASELINE.is_file():
        baseline_match = VERSIONED_RE.match(BASELINE.name)
        if baseline_match:
            base = {baseline_match.group(1): BASELINE}

    if base:
        base_max = max(base, key=version_key)
        lowest = min(new_files, key=version_key)
        if version_key(lowest) <= version_key(base_max):
            errors.append(
                f"新增迁移版本 {lowest} 必须大于基线分支最大版本 {base_max}；"
                "请 rebase 后改为下一个可用版本"
            )

    for version, path in sorted(
        new_files.items(), key=lambda item: version_key(item[0])
    ):
        if path == BASELINE:
            continue
        head = path.read_text(encoding="utf-8").splitlines()[:15]
        missing = [key for key in HEADER_KEYS if not any(key in line for line in head)]
        if missing:
            errors.append(
                f"{rel(path)} 缺少文件头字段：{'、'.join(missing)}；"
                "请参考 templates/V__migration.sql.tmpl"
            )


def main() -> int:
    if not MIG_DIR.is_dir():
        print(f"ERROR: 迁移目录不存在: {rel(MIG_DIR)}", file=sys.stderr)
        return 1

    check_naming()
    check_domain_layout()
    check_migrations_packaging()
    check_duplicate_versions()
    check_new_migrations()
    check_baseline_checksum()
    check_placeholders()
    check_concurrent_index()
    check_immutability()
    check_sqlfluff()

    print("== PostgreSQL SQL checks ==")
    for warning in warnings:
        print(f"WARN: {warning}")
    for error in errors:
        print(f"ERROR: {error}")

    if errors:
        print(f"\n失败：{len(errors)} 个错误，{len(warnings)} 个警告")
        return 1

    print(f"通过：0 个错误，{len(warnings)} 个警告")
    print(
        "提示：migrations/callbacks/beforeMigrate、migrations/callbacks/afterMigrate、"
        "checks/health.sql 为 PL/pgSQL，未交给 sqlfluff；请人工评审或用 pgFormatter 处理。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
