#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
import zipfile
from pathlib import Path

import pytest


def _ensure_scripts_on_path() -> None:
    scripts_dir = Path(__file__).resolve().parents[2]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def _load_module():
    _ensure_scripts_on_path()
    import data_modules.novel_import_manager as module

    return module


def _run_cli(module, monkeypatch, argv: list[str], *, capsys=None) -> int:
    if capsys is not None:
        capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["novel_import_manager", *argv])
    with pytest.raises(SystemExit) as exc:
        module.main()
    return int(exc.value.code or 0)


def _write_chapter(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_docx(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document_xml = "".join(
        [
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>",
            "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"><w:body>",
            *[
                f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>"
                for line in lines
            ],
            "</w:body></w:document>",
        ]
    )

    content_types = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">
  <Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>
  <Default Extension=\"xml\" ContentType=\"application/xml\"/>
  <Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>
</Types>
"""
    rels = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">
  <Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/>
</Relationships>
"""

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document_xml)


def test_import_rejects_non_empty_target_without_overwrite(tmp_path, monkeypatch, capsys):
    module = _load_module()

    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)

    _write_chapter(source_dir / "第1章-开端.md", "第一章内容")
    existing = target_dir / "existing.txt"
    existing.write_text("keep", encoding="utf-8")

    code = _run_cli(
        module,
        monkeypatch,
        [
            "--source-dir",
            str(source_dir),
            "--target-dir",
            str(target_dir),
            "--title",
            "测试书",
            "--genre",
            "都市脑洞",
            "--format",
            "json",
        ],
        capsys=capsys,
    )

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "TARGET_NOT_EMPTY"
    assert existing.read_text(encoding="utf-8") == "keep"


def test_import_creates_init_structure_and_maps_progress(tmp_path, monkeypatch, capsys):
    module = _load_module()

    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir(parents=True, exist_ok=True)

    _write_chapter(source_dir / "第1章-开局.md", "天亮了。主角出门。")
    _write_chapter(source_dir / "第2章-冲突.md", "冲突升级，线索出现。")

    code = _run_cli(
        module,
        monkeypatch,
        [
            "--source-dir",
            str(source_dir),
            "--target-dir",
            str(target_dir),
            "--title",
            "测试书",
            "--genre",
            "都市脑洞",
            "--target-chapters",
            "120",
            "--format",
            "json",
        ],
        capsys=capsys,
    )

    assert code == 0
    output_lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    payload = json.loads(output_lines[-1])
    assert payload["status"] == "success"
    assert payload["data"]["imported_chapters"] == 2
    assert payload["data"]["current_chapter"] == 2

    assert (target_dir / ".webnovel" / "state.json").is_file()
    assert (target_dir / "设定集" / "世界观.md").is_file()
    assert (target_dir / "大纲" / "总纲.md").is_file()
    assert (target_dir / "正文" / "第0001章-开局.md").is_file()
    assert (target_dir / "正文" / "第0002章-冲突.md").is_file()

    state = json.loads((target_dir / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    assert state["project_info"]["title"] == "测试书"
    assert state["project_info"]["genre"] == "都市脑洞"
    assert state["progress"]["current_chapter"] == 2
    assert state["progress"]["total_words"] > 0


def test_import_chapter_parsing_priority_and_fallback(tmp_path, monkeypatch, capsys):
    module = _load_module()

    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir(parents=True, exist_ok=True)

    _write_chapter(source_dir / "第10章-文件名优先.md", "正文A")
    _write_chapter(source_dir / "line-only.md", "# 第3章：首行识别\n正文B")
    _write_chapter(source_dir / "zzz.md", "无章节号正文C")

    code = _run_cli(
        module,
        monkeypatch,
        [
            "--source-dir",
            str(source_dir),
            "--target-dir",
            str(target_dir),
            "--title",
            "测试书",
            "--genre",
            "修仙",
            "--format",
            "json",
        ],
        capsys=capsys,
    )

    assert code == 0
    output_lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    payload = json.loads(output_lines[-1])
    assert payload["status"] == "success"

    # filename 优先识别为第10章
    assert (target_dir / "正文" / "第0010章-文件名优先.md").is_file()
    # 首行识别为第3章（包含标题）
    assert (target_dir / "正文" / "第0003章-首行识别.md").is_file()
    # fallback 补号，且会产生 warning
    warnings = payload.get("warnings") or payload["data"].get("warnings") or []
    assert any("按顺序补号" in item for item in warnings)


def test_import_parses_x_dash_number_pattern_as_numeric_chapter_order(tmp_path, monkeypatch, capsys):
    module = _load_module()

    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir(parents=True, exist_ok=True)

    # 用户反馈场景：x-x 格式，不能按字符串比较，应按数值比较
    _write_chapter(source_dir / "第0001章-1-小传.md", "正文1")
    _write_chapter(source_dir / "第0002章-10-平儿来访.md", "正文10")
    _write_chapter(source_dir / "第0003章-11-众人论古.md", "正文11")
    _write_chapter(source_dir / "第0013章-9-崩坏.md", "正文9")

    code = _run_cli(
        module,
        monkeypatch,
        [
            "--source-dir",
            str(source_dir),
            "--target-dir",
            str(target_dir),
            "--title",
            "测试书",
            "--genre",
            "都市脑洞",
            "--format",
            "json",
        ],
        capsys=capsys,
    )

    assert code == 0
    output_lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    payload = json.loads(output_lines[-1])
    assert payload["status"] == "success"

    generated = sorted(path.name for path in (target_dir / "正文").glob("*.md"))
    # 必须按章节数值生成，确保 13 > 2，且能识别 x-x 格式
    assert "第0001章-1-小传.md" in generated
    assert "第0002章-10-平儿来访.md" in generated
    assert "第0003章-11-众人论古.md" in generated
    assert "第0013章-9-崩坏.md" in generated


def test_import_rejects_paths_outside_workspace_root(tmp_path, monkeypatch, capsys):
    module = _load_module()

    workspace_dir = tmp_path / "workspace"
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True, exist_ok=True)

    _write_chapter(source_dir / "第1章-开端.md", "第一章内容")

    code = _run_cli(
        module,
        monkeypatch,
        [
            "--workspace-root",
            str(workspace_dir),
            "--source-dir",
            str(source_dir),
            "--target-dir",
            str(target_dir),
            "--title",
            "测试书",
            "--genre",
            "都市脑洞",
            "--format",
            "json",
        ],
        capsys=capsys,
    )

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "OUTSIDE_WORKSPACE"


def test_import_validates_target_chapters_not_below_existing(tmp_path, monkeypatch, capsys):
    module = _load_module()

    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir(parents=True, exist_ok=True)

    _write_chapter(source_dir / "第10章-开端.md", "第一章内容")

    code = _run_cli(
        module,
        monkeypatch,
        [
            "--source-dir",
            str(source_dir),
            "--target-dir",
            str(target_dir),
            "--title",
            "测试书",
            "--genre",
            "都市脑洞",
            "--target-chapters",
            "5",
            "--format",
            "json",
        ],
        capsys=capsys,
    )

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "TARGET_CHAPTERS_TOO_SMALL"


def test_import_overwrite_allows_non_empty_target(tmp_path, monkeypatch, capsys):
    module = _load_module()

    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)

    _write_chapter(source_dir / "第1章-开端.md", "第一章内容")
    (target_dir / "existing.txt").write_text("keep", encoding="utf-8")

    code = _run_cli(
        module,
        monkeypatch,
        [
            "--source-dir",
            str(source_dir),
            "--target-dir",
            str(target_dir),
            "--title",
            "测试书",
            "--genre",
            "都市脑洞",
            "--overwrite",
            "--format",
            "json",
        ],
        capsys=capsys,
    )

    assert code == 0
    output_lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    payload = json.loads(output_lines[-1])
    assert payload["status"] == "success"
    assert (target_dir / ".webnovel" / "state.json").is_file()


def test_import_docx_source_converts_and_imports(tmp_path, monkeypatch, capsys):
    module = _load_module()

    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir(parents=True, exist_ok=True)

    _write_docx(source_dir / "第4章-文档章.docx", ["第4章：文档章", "这是 docx 正文"])

    code = _run_cli(
        module,
        monkeypatch,
        [
            "--source-dir",
            str(source_dir),
            "--target-dir",
            str(target_dir),
            "--title",
            "测试书",
            "--genre",
            "都市脑洞",
            "--format",
            "json",
        ],
        capsys=capsys,
    )

    assert code == 0
    output_lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    payload = json.loads(output_lines[-1])
    assert payload["status"] == "success"
    warnings = payload.get("warnings") or payload["data"].get("warnings") or []
    assert any("已自动转换为 Markdown" in item for item in warnings)
    assert (target_dir / "正文" / "第0004章-文档章.md").is_file()


def test_import_rejects_doc_files_with_clear_message(tmp_path, monkeypatch, capsys):
    module = _load_module()

    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir(parents=True, exist_ok=True)

    (source_dir / "第1章-旧格式.doc").write_text("binary-placeholder", encoding="utf-8")

    code = _run_cli(
        module,
        monkeypatch,
        [
            "--source-dir",
            str(source_dir),
            "--target-dir",
            str(target_dir),
            "--title",
            "测试书",
            "--genre",
            "都市脑洞",
            "--format",
            "json",
        ],
        capsys=capsys,
    )

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "NO_SOURCE_FILES"
    assert ".doc" in payload["error"]["message"]
