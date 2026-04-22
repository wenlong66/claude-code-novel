#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def extract_docx_text(docx_path: Path) -> str:
    with zipfile.ZipFile(docx_path, "r") as zf:
        xml_data = zf.read("word/document.xml")

    root = ET.fromstring(xml_data)
    lines: list[str] = []

    for p in root.findall(".//w:body/w:p", NS):
        parts = [t.text or "" for t in p.findall(".//w:t", NS)]
        line = "".join(parts).strip()
        lines.append(line)

    normalized: list[str] = []
    prev_blank = False
    for line in lines:
        is_blank = line == ""
        if is_blank and prev_blank:
            continue
        normalized.append(line)
        prev_blank = is_blank

    text = "\n\n".join(normalized).strip()
    return text + ("\n" if text else "")


def resolve_paths(source_dir_raw: str, output_dir_raw: str | None) -> tuple[Path, Path]:
    src = Path(source_dir_raw).expanduser()
    if not src.is_absolute():
        src = (Path.cwd() / src).resolve()
    else:
        src = src.resolve()

    if output_dir_raw:
        out = Path(output_dir_raw).expanduser()
        if not out.is_absolute():
            out = (Path.cwd() / out).resolve()
        else:
            out = out.resolve()
    else:
        out = src.parent / f"{src.name}-md"

    return src, out


def convert_dir(source_dir: Path, output_dir: Path) -> tuple[int, int]:
    if not source_dir.exists() or not source_dir.is_dir():
        raise FileNotFoundError(f"source directory not found: {source_dir}")

    docx_files = sorted(source_dir.glob("*.docx"))
    output_dir.mkdir(parents=True, exist_ok=True)

    converted = 0
    failed = 0

    for docx_file in docx_files:
        md_path = output_dir / f"{docx_file.stem}.md"
        try:
            content = extract_docx_text(docx_file)
            md_path.write_text(content, encoding="utf-8")
            converted += 1
            print(f"OK: {docx_file.name} -> {md_path.name}")
        except Exception as e:
            failed += 1
            print(f"FAIL: {docx_file.name} ({e})", file=sys.stderr)

    return converted, failed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert all .docx files in a directory to .md files."
    )
    parser.add_argument("source_dir", help="Source directory containing .docx files")
    parser.add_argument(
        "--output-dir",
        help="Output directory. Default: sibling with '-md' suffix",
        default=None,
    )

    args = parser.parse_args()

    try:
        source_dir, output_dir = resolve_paths(args.source_dir, args.output_dir)
        converted, failed = convert_dir(source_dir, output_dir)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"DONE: converted={converted}, failed={failed}, output={output_dir}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
