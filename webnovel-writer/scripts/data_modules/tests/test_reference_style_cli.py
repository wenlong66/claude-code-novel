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
    import data_modules.reference_style_manager as module

    return module


def _create_project_root(tmp_path: Path) -> Path:
    project_root = (tmp_path / "book").resolve()
    (project_root / ".webnovel").mkdir(parents=True, exist_ok=True)
    (project_root / ".webnovel" / "state.json").write_text("{}", encoding="utf-8")
    return project_root


def _run_cli(module, monkeypatch, argv: list[str]) -> int:
    monkeypatch.setattr(sys, "argv", ["reference_style_manager", *argv])
    with pytest.raises(SystemExit) as exc:
        module.main()
    return int(exc.value.code or 0)


def test_analyze_writes_schema_valid_payload(tmp_path, monkeypatch, capsys):
    module = _load_module()
    project_root = _create_project_root(tmp_path)

    book_file = tmp_path / "book1.txt"
    book_file.write_text(
        """# 第一章\n清晨的风吹过山门。\n“你来了？”他低声说道。\n下一刻，危机骤然降临。\n""",
        encoding="utf-8",
    )

    code = _run_cli(
        module,
        monkeypatch,
        [
            "--project-root",
            str(project_root),
            "analyze",
            "--book",
            str(book_file),
            "--book-id",
            "book1",
            "--format",
            "json",
        ],
    )
    assert code == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"
    analysis_file = Path(payload["data"]["analysis_file"])
    assert analysis_file.is_file()

    saved = json.loads(analysis_file.read_text(encoding="utf-8"))
    validated = module.validate_reference_book_analysis(saved)
    assert validated.book_id == "book1"
    assert validated.metrics.sentence_avg_len >= 0


def test_analyze_rejects_unsupported_extension(tmp_path, monkeypatch):
    module = _load_module()
    project_root = _create_project_root(tmp_path)

    book_file = tmp_path / "book1.docx"
    book_file.write_text("dummy", encoding="utf-8")

    code = _run_cli(
        module,
        monkeypatch,
        [
            "--project-root",
            str(project_root),
            "analyze",
            "--book",
            str(book_file),
            "--book-id",
            "book1",
            "--format",
            "json",
        ],
    )
    assert code == 1


def test_merge_requires_at_least_two_sources(tmp_path, monkeypatch, capsys):
    module = _load_module()
    project_root = _create_project_root(tmp_path)

    book_file = tmp_path / "book1.md"
    book_file.write_text("第一章\n他看向山门。", encoding="utf-8")

    assert (
        _run_cli(
            module,
            monkeypatch,
            [
                "--project-root",
                str(project_root),
                "analyze",
                "--book",
                str(book_file),
                "--book-id",
                "book1",
                "--format",
                "json",
            ],
        )
        == 0
    )
    capsys.readouterr()

    code = _run_cli(
        module,
        monkeypatch,
        [
            "--project-root",
            str(project_root),
            "merge",
            "--book-ids",
            "book1",
            "--format",
            "json",
        ],
    )
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "INSUFFICIENT_SOURCES"


def test_merge_creates_profile_and_report(tmp_path, monkeypatch, capsys):
    module = _load_module()
    project_root = _create_project_root(tmp_path)

    book1 = tmp_path / "book1.md"
    book2 = tmp_path / "book2.txt"
    book1.write_text("""清晨，风雨欲来。\n“走！”他说道。\n下一刻异变突起。""", encoding="utf-8")
    book2.write_text("""夜色沉沉。\n她低声问道：“你确定？”\n然而危机刚刚开始。""", encoding="utf-8")

    for book_id, path in (("book1", book1), ("book2", book2)):
        assert (
            _run_cli(
                module,
                monkeypatch,
                [
                    "--project-root",
                    str(project_root),
                    "analyze",
                    "--book",
                    str(path),
                    "--book-id",
                    book_id,
                    "--format",
                    "json",
                ],
            )
            == 0
        )
        capsys.readouterr()

    code = _run_cli(
        module,
        monkeypatch,
        [
            "--project-root",
            str(project_root),
            "merge",
            "--book-ids",
            "book1,book2",
            "--strategy",
            "balanced",
            "--format",
            "json",
        ],
    )
    assert code == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"

    profile_path = Path(payload["data"]["profile_file"])
    report_path = Path(payload["data"]["report_file"])
    assert profile_path.is_file()
    assert report_path.is_file()

    profile_payload = json.loads(profile_path.read_text(encoding="utf-8"))
    validated = module.validate_merged_style_profile(profile_payload)
    assert validated.sources == ["book1", "book2"]
    assert validated.strategy == "balanced"


def test_list_and_show_return_expected_records(tmp_path, monkeypatch, capsys):
    module = _load_module()
    project_root = _create_project_root(tmp_path)

    book_file = tmp_path / "book1.txt"
    book_file.write_text("清晨。\n他说道：出发。", encoding="utf-8")

    assert (
        _run_cli(
            module,
            monkeypatch,
            [
                "--project-root",
                str(project_root),
                "analyze",
                "--book",
                str(book_file),
                "--book-id",
                "book1",
                "--format",
                "json",
            ],
        )
        == 0
    )
    capsys.readouterr()

    assert (
        _run_cli(
            module,
            monkeypatch,
            ["--project-root", str(project_root), "list", "--format", "json"],
        )
        == 0
    )
    list_payload = json.loads(capsys.readouterr().out)
    assert list_payload["status"] == "success"
    assert len(list_payload["data"]) == 1
    assert list_payload["data"][0]["book_id"] == "book1"

    assert (
        _run_cli(
            module,
            monkeypatch,
            [
                "--project-root",
                str(project_root),
                "show",
                "--book-id",
                "book1",
                "--format",
                "json",
            ],
        )
        == 0
    )
    show_payload = json.loads(capsys.readouterr().out)
    assert show_payload["status"] == "success"
    assert show_payload["data"]["summary"]["book_id"] == "book1"
