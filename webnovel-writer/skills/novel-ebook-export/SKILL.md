---
name: novel-ebook-export
description: 封装 webnovel 统一 CLI 的 ebook 导出流程（epub/azw3/mobi）。当用户提到“导出电子书、生成 epub、生成 azw3/mobi、把小说打包成阅读器格式”时都应主动使用本技能。
allowed-tools: Bash Read
disable-model-invocation: true
---

# novel-ebook-export

将小说项目章节通过统一 CLI `webnovel.py ebook` 导出为 ebook 文件（`epub` / `azw3` / `mobi`）。

## 适用场景

- 用户要把 `正文/` 章节导出为 EPUB。
- 用户要一次性生成 Kindle 相关格式（AZW3/MOBI）。
- 用户要先做依赖体检（`--check-only`）再执行导出。

## 前置依赖

### 1) Pandoc（必需）

`ebook` 导出必须安装 Pandoc。

#### Windows

- 推荐：`winget install --id JohnMacFarlane.Pandoc -e`
- 备选：到官网下载安装包并安装：<https://pandoc.org/installing.html>

#### macOS

- Homebrew：`brew install pandoc`

#### Linux

- Debian/Ubuntu：`sudo apt-get update && sudo apt-get install -y pandoc`
- Fedora：`sudo dnf install -y pandoc`
- Arch：`sudo pacman -S pandoc`

#### 安装验证（必须执行）

```bash
pandoc --version
```

能输出版本号即安装成功。

### 2) Calibre / ebook-convert（`--format all` 需要）

当输出 `azw3` 或 `mobi`（例如 `--format all`）时，必须安装 `ebook-convert`（Calibre 提供）。

- 官网：<https://calibre-ebook.com/download>
- 安装后验证：

```bash
ebook-convert --version
```

## 执行方式

先准备环境变量：

```bash
export WORKSPACE_ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
export SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/scripts"
```

### 示例 1：导出 EPUB（最常用）

```bash
python -X utf8 "${SCRIPTS_DIR}/webnovel.py" --project-root "${WORKSPACE_ROOT}" ebook --format epub
```

### 示例 2：导出全部格式（epub + azw3 + mobi）

```bash
python -X utf8 "${SCRIPTS_DIR}/webnovel.py" --project-root "${WORKSPACE_ROOT}" ebook --format all
```

> 注意：`--format all` 需要 `ebook-convert` 可用。

### 示例 3：仅检查依赖与输入（不生成文件）

```bash
python -X utf8 "${SCRIPTS_DIR}/webnovel.py" --project-root "${WORKSPACE_ROOT}" ebook --format all --check-only --output-format json
```

## 常用可选参数

- `--output-dir <目录>`：指定输出目录（默认 `.webnovel/ebook/build`）
- `--filename <文件名>`：指定输出文件名（不含扩展名）
- `--title <书名>` / `--author <作者>` / `--language <语言代码>`
- `--cover-image <路径>`：设置封面
- `--css <路径>`：覆盖默认 epub 样式
- `--keep-intermediate`：保留中间文件 `assembled.md`
- `--output-format text|json`：输出格式

## 结果检查

导出成功后，重点检查：

- 输出目录下是否存在目标文件（如 `.epub/.azw3/.mobi`）
- 命令返回码是否为 0
- 若失败，先用 `--check-only` 定位依赖问题（优先检查 pandoc / ebook-convert）
