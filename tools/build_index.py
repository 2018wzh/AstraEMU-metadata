"""Build the published metadata tree.

Usage: python tools/build_index.py --output dist [--root <repository>]

Writes <output>/v1/{index.json, compatibility.json, presets.json, cores.json, patches/...}.
`source_commit` is `git rev-parse HEAD` and `generated_at_unix_ms` is the HEAD commit time,
so building the same commit twice produces byte-identical output.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import common, validate  # noqa: E402

PUBLISHED_VERSION = "v1"


class BuildError(RuntimeError):
    pass


def git_head(root: Path) -> tuple[str, int]:
    def git(*args: str) -> str:
        result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise BuildError(f"git {' '.join(args)} 失败：{result.stderr.strip()}")
        return result.stdout.strip()

    return git("rev-parse", "HEAD"), int(git("show", "-s", "--format=%ct", "HEAD")) * 1000


def build(root: Path, output: Path, source_commit: str, generated_at_unix_ms: int) -> Path:
    dataset = validate.collect(root)
    if dataset.errors:
        raise BuildError("\n".join(dataset.errors))
    target = output / PUBLISHED_VERSION
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    documents = {
        "compatibility.json": {
            "schema": common.COMPATIBILITY_SCHEMA,
            "generated_at_unix_ms": generated_at_unix_ms,
            "entries": dataset.compatibility,
        },
        "presets.json": {"schema": common.PRESETS_SCHEMA, "entries": dataset.presets},
        "cores.json": {"schema": common.CORES_SCHEMA, "entries": dataset.cores},
    }
    files: dict[str, bytes] = {name: common.dump_json(document) for name, document in documents.items()}
    for relative in dataset.patch_files:
        files[relative] = (root / relative).read_bytes()

    indexed = []
    total = 0
    for path in sorted(files):
        payload = files[path]
        if not common.is_index_path(path):
            raise BuildError(f"{path}：发布路径无效")
        if len(payload) > common.MAX_FILE_BYTES:
            raise BuildError(f"{path}：超过单文件 8 MiB 上限")
        total += len(payload)
        destination = target / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        indexed.append({"path": path, "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)})
    if total > common.MAX_TOTAL_BYTES:
        raise BuildError("发布内容超过 64 MiB 总上限")
    if len(indexed) > common.MAX_INDEXED_FILES:
        raise BuildError("发布文件数超过 4096")

    index = {
        "schema": common.INDEX_SCHEMA,
        "generated_at_unix_ms": generated_at_unix_ms,
        "source_commit": source_commit,
        "files": indexed,
    }
    problems = common.schema_errors(
        common.jsonschema.Draft7Validator(common.load_schema(root, "index")), index
    )
    for name, document in documents.items():
        schema = common.load_schema(root, name.removesuffix(".json"))
        problems += [f"{name}：{problem}" for problem in common.schema_errors(common.jsonschema.Draft7Validator(schema), document)]
    if problems:
        raise BuildError("\n".join(problems))
    (target / "index.json").write_bytes(common.dump_json(index))
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 AstraEMU 元数据发布目录")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=common.REPO_ROOT)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        source_commit, generated_at = git_head(root)
        target = build(root, args.output, source_commit, generated_at)
    except BuildError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"已生成 {target.as_posix()}（{source_commit}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
