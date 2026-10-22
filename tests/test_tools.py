from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools import build_index, common, issue_to_entry, validate

FORM = """### VNDB 作品 ID（vID）

v17

### VNDB 发行版本 ID（rID）

r12345

### 模拟器

sena-rs

### 运行平台

windows

### 模拟器版本

0.2.0

### Manager 版本

0.2.0

### 兼容性

有瑕疵（flawed）

### 说明

第二章视频花屏。
其余正常。
"""


def form(**overrides: str) -> str:
    labels = {
        "vid": ("VNDB 作品 ID（vID）", "v17"),
        "rid": ("VNDB 发行版本 ID（rID）", "r12345"),
        "emulator": ("模拟器", "sena-rs"),
        "platform": ("运行平台", "windows"),
    }
    body = FORM
    for key, value in overrides.items():
        label, original = labels[key]
        body = body.replace(f"### {label}\n\n{original}\n", f"### {label}\n\n{value}\n")
    return body


class FixtureRepository:
    def __init__(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name) / "repo"
        shutil.copytree(common.REPO_ROOT / "schema", self.root / "schema")
        shutil.copytree(common.REPO_ROOT / "patches", self.root / "patches")
        for directory in ("compatibility/entries", "engines/presets", "engines/cores"):
            (self.root / directory).mkdir(parents=True)

    def write(self, relative: str, value: object) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(common.dump_json(value))
        return path

    def close(self) -> None:
        self._directory.cleanup()


def compat_entry(rid: str = "r1", emulator: str = "astra.emu.musica", status: str = "perfect") -> dict:
    return {
        "vn_id": "v17",
        "release_id": rid,
        "emulator": emulator,
        "status": status,
        "notes": None,
        "emulator_version": "0.2.0",
        "manager_version": "0.2.0",
        "platform": "windows",
        "issue": 3,
        "updated_at_unix_ms": 1_700_000_000_000,
    }


class IssueToEntryTests(unittest.TestCase):
    def test_valid_form_produces_expected_entry(self) -> None:
        entry = issue_to_entry.build_entry(FORM, 42, "2026-10-20T08:00:00Z")
        self.assertEqual(
            entry,
            {
                "vn_id": "v17",
                "release_id": "r12345",
                "emulator": "sena-rs",
                "status": "flawed",
                "notes": "第二章视频花屏。\n其余正常。",
                "emulator_version": "0.2.0",
                "manager_version": "0.2.0",
                "platform": "windows",
                "issue": 42,
                "updated_at_unix_ms": 1_792_483_200_000,
            },
        )

    def test_crlf_and_empty_optional_answers(self) -> None:
        body = FORM.replace("第二章视频花屏。\n其余正常。", "_No response_").replace("\n", "\r\n")
        entry = issue_to_entry.build_entry(body, 1, "2026-10-20T08:00:00+08:00")
        self.assertIsNone(entry["notes"])
        self.assertEqual(entry["updated_at_unix_ms"], 1_792_454_400_000)

    def test_release_id_without_prefix_is_rejected(self) -> None:
        with self.assertRaises(issue_to_entry.IssueFormError) as caught:
            issue_to_entry.build_entry(form(rid="12345"), 42, "2026-10-20T08:00:00Z")
        self.assertIn("rid", str(caught.exception))

    def test_unknown_emulator_is_rejected(self) -> None:
        with self.assertRaises(issue_to_entry.IssueFormError) as caught:
            issue_to_entry.build_entry(form(emulator="foo"), 42, "2026-10-20T08:00:00Z")
        self.assertIn("emulator", str(caught.exception))

    def test_ethornell_plugin_id_is_accepted(self) -> None:
        entry = issue_to_entry.build_entry(form(emulator="ethornell-rs"), 7, "2026-10-20T08:00:00Z")
        self.assertEqual(entry["emulator"], "ethornell-rs")

    def test_cli_writes_entry_at_keyed_path(self) -> None:
        repository = FixtureRepository()
        self.addCleanup(repository.close)
        body = repository.root / "body.md"
        body.write_text(FORM, encoding="utf-8")
        code = issue_to_entry.main(
            ["--body-file", str(body), "--issue", "42", "--labeled-at", "2026-10-20T08:00:00Z", "--root", str(repository.root)]
        )
        self.assertEqual(code, 0)
        written = repository.root / "compatibility/entries/v17/r12345/sena-rs.json"
        self.assertEqual(json.loads(written.read_text(encoding="utf-8"))["status"], "flawed")
        self.assertEqual(validate.collect(repository.root).errors, [])


class ValidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FixtureRepository()
        self.addCleanup(self.repository.close)

    def test_repository_data_is_valid(self) -> None:
        self.assertEqual(validate.collect(common.REPO_ROOT).errors, [])

    def test_duplicate_json_key_fails(self) -> None:
        path = self.repository.root / "compatibility/entries/v17/r1/astra.emu.musica.json"
        path.parent.mkdir(parents=True)
        text = common.dump_json(compat_entry()).decode("utf-8")
        path.write_text(text.replace('"status": "perfect"', '"status": "perfect",\n  "status": "flawed"'), encoding="utf-8")
        errors = validate.collect(self.repository.root).errors
        self.assertEqual(len(errors), 1)
        self.assertIn("status", errors[0])

    def test_duplicate_release_and_emulator_fails(self) -> None:
        self.repository.write("compatibility/entries/v17/r1/astra.emu.musica.json", compat_entry())
        duplicate = compat_entry()
        duplicate["vn_id"] = "v18"
        self.repository.write("compatibility/entries/v18/r1/astra.emu.musica.json", duplicate)
        errors = validate.collect(self.repository.root).errors
        self.assertTrue(any("重复" in error for error in errors), errors)

    def test_path_must_match_content(self) -> None:
        self.repository.write("compatibility/entries/v17/r2/astra.emu.musica.json", compat_entry("r1"))
        errors = validate.collect(self.repository.root).errors
        self.assertTrue(any("不一致" in error for error in errors), errors)

    def test_missing_catalog_script_fails(self) -> None:
        catalog = json.loads((self.repository.root / "patches/catalog.json").read_text(encoding="utf-8"))
        catalog.append({"id": "missing", "title": "缺失脚本", "script": "missing.luau"})
        (self.repository.root / "patches/catalog.json").write_bytes(common.dump_json(catalog))
        errors = validate.collect(self.repository.root).errors
        self.assertTrue(any("missing.luau" in error for error in errors), errors)

    def test_preset_patch_must_exist(self) -> None:
        preset = {
            "vn_id": "v17",
            "release_id": "r1",
            "emulator": "astra.emu.musica",
            "summary": "使用 GBK 脚本编码",
            "configuration": {"script_encoding": "gbk"},
            "patch": "not-in-catalog",
        }
        self.repository.write("engines/presets/r1/astra.emu.musica.json", preset)
        errors = validate.collect(self.repository.root).errors
        self.assertTrue(any("not-in-catalog" in error for error in errors), errors)
        preset["patch"] = "musica-eden-cn"
        self.repository.write("engines/presets/r1/astra.emu.musica.json", preset)
        self.assertEqual(validate.collect(self.repository.root).errors, [])

    def test_core_url_must_target_release_asset(self) -> None:
        core = {
            "plugin_id": "astra.emu.musica",
            "display_name": "Astra Musica",
            "family_name": "Musica",
            "version": "0.2.0",
            "abi": "astra.emu.native.c.v3",
            "platform": "windows-x86_64",
            "url": common.CORE_URL_PREFIX + "emu-v0.2.0/astra-emu-core-astra_emu_musica-0.2.0-windows-x86_64.zip",
            "sha256": "a" * 64,
            "size": 1024,
            "license": "MIT OR Apache-2.0",
            "release_tag": "emu-v0.2.0",
        }
        self.repository.write("engines/cores/astra.emu.musica.json", core)
        self.assertEqual(validate.collect(self.repository.root).errors, [])
        core["release_tag"] = "emu-v0.3.0"
        self.repository.write("engines/cores/astra.emu.musica.json", core)
        self.assertNotEqual(validate.collect(self.repository.root).errors, [])


class BuildIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FixtureRepository()
        self.addCleanup(self.repository.close)
        self.repository.write("compatibility/entries/v17/r2/astra.emu.musica.json", compat_entry("r2"))
        self.repository.write(
            "compatibility/entries/v17/r10/sena-rs.json", compat_entry("r10", "sena-rs", "flawed")
        )

    def _build(self, name: str) -> Path:
        output = self.repository.root.parent / name
        build_index.build(self.repository.root, output, "0123456789abcdef0123456789abcdef01234567", 1_700_000_000_000)
        return output / "v1"

    def test_two_builds_are_byte_identical(self) -> None:
        first, second = self._build("dist-a"), self._build("dist-b")
        first_files = sorted(path.relative_to(first).as_posix() for path in first.rglob("*") if path.is_file())
        second_files = sorted(path.relative_to(second).as_posix() for path in second.rglob("*") if path.is_file())
        self.assertEqual(first_files, second_files)
        for relative in first_files:
            self.assertEqual((first / relative).read_bytes(), (second / relative).read_bytes(), relative)

    def test_index_covers_every_published_file(self) -> None:
        target = self._build("dist")
        index = json.loads((target / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["schema"], common.INDEX_SCHEMA)
        published = sorted(
            path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file() and path.name != "index.json"
        )
        self.assertEqual([file["path"] for file in index["files"]], published)
        self.assertIn("patches/common/enigma_vfs.luau", published)
        compatibility = json.loads((target / "compatibility.json").read_text(encoding="utf-8"))
        self.assertEqual([entry["release_id"] for entry in compatibility["entries"]], ["r2", "r10"])

    def test_build_refuses_invalid_repository(self) -> None:
        self.repository.write("compatibility/entries/v17/r3/foo.json", compat_entry("r3", "foo"))
        with self.assertRaises(build_index.BuildError):
            self._build("dist")

    def test_cli_uses_git_head(self) -> None:
        root = self.repository.root
        for command in (
            ["git", "init", "-q", "-b", "main"],
            ["git", "add", "-A"],
            ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-q", "-m", "fixture"],
        ):
            subprocess.run(command, cwd=root, check=True)
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
        output = root.parent / "cli-dist"
        self.assertEqual(build_index.main(["--output", str(output), "--root", str(root)]), 0)
        index = json.loads((output / "v1/index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["source_commit"], head)


if __name__ == "__main__":
    unittest.main()
