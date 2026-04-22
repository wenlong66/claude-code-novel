#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from project_locator import resolve_project_root
from runtime_compat import normalize_windows_path
from security_utils import create_secure_directory, read_json_safe, sanitize_filename

from .cli_args import normalize_global_project_root
from .cli_output import build_error, build_success, print_json

try:
    from chapter_paths import extract_chapter_num_from_filename
except ImportError:  # pragma: no cover
    from scripts.chapter_paths import extract_chapter_num_from_filename


@dataclass(frozen=True)
class ChapterFile:
    chapter_num: int
    path: Path


def _positive_int(raw: str) -> int:
    value = int(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError("必须为正整数")
    return value


def _resolve_path(raw_path: str, *, project_root: Path) -> Path:
    value = normalize_windows_path(raw_path).expanduser()
    if value.is_absolute():
        return value.resolve()
    return (project_root / value).resolve()


def _default_title(project_root: Path) -> str:
    state = read_json_safe(project_root / ".webnovel" / "state.json", default={})
    title = str((state.get("project_info") or {}).get("title") or "").strip()
    if title:
        return title
    return project_root.name


def _default_filename(title: str) -> str:
    safe = sanitize_filename(title, max_length=80)
    return "book" if safe == "unnamed_entity" else safe


def _default_css_path() -> Path:
    scripts_dir = Path(__file__).resolve().parents[1]
    return scripts_dir / "ebook" / "templates" / "epub.css"


def _required_formats(fmt: str) -> list[str]:
    if fmt == "all":
        return ["epub", "azw3", "mobi"]
    return [fmt]


def _requires_calibre(formats: list[str]) -> bool:
    return "azw3" in formats or "mobi" in formats


def _tool_missing(name: str) -> bool:
    return shutil.which(name) is None


def find_chapter_files(project_root: Path, pattern: str) -> list[ChapterFile]:
    chapters_dir = project_root / "正文"
    if not chapters_dir.is_dir():
        return []

    candidates: list[ChapterFile] = []
    for path in chapters_dir.rglob(pattern):
        if not path.is_file():
            continue
        chapter_num = extract_chapter_num_from_filename(path.name)
        if chapter_num is None:
            continue
        candidates.append(ChapterFile(chapter_num=int(chapter_num), path=path.resolve()))

    return sorted(candidates, key=lambda item: (item.chapter_num, str(item.path)))


def _yaml_quote(text: str) -> str:
    escaped = text.replace('"', '\\"')
    return f'"{escaped}"'


def _assemble_markdown(
    output_path: Path,
    *,
    title: str,
    author: str,
    language: str,
    chapters: list[ChapterFile],
) -> None:
    now_year = str(datetime.now().year)
    chunks: list[str] = [
        "---",
        f"title: {_yaml_quote(title)}",
        f"author: {_yaml_quote(author)}",
        f"lang: {language}",
        f"date: {_yaml_quote(now_year)}",
        "---",
        "",
    ]

    for chapter in chapters:
        content = chapter.path.read_text(encoding="utf-8", errors="ignore").rstrip()
        chunks.append(content)
        chunks.append("")

    output_path.write_text("\n".join(chunks), encoding="utf-8")


def _run_command(command: list[str]) -> tuple[bool, str]:
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    if process.returncode == 0:
        return True, ""
    detail = process.stderr.strip() or process.stdout.strip() or f"exit code {process.returncode}"
    return False, detail


def _build_epub(
    *,
    assembled_file: Path,
    output_file: Path,
    css_path: Optional[Path],
    cover_image: Optional[Path],
    toc_depth: int,
) -> tuple[bool, str]:
    command = [
        "pandoc",
        str(assembled_file),
        "-o",
        str(output_file),
        "--toc",
        "--toc-depth",
        str(toc_depth),
        "--split-level=1",
    ]

    if css_path is not None and css_path.is_file():
        command.append(f"--css={css_path}")
    if cover_image is not None and cover_image.is_file():
        command.append(f"--epub-cover-image={cover_image}")

    return _run_command(command)


def _convert_from_epub(epub_file: Path, output_file: Path) -> tuple[bool, str]:
    return _run_command(["ebook-convert", str(epub_file), str(output_file)])


def _emit_text(payload: dict[str, Any]) -> None:
    if payload.get("status") == "error":
        error = payload.get("error") or {}
        print(f"ERROR {error.get('code', 'UNKNOWN')}: {error.get('message', '未知错误')}")
        suggestion = error.get("suggestion")
        if suggestion:
            print(f"建议: {suggestion}")
        return

    data = payload.get("data") or {}
    print(payload.get("message", "ebook_export_completed"))
    print(f"project_root: {data.get('project_root', '')}")
    print(f"output_dir: {data.get('output_dir', '')}")
    print("outputs:")
    for output in data.get("outputs", []):
        print(f"- {output}")
    warnings = payload.get("warnings") or []
    if warnings:
        print("warnings:")
        for warning in warnings:
            print(f"- {warning}")


def _run_export(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    project_root = resolve_project_root(args.project_root)

    formats = _required_formats(args.format)
    if _tool_missing("pandoc"):
        return (
            build_error(
                "PANDOC_NOT_FOUND",
                "未找到 pandoc",
                suggestion="请先安装 Pandoc 并加入 PATH",
            ),
            1,
        )

    if _requires_calibre(formats) and _tool_missing("ebook-convert"):
        return (
            build_error(
                "CALIBRE_NOT_FOUND",
                "请求格式需要 ebook-convert（Calibre）",
                suggestion="请安装 Calibre 并确保 ebook-convert 可执行",
            ),
            1,
        )

    chapters = find_chapter_files(project_root, args.chapter_pattern)
    if not chapters:
        return (
            build_error(
                "NO_CHAPTERS_FOUND",
                f"未找到可导出的章节文件（pattern={args.chapter_pattern}）",
                suggestion="请检查 正文/ 目录和 --chapter-pattern",
            ),
            1,
        )

    title = args.title or _default_title(project_root)
    filename = args.filename or _default_filename(title)
    output_dir = _resolve_path(args.output_dir, project_root=project_root)
    create_secure_directory(str(output_dir))

    css_path: Optional[Path] = None
    if args.css:
        css_path = _resolve_path(args.css, project_root=project_root)
    else:
        default_css = _default_css_path()
        if default_css.is_file():
            css_path = default_css

    cover_path: Optional[Path] = None
    warnings: list[str] = []
    if args.cover_image:
        cover_path = _resolve_path(args.cover_image, project_root=project_root)
        if not cover_path.is_file():
            warnings.append(f"封面文件不存在，已忽略: {cover_path}")
            cover_path = None

    if args.check_only:
        payload = build_success(
            {
                "project_root": str(project_root),
                "formats": formats,
                "chapters": len(chapters),
            },
            message="ebook_export_check_ok",
            warnings=warnings or None,
        )
        return payload, 0

    assembled_file = output_dir / "assembled.md"
    _assemble_markdown(
        assembled_file,
        title=title,
        author=args.author,
        language=args.language,
        chapters=chapters,
    )

    outputs: list[Path] = []
    epub_file = output_dir / f"{filename}.epub"

    if "epub" in formats:
        ok, detail = _build_epub(
            assembled_file=assembled_file,
            output_file=epub_file,
            css_path=css_path,
            cover_image=cover_path,
            toc_depth=args.toc_depth,
        )
        if not ok:
            return build_error("EPUB_BUILD_FAILED", f"生成 EPUB 失败: {detail}"), 1
        outputs.append(epub_file)

    if "azw3" in formats or "mobi" in formats:
        if not epub_file.exists():
            ok, detail = _build_epub(
                assembled_file=assembled_file,
                output_file=epub_file,
                css_path=css_path,
                cover_image=cover_path,
                toc_depth=args.toc_depth,
            )
            if not ok:
                return build_error("EPUB_BUILD_FAILED", f"生成 EPUB 失败: {detail}"), 1
            outputs.append(epub_file)

    if "azw3" in formats:
        azw3_file = output_dir / f"{filename}.azw3"
        ok, detail = _convert_from_epub(epub_file, azw3_file)
        if not ok:
            return build_error("FORMAT_CONVERT_FAILED", f"转换 AZW3 失败: {detail}"), 1
        outputs.append(azw3_file)

    if "mobi" in formats:
        mobi_file = output_dir / f"{filename}.mobi"
        ok, detail = _convert_from_epub(epub_file, mobi_file)
        if not ok:
            return build_error("FORMAT_CONVERT_FAILED", f"转换 MOBI 失败: {detail}"), 1
        outputs.append(mobi_file)

    if not args.keep_intermediate and assembled_file.exists():
        assembled_file.unlink()

    payload = build_success(
        {
            "project_root": str(project_root),
            "output_dir": str(output_dir),
            "outputs": [str(path) for path in outputs],
            "chapters": len(chapters),
            "formats": formats,
        },
        message="ebook_export_completed",
        warnings=warnings or None,
    )
    return payload, 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="导出小说 ebook（epub/azw3/mobi）")
    parser.add_argument("--project-root", help="项目根目录（可选，不传则自动探测）")
    parser.add_argument("--format", choices=["epub", "mobi", "azw3", "all"], default="epub", help="输出格式")
    parser.add_argument("--output-dir", default=".webnovel/ebook/build", help="输出目录（默认 .webnovel/ebook/build）")
    parser.add_argument("--filename", help="输出文件名（不含扩展名）")
    parser.add_argument("--title", help="书名（默认读取 state.project_info.title）")
    parser.add_argument("--author", default="Unknown Author", help="作者名")
    parser.add_argument("--language", default="zh-CN", help="语言代码")
    parser.add_argument("--chapter-pattern", default="第*.md", help="章节匹配模式")
    parser.add_argument("--cover-image", help="封面路径（可选）")
    parser.add_argument("--css", help="epub 样式表路径（可选）")
    parser.add_argument("--keep-intermediate", action="store_true", help="保留 assembled.md")
    parser.add_argument("--check-only", action="store_true", help="仅检查依赖与输入，不执行导出")
    parser.add_argument("--output-format", choices=["text", "json"], default="text", help="输出格式")
    parser.add_argument("--toc-depth", type=_positive_int, default=2, help="目录深度（当前保留参数）")
    return parser


def main() -> None:
    parser = build_parser()
    argv = normalize_global_project_root(sys.argv[1:])
    args = parser.parse_args(argv)

    payload, exit_code = _run_export(args)

    if args.output_format == "json":
        print_json(payload)
    else:
        _emit_text(payload)

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
