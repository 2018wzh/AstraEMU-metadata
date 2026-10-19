"""Turn an accepted compatibility issue form into an entry file.

Usage:
  python tools/issue_to_entry.py --body-file body.md --issue 12 \
      --labeled-at 2026-10-20T08:00:00Z [--root .] [--github-output $GITHUB_OUTPUT]

On success the entry is written to compatibility/entries/<vid>/<rid>/<plugin_id>.json.
On failure every problem is printed (one per line) and the exit code is 1.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import common  # noqa: E402

FIELD_LABELS = {
    "VNDB 作品 ID（vID）": "vid",
    "VNDB 发行版本 ID（rID）": "rid",
    "模拟器": "emulator",
    "运行平台": "platform",
    "模拟器版本": "emulator_version",
    "Manager 版本": "manager_version",
    "兼容性": "status",
    "说明": "notes",
}

STATUS_OPTIONS = {
    "完美运行（perfect）": "perfect",
    "可通关（completable）": "completable",
    "有瑕疵（flawed）": "flawed",
    "仅能启动（boot_only）": "boot_only",
    "无法运行（unplayable）": "unplayable",
}

NO_RESPONSE = "_No response_"
HEADING = re.compile(r"^### (.+?)\s*$", re.MULTILINE)


class IssueFormError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


def parse_form(body: str) -> dict[str, str]:
    """Split the rendered issue form into {field id: value}; empty answers are omitted."""
    body = body.replace("\r\n", "\n")
    headings = list(HEADING.finditer(body))
    fields: dict[str, str] = {}
    for number, heading in enumerate(headings):
        field_id = FIELD_LABELS.get(heading.group(1))
        if field_id is None:
            continue
        end = headings[number + 1].start() if number + 1 < len(headings) else len(body)
        value = body[heading.end() : end].strip()
        if value and value != NO_RESPONSE:
            fields[field_id] = value
    return fields


def _timestamp_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("缺少时区")
    return int(parsed.timestamp() * 1000)


def build_entry(body: str, issue: int, labeled_at: str) -> dict[str, Any]:
    fields = parse_form(body)
    problems: list[str] = []

    vid = fields.get("vid", "")
    if common.VN_ID.fullmatch(vid) is None:
        problems.append(f"vid：“{vid}” 不是有效的 VNDB 作品 ID，格式应为 v 加数字（如 v17）")
    rid = fields.get("rid", "")
    if common.RELEASE_ID.fullmatch(rid) is None:
        problems.append(f"rid：“{rid}” 不是有效的 VNDB 发行版本 ID，格式应为 r 加数字（如 r12345）")
    emulator = fields.get("emulator", "")
    if emulator not in common.KNOWN_EMULATORS:
        problems.append(f"emulator：“{emulator}” 不是已知模拟器，可选值为 {', '.join(common.KNOWN_EMULATORS)}")
    platform = fields.get("platform", "")
    if platform not in common.PLATFORMS:
        problems.append(f"platform：“{platform}” 无效，可选值为 {', '.join(common.PLATFORMS)}")
    status = STATUS_OPTIONS.get(fields.get("status", ""))
    if status is None:
        problems.append(f"status：“{fields.get('status', '')}” 不是表单中的兼容性选项")

    versions: dict[str, str | None] = {}
    for name in ("emulator_version", "manager_version"):
        value = fields.get(name)
        if value is not None and (len(value) > 64 or common.has_control(value)):
            problems.append(f"{name}：最多 64 个字符且只能有一行")
        versions[name] = value
    notes = fields.get("notes")
    if notes is not None and (len(notes) > 1024 or common.has_control(notes, allow_newlines=True)):
        problems.append("notes：最多 1024 个字符")
    if issue < 1:
        problems.append("issue：编号必须为正整数")
    try:
        updated_at = _timestamp_ms(labeled_at)
    except ValueError:
        problems.append(f"labeled_at：“{labeled_at}” 不是带时区的 ISO 8601 时间")
        updated_at = 0
    if problems:
        raise IssueFormError(problems)

    entry = {
        "vn_id": vid,
        "release_id": rid,
        "emulator": emulator,
        "status": status,
        "notes": notes,
        "emulator_version": versions["emulator_version"],
        "manager_version": versions["manager_version"],
        "platform": platform,
        "issue": issue,
        "updated_at_unix_ms": updated_at,
    }
    schema = common.load_schema(common.REPO_ROOT, "compatibility")
    schema_problems = common.schema_errors(common.definition_validator(schema, "CompatibilityEntry"), entry)
    if schema_problems:
        raise IssueFormError(schema_problems)
    return entry


def entry_path(root: Path, entry: dict[str, Any]) -> Path:
    return root / "compatibility" / "entries" / entry["vn_id"] / entry["release_id"] / f"{entry['emulator']}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把兼容性 issue 表单转换为条目文件")
    parser.add_argument("--body-file", type=Path, required=True)
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--labeled-at", required=True)
    parser.add_argument("--root", type=Path, default=common.REPO_ROOT)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    try:
        entry = build_entry(args.body_file.read_text(encoding="utf-8"), args.issue, args.labeled_at)
    except IssueFormError as error:
        for problem in error.problems:
            print(problem)
        return 1
    path = entry_path(args.root, entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(common.dump_json(entry))
    relative = path.relative_to(args.root).as_posix()
    print(relative)
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(f"path={relative}\nvid={entry['vn_id']}\nrid={entry['release_id']}\nemulator={entry['emulator']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
