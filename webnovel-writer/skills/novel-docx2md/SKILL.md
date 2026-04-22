---
name: novel-docx2md
description: 将目录下的 .docx 批量转换为 .md。只要用户提到“docx 转 md / Word 转 Markdown / 批量转换章节 / 转到同级 -md 目录”等场景，就应使用本技能；即使用户没有明确说“用技能”，也应主动触发。
---

# novel-docx2md

将指定目录中的 `.docx` 文件批量转换为 `.md`，默认输出到同级 `目录名-md`。

## 适用场景
- “把这个章节目录都转成 md”
- “Word 批量转 Markdown”
- “把 `xxx/章节` 转到同级 `xxx/章节-md`”

## 输入规则
- 必须提供源目录路径（支持中文路径）
- 可选提供输出目录路径

## 执行步骤
1. 解析用户提供的目录路径。
2. 若未提供输出目录，则使用默认输出目录：`<源目录同级>/<源目录名>-md`。
3. 调用脚本（使用相对路径）：

```bash
# 使用相对脚本路径执行
python "scripts/convert_docx_dir.py" "<源目录>"
```

如果用户指定输出目录：

```bash
python "scripts/convert_docx_dir.py" "<源目录>" --output-dir "<输出目录>"
```

4. 输出转换结果统计（converted / failed）和输出目录。

## 使用示例

### 示例 1（默认同级 -md 目录）
用户输入：
- `将 小说/章节 转成.md`

执行：
```bash
python "scripts/convert_docx_dir.py" "小说/章节"
```

结果目录：
- `小说/章节-md`

### 示例 2（自定义输出目录）
用户输入：
- `把 小说/章节 转成 md，输出到 小说/导出md`

执行：
```bash
python "scripts/convert_docx_dir.py" "小说/章节" --output-dir "小说/导出md"
```

## 说明
- 默认实现不依赖 pandoc，使用 Python 读取 `.docx` 内容并写入 `.md`。
- 保持文件名一致，仅扩展名从 `.docx` 变为 `.md`。
- 当输出目录不存在时会自动创建。
