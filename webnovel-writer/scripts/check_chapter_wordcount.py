#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
章节字数检查脚本。

支持：
- 按章节号检查单章
- 批量检查项目下所有章节
- 文本 / JSON 输出
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from project_locator import resolve_project_root
from runtime_compat import enable_windows_utf8_stdio


def _positive_int(raw: str) -> int:
    value = int(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError("必须为正整数")
    return value

try:
    from chapter_paths import extract_chapter_num_from_filename, find_chapter_file
except ImportError:  # pragma: no cover
    from scripts.chapter_paths import extract_chapter_num_from_filename, find_chapter_file


def strip_markdown(text: str) -> str:
    """移除常见 Markdown 标记，保留正文文本。"""
    cleaned = text
    cleaned = re.sub(r"```[\s\S]*?```", "", cleaned)
    cleaned = re.sub(r"#{1,6}\s*", "", cleaned)
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*(.*?)\*", r"\1", cleaned)
    cleaned = re.sub(r"~~(.*?)~~", r"\1", cleaned)
    cleaned = re.sub(r"`(.*?)`", r"\1", cleaned)
    cleaned = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", cleaned)
    cleaned = re.sub(r"^---+$", "", cleaned, flags=re.MULTILINE)
    return cleaned


def count_chinese_words(text: str) -> int:
    """统计中文字符数（排除标点、空白和英文）。"""
    cleaned = strip_markdown(text)
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", cleaned)
    return len(chinese_chars)


def extract_content_from_chapter(file_path: Path) -> str:
    """提取章节正文，跳过常见章节标题行。"""
    content = file_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    content_start = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") and "章" in stripped:
            content_start = index + 1
            break

    return "\n".join(lines[content_start:])


def _relative_path(path: Path, project_root: Path) -> str:
    try:
        relative = path.resolve().relative_to(project_root.resolve())
        return relative.as_posix()
    except Exception:
        return str(path).replace("\\", "/")


def check_chapter_file(file_path: Path, project_root: Path, min_words: int = 3000) -> dict[str, Any]:
    """检查单个章节文件的字数。"""
    chapter_num = extract_chapter_num_from_filename(file_path.name)

    if not file_path.exists():
        return {
            "chapter": chapter_num,
            "file": str(file_path),
            "relative_path": _relative_path(file_path, project_root),
            "exists": False,
            "word_count": 0,
            "status": "error",
            "message": f"文件不存在: {file_path}",
        }

    main_content = extract_content_from_chapter(file_path)
    word_count = count_chinese_words(main_content)
    passed = word_count >= min_words

    return {
        "chapter": chapter_num,
        "file": str(file_path),
        "relative_path": _relative_path(file_path, project_root),
        "exists": True,
        "word_count": word_count,
        "status": "pass" if passed else "fail",
        "message": (
            f"字数: {word_count} (✓ 达标)"
            if passed
            else f"字数: {word_count} (✗ 不足，需要至少 {min_words} 字)"
        ),
    }


def check_chapter(project_root: Path, chapter_num: int, min_words: int = 3000) -> dict[str, Any]:
    """按章节号检查单章。"""
    chapter_file = find_chapter_file(project_root, chapter_num)
    if chapter_file is None:
        missing = project_root / "正文" / f"第{chapter_num:04d}章.md"
        return {
            "chapter": chapter_num,
            "file": str(missing),
            "relative_path": _relative_path(missing, project_root),
            "exists": False,
            "word_count": 0,
            "status": "error",
            "message": f"未找到第{chapter_num}章文件",
        }
    return check_chapter_file(chapter_file, project_root, min_words)


def find_all_chapter_files(project_root: Path, pattern: str = "第*.md") -> list[Path]:
    """扫描项目下所有章节文件。"""
    chapters_dir = project_root / "正文"
    if not chapters_dir.exists():
        return []

    chapter_files = [
        path
        for path in chapters_dir.rglob(pattern)
        if path.is_file() and extract_chapter_num_from_filename(path.name) is not None
    ]
    return sorted(
        chapter_files,
        key=lambda path: (extract_chapter_num_from_filename(path.name) or 0, str(path)),
    )


def check_all_chapters(project_root: Path, pattern: str = "第*.md", min_words: int = 3000) -> list[dict[str, Any]]:
    """批量检查所有章节。"""
    return [
        check_chapter_file(chapter_file, project_root, min_words)
        for chapter_file in find_all_chapter_files(project_root, pattern)
    ]


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result["status"] == "pass")
    failed = sum(1 for result in results if result["status"] == "fail")
    errors = sum(1 for result in results if result["status"] == "error")
    total_words = sum(int(result.get("word_count", 0) or 0) for result in results)

    if total == 0:
        status = "error"
    elif failed > 0 or errors > 0:
        status = "fail"
    else:
        status = "pass"

    return {
        "status": status,
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "total_words": total_words,
    }


def print_text_report(results: list[dict[str, Any]], *, min_words: int, project_root: Path) -> None:
    summary = summarize_results(results)

    print("\n" + "=" * 60)
    print("章节字数检查报告")
    print("=" * 60)
    print(f"项目: {project_root}")
    print(f"最低字数要求: {min_words}")

    if not results:
        print("\n⚠️  没有找到章节文件")
        return

    for result in results:
        if result["status"] == "pass":
            icon = "✅"
        elif result["status"] == "fail":
            icon = "⚠️"
        else:
            icon = "❌"

        label = result.get("relative_path") or result.get("file")
        chapter = result.get("chapter")
        chapter_prefix = f"第{chapter}章 - " if chapter else ""
        print(f"\n{icon} {chapter_prefix}{label}")
        print(f"   {result['message']}")

    print("\n" + "-" * 60)
    print(
        f"总计: {summary['total']} 章 | "
        f"{summary['passed']} 章达标 | "
        f"{summary['failed']} 章不足 | "
        f"{summary['errors']} 章错误 | "
        f"总字数: {summary['total_words']:,}"
    )
    print("-" * 60)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="检查章节字数是否达到最低要求")
    parser.add_argument("--project-root", type=str, help="项目根目录（可选，不传则自动探测）")
    parser.add_argument("--min-words", type=_positive_int, default=3000, help="最低字数要求（默认 3000）")
    parser.add_argument("--pattern", default="第*.md", help="批量扫描时使用的文件模式（默认 第*.md）")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="输出格式")

    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--chapter", type=_positive_int, help="按章节号检查单章")
    target_group.add_argument("--all", action="store_true", help="检查项目下全部章节")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    project_root = resolve_project_root(args.project_root) if args.project_root else resolve_project_root()

    if args.chapter is not None:
        results = [check_chapter(project_root, args.chapter, args.min_words)]
    else:
        results = check_all_chapters(project_root, args.pattern, args.min_words)

    payload = {
        "project_root": str(project_root),
        "min_words": int(args.min_words),
        "pattern": args.pattern,
        "results": results,
        "summary": summarize_results(results),
    }

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_text_report(results, min_words=args.min_words, project_root=project_root)

    raise SystemExit(0 if payload["summary"]["status"] == "pass" else 1)


if __name__ == "__main__":
    enable_windows_utf8_stdio(skip_in_pytest=True)
    main()
