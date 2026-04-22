#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Optional

from runtime_compat import normalize_windows_path

from init_project import init_project
from security_utils import atomic_write_json, read_json_safe, sanitize_filename

from .cli_args import normalize_global_project_root
from .cli_output import build_error, build_success, print_json

SUPPORTED_EXTENSIONS = {".md", ".txt"}
WORD_EXTENSIONS = {".doc", ".docx"}
IGNORED_SOURCE_DIR_NAMES = {".webnovel", ".claude", ".git", "设定集", "大纲", "审查报告"}
_FILENAME_CHAPTER_RE = re.compile(r"第\s*0*(?P<num>\d+)\s*章(?:\s*[-—_：: ]\s*(?P<title>[^\\/:*?\"<>|]+))?", re.IGNORECASE)
_FALLBACK_NUMBER_RE = re.compile(r"(?<!\d)(?P<num>\d{1,6})(?!\d)")


@dataclass(frozen=True)
class ParsedChapter:
    chapter_num: int
    title: str
    content: str
    source_file: Path
    detection: str
    priority: int


def _resolve_path(raw_path: str, *, workspace_root: Optional[str]) -> Path:
    value = normalize_windows_path(raw_path).expanduser()
    if value.is_absolute():
        return value.resolve()

    if workspace_root:
        base = normalize_windows_path(workspace_root).expanduser()
    else:
        base = Path.cwd()

    return (base / value).resolve()


def _iter_source_files(source_dir: Path) -> list[Path]:
    files = [
        path
        for path in source_dir.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_EXTENSIONS
        and not any(part in IGNORED_SOURCE_DIR_NAMES for part in path.relative_to(source_dir).parts[:-1])
    ]
    return sorted(files, key=lambda path: str(path.relative_to(source_dir)).lower())


def _iter_word_files(source_dir: Path) -> list[Path]:
    files = [
        path
        for path in source_dir.rglob("*")
        if path.is_file()
        and path.suffix.lower() in WORD_EXTENSIONS
        and not any(part in IGNORED_SOURCE_DIR_NAMES for part in path.relative_to(source_dir).parts[:-1])
    ]
    return sorted(files, key=lambda path: str(path.relative_to(source_dir)).lower())


def _resolve_docx_converter_script() -> Optional[Path]:
    scripts_dir = Path(__file__).resolve().parents[1]
    candidate = scripts_dir.parent / "skills" / "novel-docx2md" / "scripts" / "convert_docx_dir.py"
    if candidate.is_file():
        return candidate
    return None


def _convert_docx_dir_to_markdown(source_dir: Path, output_dir: Path) -> tuple[bool, str]:
    converter = _resolve_docx_converter_script()
    if converter is None:
        return False, "未找到 novel-docx2md 转换脚本"

    command = [
        sys.executable,
        str(converter),
        str(source_dir),
        "--output-dir",
        str(output_dir),
    ]
    process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip() or f"exit code {process.returncode}"
        return False, f"docx 转换失败: {detail}"

    return True, ""


def _copy_markdown_files(source_dir: Path, destination_dir: Path, files: list[Path]) -> None:
    for file_path in files:
        relative = file_path.relative_to(source_dir)
        output_path = destination_dir / relative
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file_path, output_path)


def _prepare_import_source_dir(source_dir: Path) -> tuple[Optional[Path], list[str], Optional[TemporaryDirectory[str]], Optional[str]]:
    markdown_files = _iter_source_files(source_dir)
    word_files = _iter_word_files(source_dir)

    if not markdown_files and not word_files:
        return None, [], None, "源目录中没有可导入章节（支持 .md/.txt/.docx）"

    if any(path.suffix.lower() == ".doc" for path in word_files):
        return None, [], None, "检测到 .doc 文件，当前仅支持 .docx；请先另存为 .docx 后重试"

    if not word_files:
        return source_dir, [], None, None

    nested_docx = [path for path in word_files if path.suffix.lower() == ".docx" and path.parent != source_dir]
    if nested_docx:
        return None, [], None, "当前仅支持 source-dir 根目录下的 .docx 文件；请先整理后重试"

    temp_dir = TemporaryDirectory(prefix="webnovel-import-docx-")
    prepared_dir = Path(temp_dir.name) / "prepared-source"
    prepared_dir.mkdir(parents=True, exist_ok=True)

    if markdown_files:
        _copy_markdown_files(source_dir, prepared_dir, markdown_files)

    ok, detail = _convert_docx_dir_to_markdown(source_dir, prepared_dir)
    if not ok:
        temp_dir.cleanup()
        return None, [], None, detail

    prepared_files = _iter_source_files(prepared_dir)
    if not prepared_files:
        temp_dir.cleanup()
        return None, [], None, "docx 转换后未生成可导入章节（.md/.txt）"

    warnings = [f"检测到 docx 输入，已自动转换为 Markdown：{len(word_files)} 文件"]
    if markdown_files:
        warnings.append("检测到混合输入（md/txt + docx），已合并后统一导入")

    return prepared_dir, warnings, temp_dir, None


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _strip_heading_prefix(line: str) -> str:
    return re.sub(r"^#+\s*", "", line.strip())


def _parse_from_filename(path: Path) -> tuple[Optional[int], str]:
    stem = path.stem
    match = _FILENAME_CHAPTER_RE.search(stem)
    if match:
        chapter_num = int(match.group("num"))
        title = (match.group("title") or "").strip()
        return chapter_num, title

    fallback_match = _FALLBACK_NUMBER_RE.search(stem)
    if fallback_match:
        chapter_num = int(fallback_match.group("num"))
        # 兼容: 第0001章-1-小传 / 第0002章-10-平儿来访 这类格式
        # 取第一个数字后面的内容作为标题候选
        rest = stem[fallback_match.end():].lstrip("-—_ ：:")
        return chapter_num, rest.strip()

    return None, ""


def _parse_from_first_line(content: str) -> tuple[Optional[int], str]:
    first_line = ""
    for line in content.splitlines():
        if line.strip():
            first_line = _strip_heading_prefix(line)
            break

    if not first_line:
        return None, ""

    match = _FILENAME_CHAPTER_RE.search(first_line)
    if not match:
        return None, ""

    chapter_num = int(match.group("num"))
    title = (match.group("title") or "").strip()
    return chapter_num, title


def _safe_title(title: str, fallback: str) -> str:
    preferred = title.strip() if title else fallback.strip()
    if not preferred:
        return ""
    safe = sanitize_filename(preferred, max_length=60)
    return "" if safe == "unnamed_entity" else safe


def _count_words(content: str) -> int:
    chinese_count = len(re.findall(r"[一-鿿]", content))
    latin_tokens = len(re.findall(r"[A-Za-z0-9]+", content))
    return chinese_count + latin_tokens


def _normalize_chapters(source_files: list[Path]) -> tuple[list[ParsedChapter], list[str]]:
    warnings: list[str] = []

    collected: list[dict[str, Any]] = []
    explicit_numbers: set[int] = set()

    for index, source_file in enumerate(source_files):
        content = _read_text(source_file)

        filename_num, filename_title = _parse_from_filename(source_file)
        first_line_num, first_line_title = _parse_from_first_line(content)

        if filename_num is not None:
            record = {
                "chapter_num": filename_num,
                "title": _safe_title(filename_title, ""),
                "content": content,
                "source_file": source_file,
                "detection": "filename",
                "priority": 0,
                "order": index,
            }
            explicit_numbers.add(filename_num)
        elif first_line_num is not None:
            record = {
                "chapter_num": first_line_num,
                "title": _safe_title(first_line_title, ""),
                "content": content,
                "source_file": source_file,
                "detection": "first_line",
                "priority": 1,
                "order": index,
            }
            explicit_numbers.add(first_line_num)
        else:
            record = {
                "chapter_num": None,
                "title": _safe_title("", source_file.stem),
                "content": content,
                "source_file": source_file,
                "detection": "fallback",
                "priority": 2,
                "order": index,
            }
            warnings.append(f"未识别章节号，按顺序补号: {source_file.name}")

        collected.append(record)

    next_fallback = 1
    normalized: list[dict[str, Any]] = []
    for record in collected:
        chapter_num = record["chapter_num"]
        if chapter_num is None:
            while next_fallback in explicit_numbers:
                next_fallback += 1
            chapter_num = next_fallback
            next_fallback += 1
        normalized.append({**record, "chapter_num": int(chapter_num)})

    winner_by_num: dict[int, dict[str, Any]] = {}
    for record in sorted(normalized, key=lambda item: (int(item["chapter_num"]), int(item["priority"]), int(item["order"]))):
        chapter_num = int(record["chapter_num"])
        existing = winner_by_num.get(chapter_num)
        if existing is None:
            winner_by_num[chapter_num] = record
            continue

        if int(record["priority"]) < int(existing["priority"]):
            warnings.append(
                f"章节冲突已替换: 第{chapter_num}章 使用 {record['source_file'].name} 覆盖 {existing['source_file'].name}"
            )
            winner_by_num[chapter_num] = record
        else:
            warnings.append(
                f"章节冲突已跳过: 第{chapter_num}章 忽略 {record['source_file'].name}"
            )

    chapters = [
        ParsedChapter(
            chapter_num=chapter_num,
            title=str(record["title"]),
            content=str(record["content"]).rstrip() + "\n",
            source_file=Path(record["source_file"]),
            detection=str(record["detection"]),
            priority=int(record["priority"]),
        )
        for chapter_num, record in sorted(winner_by_num.items(), key=lambda item: item[0])
    ]
    return chapters, warnings


def _chapter_output_path(project_root: Path, chapter: ParsedChapter) -> Path:
    chapter_filename = f"第{chapter.chapter_num:04d}章"
    if chapter.title:
        chapter_filename = f"{chapter_filename}-{chapter.title}"
    return project_root / "正文" / f"{chapter_filename}.md"


def _append_import_outline(project_root: Path, *, min_chapter: int, max_chapter: int, target_chapters: int) -> None:
    outline_path = project_root / "大纲" / "总纲.md"
    if not outline_path.exists():
        return

    marker = "## 导入信息（已有小说）"
    current_text = outline_path.read_text(encoding="utf-8")
    if marker in current_text:
        return

    pending_start = max_chapter + 1
    pending_range = (
        f"第{pending_start}-{target_chapters}章"
        if pending_start <= target_chapters
        else "已达到当前目标章数，可直接追加新目标后续写"
    )
    appendix = "\n".join(
        [
            marker,
            "",
            f"- 已导入范围（事实区）：第{min_chapter}-{max_chapter}章",
            f"- 待续写范围（规划区）：{pending_range}",
            "",
        ]
    )
    outline_path.write_text(current_text.rstrip() + "\n\n" + appendix, encoding="utf-8")


def _build_updated_state(
    state: dict[str, Any],
    *,
    title: str,
    genre: str,
    target_words: int,
    target_chapters: int,
    current_chapter: int,
    total_words: int,
    min_chapter: int,
) -> dict[str, Any]:
    project_info = dict(state.get("project_info") or {})
    progress = dict(state.get("progress") or {})

    existing_plan = list(progress.get("volumes_planned") or [])
    if not existing_plan:
        pending_start = current_chapter + 1
        if pending_start <= target_chapters:
            existing_plan = [
                f"已导入章节：第{min_chapter}-{current_chapter}章",
                f"待续写章节：第{pending_start}-{target_chapters}章",
            ]
        else:
            existing_plan = [f"已导入章节：第{min_chapter}-{current_chapter}章"]

    next_project_info = {
        **project_info,
        "title": title,
        "genre": genre,
        "target_words": int(target_words),
        "target_chapters": int(target_chapters),
    }
    next_progress = {
        **progress,
        "current_chapter": int(current_chapter),
        "total_words": int(total_words),
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "volumes_planned": existing_plan,
    }

    return {
        **state,
        "project_info": next_project_info,
        "progress": next_progress,
    }


def _emit_text(payload: dict[str, Any]) -> None:
    if payload.get("status") == "error":
        error = payload.get("error") or {}
        print(f"ERROR {error.get('code', 'UNKNOWN')}: {error.get('message', '未知错误')}")
        suggestion = error.get("suggestion")
        if suggestion:
            print(f"建议: {suggestion}")
        return

    data = payload.get("data") or {}
    print("import_novel_completed")
    print(f"project_root: {data.get('project_root', '')}")
    print(f"imported_chapters: {data.get('imported_chapters', 0)}")
    print(f"current_chapter: {data.get('current_chapter', 0)}")
    print(f"total_words: {data.get('total_words', 0)}")
    if data.get("warnings"):
        print("warnings:")
        for warning in data["warnings"]:
            print(f"- {warning}")


def _run_import(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    source_dir = _resolve_path(args.source_dir, workspace_root=args.workspace_root)
    target_dir = _resolve_path(args.target_dir, workspace_root=args.workspace_root)

    workspace_root: Optional[Path] = None
    if args.workspace_root:
        workspace_root = _resolve_path(args.workspace_root, workspace_root=None)
        try:
            source_dir.relative_to(workspace_root)
            target_dir.relative_to(workspace_root)
        except ValueError:
            return (
                build_error(
                    "OUTSIDE_WORKSPACE",
                    "源目录或目标目录不在 workspace-root 内",
                    suggestion="请调整 --source-dir/--target-dir 或 --workspace-root",
                ),
                1,
            )

    if not source_dir.is_dir():
        return (
            build_error("SOURCE_NOT_FOUND", f"源目录不存在: {source_dir}", suggestion="请检查 --source-dir 路径"),
            1,
        )

    if ".claude" in target_dir.parts:
        return (
            build_error("INVALID_TARGET_DIR", "不能在 .claude 目录内导入项目", suggestion="请更换 --target-dir"),
            1,
        )

    target_exists = target_dir.exists()
    target_has_entries = target_exists and any(target_dir.iterdir())
    if target_has_entries and not bool(args.overwrite):
        return (
            build_error(
                "TARGET_NOT_EMPTY",
                f"目标目录非空，拒绝覆盖: {target_dir}",
                suggestion="请清空目录或使用 --overwrite",
            ),
            1,
        )

    prepared_source_dir: Optional[Path] = None
    prepared_warnings: list[str] = []
    temp_source_ctx: Optional[TemporaryDirectory[str]] = None
    prepare_error: Optional[str] = None

    try:
        prepared_source_dir, prepared_warnings, temp_source_ctx, prepare_error = _prepare_import_source_dir(source_dir)
        if prepared_source_dir is None:
            message = prepare_error or "源目录中没有可导入章节（支持 .md/.txt/.docx）"
            return (
                build_error("NO_SOURCE_FILES", message, suggestion="请检查文件格式"),
                1,
            )

        source_files = _iter_source_files(prepared_source_dir)
        if not source_files:
            return (
                build_error("NO_SOURCE_FILES", "源目录中没有可导入章节（支持 .md/.txt/.docx）", suggestion="请检查文件格式"),
                1,
            )

        chapters, parse_warnings = _normalize_chapters(source_files)
        parse_warnings = [*prepared_warnings, *parse_warnings]
        if not chapters:
            return (
                build_error("NO_VALID_CHAPTERS", "未能解析有效章节", suggestion="请检查章节文件命名或首行格式"),
                1,
            )

        imported_total_words = sum(_count_words(chapter.content) for chapter in chapters)
        max_chapter = max(chapter.chapter_num for chapter in chapters)
        min_chapter = min(chapter.chapter_num for chapter in chapters)

        target_chapters = int(args.target_chapters) if args.target_chapters else max_chapter + 200
        target_words = int(args.target_words) if args.target_words else imported_total_words + 600_000

        if target_chapters <= 0:
            return (
                build_error("INVALID_TARGET_CHAPTERS", "target_chapters 必须大于 0", suggestion="请设置正整数目标章数"),
                1,
            )
        if target_words <= 0:
            return (
                build_error("INVALID_TARGET_WORDS", "target_words 必须大于 0", suggestion="请设置正整数目标字数"),
                1,
            )
        if target_chapters < max_chapter:
            return (
                build_error(
                    "TARGET_CHAPTERS_TOO_SMALL",
                    f"target_chapters({target_chapters}) 小于已导入最大章节({max_chapter})",
                    suggestion="请增大目标章数，或移除 --target-chapters 使用默认值",
                ),
                1,
            )

        try:
            import io
            from contextlib import redirect_stdout

            import security_utils as _security_utils  # lazy import to avoid global side-effects

            previous_git_flag = getattr(_security_utils, "_git_available", None)
            _security_utils._git_available = False

            try:
                with redirect_stdout(io.StringIO()):
                    init_project(
                        str(target_dir),
                        args.title,
                        args.genre,
                        protagonist_name=args.protagonist_name,
                        target_words=target_words,
                        target_chapters=target_chapters,
                    )
            finally:
                _security_utils._git_available = previous_git_flag
        except Exception as exc:
            return (
                build_error("INIT_FAILED", f"初始化项目失败: {exc}", suggestion="请检查参数后重试"),
                1,
            )

        for chapter in chapters:
            out_path = _chapter_output_path(target_dir, chapter)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(chapter.content, encoding="utf-8")

        _append_import_outline(
            target_dir,
            min_chapter=min_chapter,
            max_chapter=max_chapter,
            target_chapters=target_chapters,
        )

        state_path = target_dir / ".webnovel" / "state.json"
        state = read_json_safe(state_path, default={})
        next_state = _build_updated_state(
            state,
            title=args.title,
            genre=args.genre,
            target_words=target_words,
            target_chapters=target_chapters,
            current_chapter=max_chapter,
            total_words=imported_total_words,
            min_chapter=min_chapter,
        )
        atomic_write_json(state_path, next_state, use_lock=True, backup=False)

        data = {
            "project_root": str(target_dir),
            "source_dir": str(source_dir),
            "imported_chapters": len(chapters),
            "current_chapter": max_chapter,
            "total_words": imported_total_words,
            "next_chapter": max_chapter + 1,
            "warnings": parse_warnings,
            "next_steps": ["/webnovel-plan", "/webnovel-write"],
        }
        return build_success(data, message="import_novel_completed", warnings=parse_warnings or None), 0
    finally:
        if temp_source_ctx is not None:
            temp_source_ctx.cleanup()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="导入已有小说章节并生成可续写项目")
    parser.add_argument("--project-root", help="兼容参数（本命令不使用）")
    parser.add_argument("--workspace-root", help="工作区根目录（用于解析相对路径）")
    parser.add_argument("--source-dir", "--source", dest="source_dir", required=True, help="已有小说章节目录（md/txt/docx）")
    parser.add_argument("--target-dir", "--target", dest="target_dir", required=True, help="目标项目目录")
    parser.add_argument("--title", required=True, help="小说标题")
    parser.add_argument("--genre", required=True, help="小说题材")
    parser.add_argument("--protagonist-name", default="", help="主角姓名（可选）")
    parser.add_argument("--target-words", type=int, help="目标总字数（可选）")
    parser.add_argument("--target-chapters", type=int, help="目标总章数（可选）")
    parser.add_argument("--overwrite", action="store_true", help="允许在非空目标目录导入")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser


def main() -> None:
    parser = build_parser()
    argv = normalize_global_project_root(sys.argv[1:])
    args = parser.parse_args(argv)

    payload, exit_code = _run_import(args)

    if args.format == "json":
        print_json(payload)
    else:
        _emit_text(payload)

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
