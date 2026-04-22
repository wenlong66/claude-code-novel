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
    import data_modules.ebook_export_manager as module

    return module


def _create_project_root(tmp_path: Path) -> Path:
    project_root = (tmp_path / "book").resolve()
    (project_root / ".webnovel").mkdir(parents=True, exist_ok=True)
    (project_root / ".webnovel" / "state.json").write_text(
        json.dumps(
            {
                "project_info": {
                    "title": "凡人资本论",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chapters_dir = project_root / "正文"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    (chapters_dir / "第0002章-测试二.md").write_text("# 第2章\n第二章内容", encoding="utf-8")
    (chapters_dir / "第0001章-测试一.md").write_text("# 第1章\n第一章内容", encoding="utf-8")
    return project_root


def _run_cli(module, monkeypatch, argv: list[str], *, capsys=None) -> int:
    if capsys is not None:
        capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["ebook_export_manager", *argv])
    with pytest.raises(SystemExit) as exc:
        module.main()
    return int(exc.value.code or 0)


def test_check_only_reports_missing_calibre_for_all_format(tmp_path, monkeypatch, capsys):
    module = _load_module()
    project_root = _create_project_root(tmp_path)

    monkeypatch.setattr(module.shutil, "which", lambda name: "C:/ok/tool.exe" if name == "pandoc" else None)

    code = _run_cli(
        module,
        monkeypatch,
        [
            "--project-root",
            str(project_root),
            "--format",
            "all",
            "--check-only",
            "--output-format",
            "json",
        ],
        capsys=capsys,
    )

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "CALIBRE_NOT_FOUND"


def test_check_only_succeeds_when_tools_ready(tmp_path, monkeypatch, capsys):
    module = _load_module()
    project_root = _create_project_root(tmp_path)

    monkeypatch.setattr(module.shutil, "which", lambda _name: "C:/ok/tool.exe")

    code = _run_cli(
        module,
        monkeypatch,
        [
            "--project-root",
            str(project_root),
            "--format",
            "epub",
            "--check-only",
            "--output-format",
            "json",
        ],
        capsys=capsys,
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"
    assert payload["message"] == "ebook_export_check_ok"


def test_find_chapter_files_sorted_by_chapter_num(tmp_path):
    module = _load_module()
    project_root = _create_project_root(tmp_path)

    chapters = module.find_chapter_files(project_root, "第*.md")

    assert [item.chapter_num for item in chapters] == [1, 2]
    assert chapters[0].path.name.startswith("第0001章")


def test_build_command_invokes_pandoc_and_outputs_epub(tmp_path, monkeypatch, capsys):
    module = _load_module()
    project_root = _create_project_root(tmp_path)

    monkeypatch.setattr(module.shutil, "which", lambda _name: "C:/ok/tool.exe")

    called: list[list[str]] = []

    def _fake_run(cmd, capture_output, text, encoding, errors):
        called.append(list(cmd))

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        out_idx = cmd.index("-o") + 1
        Path(cmd[out_idx]).write_text("epub-bytes", encoding="utf-8")
        return _Result()

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    out_dir = project_root / ".webnovel" / "ebook" / "build"
    code = _run_cli(
        module,
        monkeypatch,
        [
            "--project-root",
            str(project_root),
            "--format",
            "epub",
            "--output-format",
            "json",
            "--output-dir",
            str(out_dir),
        ],
        capsys=capsys,
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"
    outputs = payload["data"]["outputs"]
    assert len(outputs) == 1
    assert outputs[0].endswith(".epub")
    assert any(cmd and cmd[0] == "pandoc" for cmd in called)


def test_text_output_is_human_readable(tmp_path, monkeypatch, capsys):
    module = _load_module()
    project_root = _create_project_root(tmp_path)

    monkeypatch.setattr(module.shutil, "which", lambda _name: "C:/ok/tool.exe")

    def _fake_run(cmd, capture_output, text, encoding, errors):
        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        out_idx = cmd.index("-o") + 1
        Path(cmd[out_idx]).write_text("epub-bytes", encoding="utf-8")
        return _Result()

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    code = _run_cli(
        module,
        monkeypatch,
        [
            "--project-root",
            str(project_root),
            "--format",
            "epub",
            "--output-format",
            "text",
        ],
        capsys=capsys,
    )

    assert code == 0
    output = capsys.readouterr().out
    assert "ebook_export_completed" in output
    assert "outputs:" in output
