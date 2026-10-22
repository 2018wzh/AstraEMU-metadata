# AstraEMU-metadata

AstraEMU Manager 使用的公开数据：兼容性记录、推荐配置、核心目录和汉化补丁。数据经 GitHub Pages 发布在 `https://2018wzh.github.io/AstraEMU-metadata/v1/`，Manager 在允许联网后按 `index.json` 增量同步。

## 目录

| 路径 | 内容 |
|---|---|
| `compatibility/entries/<vid>/<rid>/<plugin_id>.json` | 一条兼容性记录。每个 VNDB 发行版本（rID）和模拟器组合一个文件 |
| `engines/presets/<rid>/<plugin_id>.json` | 推荐配置，维护者通过 PR 编写 |
| `engines/cores/<plugin_id>.json` | 核心下载目录，由主仓发布工作流开 PR 更新 |
| `patches/` | 汉化补丁目录 `catalog.json`、补丁脚本和 `common/` 公共脚本 |
| `schema/` | JSON Schema，由主仓 `astra-emu-metadata` crate 的 `export_schemas` 生成，不要手改 |
| `tools/` | 校验、生成发布目录、处理 issue 的脚本 |

模拟器 plugin_id：`rfvp`、`siglus_rs`、`art3m1s-core`、`astra.emu.musica`、`sena-rs`、`ethornell-rs`、`kirikiroid2-web`。

兼容性分五级：`perfect`（完美运行）、`completable`（可通关）、`flawed`（有瑕疵）、`boot_only`（仅能启动）、`unplayable`（无法运行）。

## 提交兼容性报告

1. 在 Manager 的作品详情→兼容性中点「报告兼容性」，或直接新建“兼容性报告” issue。
2. 维护者核对后加上 `compat:accepted` 标签。
3. `issue-intake` 工作流把表单转换成条目文件，在 `compat/issue-<编号>` 分支开 PR；表单有误时会在 issue 下列出原因并移除标签。
4. PR 合并后 `publish` 工作流重新生成并发布数据。

## 本地使用

需要 Python 3.10 及以上和 `jsonschema`：

```sh
python -m pip install jsonschema
python tools/validate.py
python -m unittest
python tools/build_index.py --output dist
```

`build_index.py` 输出 `dist/v1/`：`index.json`、`compatibility.json`、`presets.json`、`cores.json` 和 `patches/`。`index.json` 记录每个文件的 sha256 与大小，`source_commit` 取 `git rev-parse HEAD`，生成时间取 HEAD 的提交时间，同一提交两次生成的结果逐字节相同。

处理单个 issue 正文：

```sh
python tools/issue_to_entry.py --body-file body.md --issue 12 --labeled-at 2026-10-20T08:00:00Z
```

## 更新 schema

schema 以 Rust 类型为准。在 AstraEngine 主仓运行：

```sh
cargo run --manifest-path Emulator/Cargo.toml -p astra-emu-metadata --example export_schemas -- <本仓库>/schema
```

## 许可

数据采用 CC0-1.0；补丁脚本与工具采用 MIT OR Apache-2.0。详见 `LICENSE` 与 `LICENSES/`。
