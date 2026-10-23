"""Validate every data file in the AstraEMU metadata repository.

Usage: python tools/validate.py [--root <repository>]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import common  # noqa: E402


@dataclass
class Dataset:
    errors: list[str] = field(default_factory=list)
    compatibility: list[dict[str, Any]] = field(default_factory=list)
    presets: list[dict[str, Any]] = field(default_factory=list)
    cores: list[dict[str, Any]] = field(default_factory=list)
    patch_files: list[str] = field(default_factory=list)


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _data_files(root: Path, directory: str, depth: int, errors: list[str]) -> list[Path]:
    base = root / directory
    if not base.is_dir():
        errors.append(f"{directory}：目录不存在")
        return []
    files = []
    for path in sorted(base.rglob("*")):
        if path.is_dir() or path.name in common.IGNORED_FILES:
            continue
        relative = path.relative_to(base)
        if path.suffix != ".json" or len(relative.parts) != depth:
            errors.append(f"{_relative(root, path)}：不符合目录布局 {directory}/{'/'.join(['…'] * (depth - 1))}/<plugin_id>.json")
            continue
        files.append(path)
    return files


def _load(root: Path, path: Path, errors: list[str]) -> Any:
    try:
        return common.load_json(path)
    except (UnicodeDecodeError, ValueError) as error:
        errors.append(f"{_relative(root, path)}：无法解析 JSON（{error}）")
        return None


def _check_text(errors: list[str], where: str, name: str, value: Any, low: int, high: int, multiline: bool = False) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not low <= len(value) <= high or common.has_control(value, multiline):
        errors.append(f"{where}：{name} 必须是 {low}–{high} 个字符且不含控制字符")


def _check_compatibility(root: Path, dataset: Dataset, schema: dict[str, Any]) -> None:
    validator = common.definition_validator(schema, "CompatibilityEntry")
    owners: dict[tuple[str, str], str] = {}
    for path in _data_files(root, "compatibility/entries", 3, dataset.errors):
        where = _relative(root, path)
        entry = _load(root, path, dataset.errors)
        if entry is None:
            continue
        problems = common.schema_errors(validator, entry)
        if problems:
            dataset.errors.extend(f"{where}：{problem}" for problem in problems)
            continue
        vid, rid = path.parent.parent.name, path.parent.name
        if (entry["vn_id"], entry["release_id"], entry["emulator"]) != (vid, rid, path.stem):
            dataset.errors.append(f"{where}：vn_id/release_id/emulator 与文件路径 {vid}/{rid}/{path.stem} 不一致")
            continue
        if common.VN_ID.fullmatch(vid) is None or common.RELEASE_ID.fullmatch(rid) is None:
            dataset.errors.append(f"{where}：vID/rID 必须为 v/r 加 1–12 位数字")
        if entry["emulator"] not in common.KNOWN_EMULATORS:
            dataset.errors.append(f"{where}：未知模拟器 {entry['emulator']}")
        _check_text(dataset.errors, where, "notes", entry.get("notes"), 0, 1024, multiline=True)
        _check_text(dataset.errors, where, "emulator_version", entry.get("emulator_version"), 1, 64)
        _check_text(dataset.errors, where, "manager_version", entry.get("manager_version"), 1, 64)
        key = (entry["release_id"], entry["emulator"])
        if key in owners:
            dataset.errors.append(f"{where}：重复的 (release_id, emulator) {key[0]}/{key[1]}，已在 {owners[key]} 中定义")
            continue
        owners[key] = where
        dataset.compatibility.append(entry)


def _check_presets(root: Path, dataset: Dataset, schema: dict[str, Any], recipe_ids: set[str]) -> None:
    validator = common.definition_validator(schema, "Preset")
    owners: dict[tuple[str, str], str] = {}
    for path in _data_files(root, "engines/presets", 2, dataset.errors):
        where = _relative(root, path)
        preset = _load(root, path, dataset.errors)
        if preset is None:
            continue
        problems = common.schema_errors(validator, preset)
        if problems:
            dataset.errors.extend(f"{where}：{problem}" for problem in problems)
            continue
        if (preset["release_id"], preset["emulator"]) != (path.parent.name, path.stem):
            dataset.errors.append(f"{where}：release_id/emulator 与文件路径不一致")
            continue
        if common.VN_ID.fullmatch(preset["vn_id"]) is None or common.RELEASE_ID.fullmatch(preset["release_id"]) is None:
            dataset.errors.append(f"{where}：vID/rID 必须为 v/r 加 1–12 位数字")
        if preset["emulator"] not in common.KNOWN_EMULATORS:
            dataset.errors.append(f"{where}：未知模拟器 {preset['emulator']}")
        _check_text(dataset.errors, where, "summary", preset["summary"], 1, 120)
        configuration = preset["configuration"]
        if len(configuration) > 256:
            dataset.errors.append(f"{where}：configuration 最多 256 项")
        for key, value in configuration.items():
            if not (0 < len(key) <= 128 and all(ch.isascii() and (ch.isalnum() or ch in "._-") for ch in key)):
                dataset.errors.append(f"{where}：配置项名称 “{key}” 无效")
            _check_text(dataset.errors, where, f"configuration.{key}", value, 0, 4096)
        patch = preset.get("patch")
        if patch is not None and patch not in recipe_ids:
            dataset.errors.append(f"{where}：patch “{patch}” 不在 patches/catalog.json 中")
        key = (preset["release_id"], preset["emulator"])
        if key in owners:
            dataset.errors.append(f"{where}：重复的 (release_id, emulator)")
            continue
        owners[key] = where
        dataset.presets.append(preset)


def _check_cores(root: Path, dataset: Dataset, schema: dict[str, Any]) -> None:
    validator = common.definition_validator(schema, "CoreCatalogEntry")
    for path in _data_files(root, "engines/cores", 1, dataset.errors):
        where = _relative(root, path)
        entry = _load(root, path, dataset.errors)
        if entry is None:
            continue
        problems = common.schema_errors(validator, entry)
        if problems:
            dataset.errors.extend(f"{where}：{problem}" for problem in problems)
            continue
        if entry["plugin_id"] != path.stem:
            dataset.errors.append(f"{where}：plugin_id 与文件名不一致")
            continue
        for name in ("display_name", "family_name"):
            _check_text(dataset.errors, where, name, entry[name], 1, 64)
        _check_text(dataset.errors, where, "abi", entry["abi"], 1, 128)
        _check_text(dataset.errors, where, "license", entry["license"], 1, 128)
        if len(entry["version"]) > 64 or common.SEMVER.fullmatch(entry["version"]) is None:
            dataset.errors.append(f"{where}：version 必须是语义化版本号")
        tag, _, asset = entry["url"].removeprefix(common.CORE_URL_PREFIX).partition("/")
        if tag != entry["release_tag"] or not asset or asset in {".", ".."} or len(asset) > 256:
            dataset.errors.append(f"{where}：url 必须指向 release_tag 对应的主仓 Release 资产")
        dataset.cores.append(entry)


def _check_patches(root: Path, dataset: Dataset) -> set[str]:
    patches = root / "patches"
    catalog_path = patches / "catalog.json"
    if not catalog_path.is_file():
        dataset.errors.append("patches/catalog.json：文件不存在")
        return set()
    catalog = _load(root, catalog_path, dataset.errors)
    recipe_ids: set[str] = set()
    if not isinstance(catalog, list):
        if catalog is not None:
            dataset.errors.append("patches/catalog.json：必须是数组")
        catalog = []
    for number, recipe in enumerate(catalog):
        where = f"patches/catalog.json[{number}]"
        fields = {"id", "title", "script", "vn_ids", "emulators"}
        if not isinstance(recipe, dict) or set(recipe) != fields or not all(isinstance(recipe[name], str) for name in ("id", "title", "script")):
            dataset.errors.append(f"{where}：必须只包含字段 id、title、script（字符串）与 vn_ids、emulators（数组）")
            continue
        vn_ids, emulators = recipe["vn_ids"], recipe["emulators"]
        if not isinstance(vn_ids, list) or not vn_ids or not all(isinstance(vid, str) and common.VN_ID.fullmatch(vid) for vid in vn_ids) or len(set(vn_ids)) != len(vn_ids):
            dataset.errors.append(f"{where}：vn_ids 必须是不重复的 VNDB 作品 ID（v 加 1–12 位数字）组成的非空数组")
        if not isinstance(emulators, list) or not emulators or not all(isinstance(emulator, str) for emulator in emulators) or len(set(emulators)) != len(emulators):
            dataset.errors.append(f"{where}：emulators 必须是不重复的模拟器 plugin_id 组成的非空数组")
        else:
            for emulator in emulators:
                if emulator not in common.KNOWN_EMULATORS:
                    dataset.errors.append(f"{where}：未知模拟器 {emulator}")
        if not recipe["id"].strip() or "\0" in recipe["id"] or not recipe["title"].strip():
            dataset.errors.append(f"{where}：id 与 title 不能为空")
        elif recipe["id"] in recipe_ids:
            dataset.errors.append(f"{where}：重复的补丁 id “{recipe['id']}”")
        recipe_ids.add(recipe["id"])
        script = PurePosixPath(recipe["script"])
        if script.is_absolute() or ".." in script.parts or "\\" in recipe["script"] or not common.is_index_path(f"patches/{script}"):
            dataset.errors.append(f"{where}：脚本路径 “{recipe['script']}” 无效")
        elif not (patches / script).is_file():
            dataset.errors.append(f"{where}：脚本 “{recipe['script']}” 不存在")
    for path in sorted(patches.rglob("*")):
        if path.is_dir():
            continue
        relative = _relative(root, path)
        if not common.is_index_path(relative):
            dataset.errors.append(f"{relative}：发布路径只能使用 [a-z0-9._/-]")
        elif path.stat().st_size > common.MAX_FILE_BYTES:
            dataset.errors.append(f"{relative}：单个文件不能超过 8 MiB")
        else:
            dataset.patch_files.append(relative)
    return recipe_ids


def collect(root: Path) -> Dataset:
    dataset = Dataset()
    schemas: dict[str, dict[str, Any]] = {}
    for name, file_name in common.SCHEMA_FILES.items():
        try:
            schemas[name] = common.load_schema(root, name)
        except (OSError, ValueError, common.jsonschema.SchemaError) as error:
            dataset.errors.append(f"schema/{file_name}：{error}")
    if len(schemas) != len(common.SCHEMA_FILES):
        return dataset
    recipe_ids = _check_patches(root, dataset)
    _check_compatibility(root, dataset, schemas["compatibility"])
    _check_presets(root, dataset, schemas["presets"], recipe_ids)
    _check_cores(root, dataset, schemas["cores"])
    dataset.compatibility.sort(key=lambda entry: (int(entry["vn_id"][1:]), int(entry["release_id"][1:]), entry["emulator"]))
    dataset.presets.sort(key=lambda preset: (int(preset["release_id"][1:]), preset["emulator"]))
    dataset.cores.sort(key=lambda entry: (entry["plugin_id"], entry["platform"], entry["version"]))
    return dataset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验 AstraEMU 元数据仓库")
    parser.add_argument("--root", type=Path, default=common.REPO_ROOT)
    args = parser.parse_args(argv)
    dataset = collect(args.root.resolve())
    for error in dataset.errors:
        print(error, file=sys.stderr)
    if dataset.errors:
        print(f"校验失败：{len(dataset.errors)} 个问题", file=sys.stderr)
        return 1
    print(
        f"校验通过：兼容性 {len(dataset.compatibility)} 条，推荐配置 {len(dataset.presets)} 条，"
        f"核心 {len(dataset.cores)} 个，补丁文件 {len(dataset.patch_files)} 个"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
