"""Shared constants and helpers for the AstraEMU metadata repository tools."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent

COMPATIBILITY_SCHEMA = "astra.emu.compatibility.v3"
PRESETS_SCHEMA = "astra.emu.presets.v1"
CORES_SCHEMA = "astra.emu.cores.v1"
INDEX_SCHEMA = "astra.emu.metadata.index.v1"

SCHEMA_FILES = {
    "compatibility": "compatibility.v3.schema.json",
    "index": "index.v1.schema.json",
    "presets": "presets.v1.schema.json",
    "cores": "cores.v1.schema.json",
}

KNOWN_EMULATORS = (
    "rfvp",
    "siglus_rs",
    "art3m1s-core",
    "astra.emu.musica",
    "sena-rs",
    "ethornell-rs",
    "kirikiroid2-web",
    "ReMinori",
    "impacto",
)
PLATFORMS = ("windows", "linux", "macos", "android")
STATUSES = ("perfect", "completable", "flawed", "boot_only", "unplayable")

VN_ID = re.compile(r"v[0-9]{1,12}")
RELEASE_ID = re.compile(r"r[0-9]{1,12}")
INDEX_PATH = re.compile(r"[a-z0-9._-]+(/[a-z0-9._-]+)*")
SEMVER = re.compile(
    r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?"
)

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_INDEXED_FILES = 4096
MAX_INDEX_PATH_BYTES = 256

CORE_URL_PREFIX = "https://github.com/2018wzh/AstraEngine/releases/download/"
IGNORED_FILES = {".gitkeep"}


class DuplicateKeyError(ValueError):
    pass


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"重复的 JSON 键 “{key}”")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    """Parse UTF-8 JSON, rejecting duplicate object keys."""
    return json.loads(path.read_bytes().decode("utf-8"), object_pairs_hook=_reject_duplicates)


def dump_json(value: Any) -> bytes:
    """Deterministic UTF-8 JSON with sorted keys and a trailing newline."""
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def load_schema(root: Path, name: str) -> dict[str, Any]:
    schema = load_json(root / "schema" / SCHEMA_FILES[name])
    jsonschema.Draft7Validator.check_schema(schema)
    return schema


def definition_validator(schema: dict[str, Any], definition: str) -> jsonschema.Draft7Validator:
    """Validator for one `definitions` entry of an exported root schema."""
    return jsonschema.Draft7Validator(
        {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "$ref": f"#/definitions/{definition}",
            "definitions": schema.get("definitions", {}),
        }
    )


def schema_errors(validator: jsonschema.Draft7Validator, value: Any) -> list[str]:
    messages = []
    for error in sorted(validator.iter_errors(value), key=lambda item: list(item.absolute_path)):
        location = "/".join(str(part) for part in error.absolute_path) or "<根>"
        messages.append(f"{location}：{error.message}")
    return messages


def has_control(value: str, allow_newlines: bool = False) -> bool:
    allowed = {"\n", "\t"} if allow_newlines else set()
    return any((ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F) and ch not in allowed for ch in value)


def is_index_path(path: str) -> bool:
    return (
        0 < len(path.encode("utf-8")) <= MAX_INDEX_PATH_BYTES
        and path != "index.json"
        and ".." not in path
        and INDEX_PATH.fullmatch(path) is not None
        and all(segment != "." for segment in path.split("/"))
    )
