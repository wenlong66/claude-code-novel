# /novel-wordcount

显式执行章节字数检查命令。

## 用法

- `/novel-wordcount 12`
- `/novel-wordcount --all`
- `/novel-wordcount --all --min-words 3000`
- `/novel-wordcount 12 --format json`

## 执行要求

1. 这是一个**主动执行的 command**，被调用后直接完成字数检查，不要只解释命令本身。
2. 先解析真实书项目根（必须包含 `.webnovel/state.json`）。
3. 底层统一调用 `webnovel.py wordcount`，不要重复实现字数统计逻辑。
4. 默认只读，不修改项目文件。

## 参数处理

当前原始参数：`$ARGUMENTS`

按以下规则处理：

- 如果没有参数：使用 AskUserQuestion 追问用户要检查“单章”还是“全部章节”。
- 如果参数是单个正整数（例如 `12`）：视为 `--chapter 12`。
- 如果参数中已经包含 `--chapter` 或 `--all`：按原样透传。
- 允许附带透传这些参数：`--min-words <N>`、`--format <text|json>`、`--pattern <glob>`。
- 如果参数既不是单章号，也没有 `--chapter` / `--all`，先让用户澄清，再执行。

## 统一执行方式

先准备环境：

```bash
export WORKSPACE_ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
export SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/scripts"
export PROJECT_ROOT="$(python -X utf8 "${SCRIPTS_DIR}/webnovel.py" --project-root "${WORKSPACE_ROOT}" where)"
```

然后执行：

- 单章：
```bash
python -X utf8 "${SCRIPTS_DIR}/webnovel.py" --project-root "${PROJECT_ROOT}" wordcount --chapter <章号> ...
```

- 全量：
```bash
python -X utf8 "${SCRIPTS_DIR}/webnovel.py" --project-root "${PROJECT_ROOT}" wordcount --all ...
```

## 输出要求

- 文本模式：直接展示检查结果。
- JSON 模式：返回 JSON，并简短说明结论。
- 若退出码非 0，明确说明是“字数不足”或“文件缺失”等检查结果，不是命令崩溃。
