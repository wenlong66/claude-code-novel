---
name: webnovel-import
description: 将已有小说章节目录导入为 webnovel-writer 标准项目结构，并直接进入可续写状态。
allowed-tools: Bash Read AskUserQuestion
disable-model-invocation: true
---

# webnovel-import

把已有章节目录（`.md/.txt/.docx`）导入为标准项目（含 `.webnovel/state.json`、`设定集/`、`大纲/`、`正文/`）。

## 适用场景

- 已经有一批历史章节，希望迁移到 webnovel-writer 再继续写。
- 需要按 `/webnovel-init` 结构补齐项目骨架，但正文来自已有小说。

## 参数规则

必填：
- `--source-dir`：章节来源目录
- `--target-dir`：目标项目目录
- `--title`：书名
- `--genre`：题材

可选：
- `--protagonist-name`
- `--target-words`
- `--target-chapters`
- `--overwrite`（目标目录非空时允许导入）
- `--format text|json`

## 执行方式

先准备环境：

```bash
export WORKSPACE_ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
export SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/scripts"
```

执行导入：

```bash
python -X utf8 "${SCRIPTS_DIR}/webnovel.py" import-novel \
  --workspace-root "${WORKSPACE_ROOT}" \
  --source-dir "<source-dir>" \
  --target-dir "<target-dir>" \
  --title "<title>" \
  --genre "<genre>"
```

如需覆盖非空目录：

```bash
python -X utf8 "${SCRIPTS_DIR}/webnovel.py" import-novel \
  --workspace-root "${WORKSPACE_ROOT}" \
  --source-dir "<source-dir>" \
  --target-dir "<target-dir>" \
  --title "<title>" \
  --genre "<genre>" \
  --overwrite
```

## 导入后建议

- 先执行 `/webnovel-plan` 补齐后续规划。
- 再执行 `/webnovel-write <下一章>` 开始续写。

## 说明

- 默认支持 `.md/.txt`，并支持 `.docx` 自动转换后导入。
- 若输入包含 `.doc`，会直接报错并提示先另存为 `.docx`。
- 章节号识别优先：文件名 `第X章` > 首行 `第X章` > 文件顺序补号。
- 若出现同章节号冲突，保留优先级更高来源并在结果中给出 warning。
