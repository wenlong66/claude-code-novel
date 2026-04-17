#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
from pathlib import Path

import pytest


def _ensure_scripts_on_path() -> None:
    scripts_dir = Path(__file__).resolve().parents[2]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def _load_module():
    _ensure_scripts_on_path()
    import check_chapter_wordcount as module

    return module


def _create_project_root(tmp_path: Path) -> Path:
    project_root = tmp_path / "book"
    (project_root / ".webnovel").mkdir(parents=True, exist_ok=True)
    (project_root / ".webnovel" / "state.json").write_text("{}", encoding="utf-8")
    return project_root


def test_check_chapter_uses_existing_chapter_path_helper(tmp_path):
    module = _load_module()
    project_root = _create_project_root(tmp_path)

    chapter_file = project_root / "正文" / "第0003章-山雨欲来.md"
    chapter_file.parent.mkdir(parents=True, exist_ok=True)
    chapter_file.write_text("# 第3章 山雨欲来\n这是正文内容。", encoding="utf-8")

    result = module.check_chapter(project_root, 3, min_words=2)

    assert result["status"] == "pass"
    assert result["chapter"] == 3
    assert result["relative_path"] == "正文/第0003章-山雨欲来.md"
    assert result["word_count"] >= 6


def test_check_chapter_returns_error_when_chapter_is_missing(tmp_path):
    module = _load_module()
    project_root = _create_project_root(tmp_path)

    result = module.check_chapter(project_root, 12, min_words=3000)

    assert result["status"] == "error"
    assert result["chapter"] == 12
    assert "未找到第12章文件" in result["message"]


def test_check_all_chapters_filters_non_chapter_files_and_sorts_by_chapter(tmp_path):
    module = _load_module()
    project_root = _create_project_root(tmp_path)

    chapters_dir = project_root / "正文"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    (chapters_dir / "第0002章.md").write_text("# 第2章\n这是第二章内容", encoding="utf-8")
    (chapters_dir / "杂项说明.md").write_text("忽略我", encoding="utf-8")

    volume_dir = chapters_dir / "第1卷"
    volume_dir.mkdir(parents=True, exist_ok=True)
    (volume_dir / "第001章-开篇.md").write_text("# 第1章\n这是第一章内容", encoding="utf-8")

    results = module.check_all_chapters(project_root, min_words=2)

    assert [item["chapter"] for item in results] == [1, 2]
    assert all(item["status"] == "pass" for item in results)


def test_count_chinese_words_ignores_markdown_markup():
    module = _load_module()

    text = "# 标题\n**加粗**和[链接](https://example.com)还有`代码`\nEnglish 123\n中文内容"

    count = module.count_chinese_words(text)

    assert count == 15


def test_main_outputs_json_and_returns_nonzero_when_any_chapter_fails(tmp_path, monkeypatch, capsys):
    module = _load_module()
    project_root = _create_project_root(tmp_path)

    chapter_file = project_root / "正文" / "第0001章.md"
    chapter_file.parent.mkdir(parents=True, exist_ok=True)
    chapter_file.write_text("# 第1章\n字很少", encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_chapter_wordcount",
            "--project-root",
            str(project_root),
            "--chapter",
            "1",
            "--min-words",
            "10",
            "--format",
            "json",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        module.main()

    payload = json.loads(capsys.readouterr().out)
    assert int(exc.value.code or 0) == 1
    assert payload["summary"]["status"] == "fail"
    assert payload["results"][0]["chapter"] == 1


def test_build_parser_rejects_non_positive_numbers():
    module = _load_module()
    parser = module.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--chapter", "0"])

    with pytest.raises(SystemExit):
        parser.parse_args(["--all", "--min-words", "-1"])

