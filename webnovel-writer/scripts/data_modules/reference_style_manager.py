#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reference Style Manager - 参考书分析与风格合并（MVP）

子命令：
- analyze: 分析单本参考书并落盘结构化结果
- merge: 合并多本分析结果，产出 merged profile + markdown 报告
- list: 列出已有分析
- show: 查看单本分析摘要
"""

from __future__ import annotations

import argparse
import hashlib
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import ValidationError

from .cli_args import normalize_global_project_root
from .cli_output import build_error, build_success, print_json
from .config import DataModulesConfig
from .schemas import (
    MergedStyleProfile,
    ReferenceBookAnalysis,
    validate_merged_style_profile,
    validate_reference_book_analysis,
)

SUPPORTED_EXTENSIONS = {".txt", ".md"}
DEFAULT_SCHEMA_VERSION = "refstyle.v1"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_book_id(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise argparse.ArgumentTypeError("book-id 不能为空")
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$", value):
        raise argparse.ArgumentTypeError("book-id 仅支持字母/数字/._-，且长度 1-64")
    return value


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"[。！？!?\n]+", text)
    return [part.strip() for part in parts if part.strip()]


def _count_chinese_chars(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def _detect_pov(text: str) -> str:
    first_person = text.count("我") + text.count("我们") + text.count("自己")
    third_person = (
        text.count("他")
        + text.count("她")
        + text.count("他们")
        + text.count("她们")
        + text.count("主角")
    )
    if first_person > third_person and first_person > 0:
        return "第一人称"
    if third_person > first_person and third_person > 0:
        return "第三人称"
    return "混合/不确定"


def _detect_tense(text: str) -> str:
    present_hits = len(re.findall(r"正在|此刻|现在|当下", text))
    past_hits = len(re.findall(r"当时|曾经|此前|后来", text))
    if present_hits > past_hits and present_hits > 0:
        return "现在时"
    if past_hits > present_hits and past_hits > 0:
        return "过去时"
    return "混合/不确定"


def _extract_dialogue_tags(text: str) -> list[str]:
    candidates = ["说道", "问道", "冷笑", "低声", "沉声", "喝道", "叹道", "笑道"]
    found = [tag for tag in candidates if tag in text]
    return found[:8]


def _extract_lexical_markers(text: str) -> list[str]:
    candidates = [
        "灵气",
        "斗气",
        "真气",
        "杀意",
        "威压",
        "心神",
        "识海",
        "因果",
        "命格",
        "天道",
        "伏笔",
        "反转",
    ]
    freq: list[tuple[str, int]] = []
    for token in candidates:
        count = text.count(token)
        if count > 0:
            freq.append((token, count))
    freq.sort(key=lambda item: (-item[1], item[0]))
    return [token for token, _ in freq[:10]]


def _extract_opening_patterns(text: str) -> list[str]:
    head = text[:1500]
    patterns: list[str] = []
    if any(word in head for word in ("清晨", "黎明", "夜色", "雨", "风")):
        patterns.append("环境开场")
    if any(word in head for word in ("忽然", "骤然", "下一刻", "危机")):
        patterns.append("事件突发开场")
    if any(word in head for word in ("他说", "问道", "开口")):
        patterns.append("对话开场")
    return patterns or ["常规叙述开场"]


def _extract_ending_hook_patterns(text: str) -> list[str]:
    tail = text[-1200:]
    patterns: list[str] = []
    if any(word in tail for word in ("未完", "下章", "下一刻", "然而")):
        patterns.append("悬念截断")
    if any(word in tail for word in ("惊变", "异变", "突变", "震动")):
        patterns.append("突发变故")
    if any(word in tail for word in ("决心", "誓言", "必须", "一定")):
        patterns.append("目标强化")
    return patterns or ["平稳收束"]


def _estimate_act_beats(text: str) -> list[str]:
    length = len(text)
    if length <= 0:
        return []
    beats = ["铺垫", "推进", "回钩"]
    if any(word in text for word in ("冲突", "战斗", "对决", "危机")):
        beats.insert(2, "冲突爆发")
    return beats


def _chapter_count_estimate(text: str) -> int:
    chapter_markers = re.findall(r"第\s*\d+\s*章", text)
    if chapter_markers:
        return len(chapter_markers)
    return max(1, text.count("\n# "))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _analysis_dir(config: DataModulesConfig) -> Path:
    return config.webnovel_dir / "reference_style" / "analyses"


def _merged_dir(config: DataModulesConfig) -> Path:
    return config.webnovel_dir / "reference_style" / "merged"


def _load_analysis(path: Path) -> ReferenceBookAnalysis:
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    return validate_reference_book_analysis(payload)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_analyze_payload(
    *,
    book_file: Path,
    book_id: str,
    title: Optional[str],
    author: Optional[str],
) -> ReferenceBookAnalysis:
    raw = book_file.read_text(encoding="utf-8")
    sentences = _split_sentences(raw)
    sentence_lengths = [_count_chinese_chars(sentence) for sentence in sentences]
    sentence_avg = float(statistics.mean(sentence_lengths)) if sentence_lengths else 0.0

    dialogue_chars = _count_chinese_chars("".join(re.findall(r"[“\"].*?[”\"]", raw, flags=re.S)))
    total_chars = max(_count_chinese_chars(raw), 1)
    dialogue_ratio = min(max(dialogue_chars / total_chars, 0.0), 1.0)

    lexical_markers = _extract_lexical_markers(raw)
    opening_patterns = _extract_opening_patterns(raw)
    ending_patterns = _extract_ending_hook_patterns(raw)

    evidence: list[dict[str, str]] = []
    evidence.append({"label": "句长统计", "detail": f"平均句长约 {sentence_avg:.1f} 中文字"})
    evidence.append({"label": "对话占比", "detail": f"对话占比约 {dialogue_ratio:.3f}"})
    if lexical_markers:
        evidence.append({"label": "高频风格词", "detail": "、".join(lexical_markers[:5])})

    payload = {
        "schema_version": DEFAULT_SCHEMA_VERSION,
        "book_id": book_id,
        "title": title or book_file.stem,
        "author": author,
        "source_path": str(book_file.resolve()),
        "source_sha256": _sha256(book_file),
        "analyzed_at": _now_iso(),
        "metrics": {
            "sentence_avg_len": round(sentence_avg, 3),
            "dialogue_ratio": round(dialogue_ratio, 4),
            "chapter_count_estimate": _chapter_count_estimate(raw),
        },
        "style": {
            "pov": _detect_pov(raw),
            "primary_tense": _detect_tense(raw),
            "dialogue_tags": _extract_dialogue_tags(raw),
            "lexical_markers": lexical_markers,
        },
        "structure": {
            "opening_patterns": opening_patterns,
            "ending_hook_patterns": ending_patterns,
            "act_beats": _estimate_act_beats(raw),
        },
        "evidence": evidence,
    }
    return validate_reference_book_analysis(payload)


def _merge_profiles(analyses: list[ReferenceBookAnalysis], strategy: str) -> MergedStyleProfile:
    if len(analyses) < 2:
        raise ValueError("merge 至少需要 2 份分析结果")

    source_ids = [item.book_id for item in analyses]

    pov_values = {item.style.pov for item in analyses}
    tense_values = {item.style.primary_tense for item in analyses}

    stable_rules: list[dict[str, Any]] = []
    conflict_resolutions: list[dict[str, str]] = []

    if len(pov_values) == 1:
        pov = next(iter(pov_values))
        stable_rules.append({"rule": f"叙事视角保持 {pov}", "evidence_books": source_ids})
    else:
        winner = sorted(pov_values)[0]
        conflict_resolutions.append(
            {
                "topic": "pov",
                "decision": winner,
                "rationale": f"{strategy} 策略下按字典序稳定选择（可后续人工覆写）",
            }
        )

    if len(tense_values) == 1:
        tense = next(iter(tense_values))
        stable_rules.append({"rule": f"时态以 {tense} 为主", "evidence_books": source_ids})
    else:
        winner = sorted(tense_values)[0]
        conflict_resolutions.append(
            {
                "topic": "primary_tense",
                "decision": winner,
                "rationale": f"{strategy} 策略下按字典序稳定选择（可后续人工覆写）",
            }
        )

    sentence_values = [item.metrics.sentence_avg_len for item in analyses]
    dialogue_values = [item.metrics.dialogue_ratio for item in analyses]

    ranged_rules = [
        {
            "field": "sentence_avg_len",
            "min_value": float(min(sentence_values)),
            "max_value": float(max(sentence_values)),
            "unit": "chars",
        },
        {
            "field": "dialogue_ratio",
            "min_value": float(min(dialogue_values)),
            "max_value": float(max(dialogue_values)),
            "unit": "ratio",
        },
    ]

    marker_sets = [set(item.style.lexical_markers) for item in analyses]
    stable_markers = sorted(set.intersection(*marker_sets)) if marker_sets else []
    if stable_markers:
        stable_rules.append(
            {
                "rule": f"高频词保持：{'、'.join(stable_markers[:6])}",
                "evidence_books": source_ids,
            }
        )

    trait_candidates: list[dict[str, str]] = []
    all_markers = set().union(*marker_sets) if marker_sets else set()
    for marker in sorted(all_markers):
        owners = [item.book_id for item in analyses if marker in item.style.lexical_markers]
        if len(owners) == 1:
            trait_candidates.append(
                {
                    "book_id": owners[0],
                    "trait": marker,
                    "reason": "仅在单本样书中高频出现",
                }
            )

    writing_guidelines = [
        "优先遵守 stable_rules，再在 ranged_rules 范围内调整句式。",
        "book_specific_traits 仅用于点缀，避免整章风格偏离主基线。",
        "若 conflict_resolutions 与当前题材冲突，先人工覆写再用于生成。",
    ]

    payload = {
        "schema_version": DEFAULT_SCHEMA_VERSION,
        "profile_id": f"merged-{'-'.join(source_ids)}",
        "strategy": strategy,
        "sources": source_ids,
        "generated_at": _now_iso(),
        "stable_rules": stable_rules,
        "ranged_rules": ranged_rules,
        "book_specific_traits": trait_candidates,
        "conflict_resolutions": conflict_resolutions,
        "writing_guidelines": writing_guidelines,
    }
    return validate_merged_style_profile(payload)


def _render_merge_report(profile: MergedStyleProfile) -> str:
    lines: list[str] = []
    lines.append("# 参考书风格合并报告")
    lines.append("")
    lines.append(f"- 生成时间：{profile.generated_at}")
    lines.append(f"- 策略：{profile.strategy}")
    lines.append(f"- 来源：{', '.join(profile.sources)}")
    lines.append("")

    lines.append("## 稳定规则")
    if profile.stable_rules:
        for item in profile.stable_rules:
            books = ", ".join(item.evidence_books)
            lines.append(f"- {item.rule}（来源：{books}）")
    else:
        lines.append("- 无")
    lines.append("")

    lines.append("## 范围规则")
    for item in profile.ranged_rules:
        lines.append(f"- {item.field}: {item.min_value:.4f} ~ {item.max_value:.4f} ({item.unit or '-'})")
    lines.append("")

    lines.append("## 单书特征")
    if profile.book_specific_traits:
        for item in profile.book_specific_traits:
            lines.append(f"- {item.book_id}: {item.trait}（{item.reason or '无'}）")
    else:
        lines.append("- 无")
    lines.append("")

    lines.append("## 冲突处理")
    if profile.conflict_resolutions:
        for item in profile.conflict_resolutions:
            lines.append(f"- {item.topic}: {item.decision}（{item.rationale}）")
    else:
        lines.append("- 无")
    lines.append("")

    lines.append("## 写作建议")
    for guideline in profile.writing_guidelines:
        lines.append(f"- {guideline}")
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="参考书分析与风格合并 CLI")
    parser.add_argument("--project-root", type=str, help="项目根目录（可选，不传则自动探测）")

    sub = parser.add_subparsers(dest="command", required=True)

    p_analyze = sub.add_parser("analyze", help="分析单本参考书")
    p_analyze.add_argument("--book", required=True, help="参考书文件路径（txt/md）")
    p_analyze.add_argument("--book-id", required=True, type=_safe_book_id, help="分析结果ID")
    p_analyze.add_argument("--title", help="书名（默认使用文件名）")
    p_analyze.add_argument("--author", help="作者")
    p_analyze.add_argument("--overwrite", action="store_true", help="允许覆盖已存在分析")
    p_analyze.add_argument("--format", choices=["text", "json"], default="text")

    p_merge = sub.add_parser("merge", help="合并多本分析")
    p_merge.add_argument("--book-ids", help="逗号分隔的 book_id 列表；不传则自动使用全部")
    p_merge.add_argument("--strategy", choices=["conservative", "balanced", "aggressive"], default="balanced")
    p_merge.add_argument("--format", choices=["text", "json"], default="text")

    p_list = sub.add_parser("list", help="列出分析结果")
    p_list.add_argument("--format", choices=["text", "json"], default="text")

    p_show = sub.add_parser("show", help="查看单本分析")
    p_show.add_argument("--book-id", required=True, type=_safe_book_id)
    p_show.add_argument("--format", choices=["text", "json"], default="text")

    return parser


def _resolve_config(project_root: Optional[str]) -> DataModulesConfig:
    from project_locator import resolve_project_root

    resolved = resolve_project_root(project_root) if project_root else resolve_project_root()
    return DataModulesConfig.from_project_root(resolved)


def _emit_text(payload: dict[str, Any]) -> None:
    if payload.get("status") == "success":
        message = payload.get("message", "ok")
        data = payload.get("data")
        print(message)
        if data is not None:
            import json

            print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    error = payload.get("error") or {}
    print(f"ERROR {error.get('code', 'UNKNOWN')}: {error.get('message', '未知错误')}")
    if error.get("suggestion"):
        print(f"建议: {error['suggestion']}")


def _analysis_summary(analysis: ReferenceBookAnalysis) -> dict[str, Any]:
    return {
        "book_id": analysis.book_id,
        "title": analysis.title,
        "author": analysis.author,
        "sentence_avg_len": analysis.metrics.sentence_avg_len,
        "dialogue_ratio": analysis.metrics.dialogue_ratio,
        "pov": analysis.style.pov,
        "primary_tense": analysis.style.primary_tense,
    }


def _list_analyses(config: DataModulesConfig) -> list[dict[str, Any]]:
    base = _analysis_dir(config)
    if not base.exists():
        return []

    records: list[dict[str, Any]] = []
    for path in sorted(base.glob("*.json")):
        try:
            analysis = _load_analysis(path)
        except Exception:
            continue
        record = _analysis_summary(analysis)
        record["updated_at"] = analysis.analyzed_at
        records.append(record)
    return records


def _run_analyze(args: argparse.Namespace, config: DataModulesConfig) -> tuple[dict[str, Any], int]:
    book_file = Path(args.book).expanduser()
    if not book_file.is_file():
        return (
            build_error("BOOK_NOT_FOUND", f"参考书不存在: {book_file}", suggestion="请检查 --book 路径"),
            1,
        )

    if book_file.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return (
            build_error("UNSUPPORTED_BOOK_FORMAT", "仅支持 txt/md 文件", suggestion="请先转换为 .txt 或 .md"),
            1,
        )

    out_path = _analysis_dir(config) / f"{args.book_id}.json"
    if out_path.exists() and not bool(args.overwrite):
        return (
            build_error("ANALYSIS_EXISTS", f"分析已存在: {args.book_id}", suggestion="使用 --overwrite 覆盖"),
            1,
        )

    try:
        analysis = _build_analyze_payload(
            book_file=book_file,
            book_id=args.book_id,
            title=args.title,
            author=args.author,
        )
    except ValidationError as exc:
        return (
            build_error(
                "SCHEMA_VALIDATION_FAILED",
                "分析结果结构校验失败",
                details={"errors": exc.errors()},
            ),
            1,
        )

    _write_json(out_path, analysis.model_dump(mode="json"))

    payload = build_success(
        {
            "analysis_file": str(out_path),
            "summary": _analysis_summary(analysis),
        },
        message="analysis_created",
    )
    return payload, 0


def _resolve_merge_inputs(config: DataModulesConfig, raw_book_ids: Optional[str]) -> tuple[list[ReferenceBookAnalysis], Optional[dict[str, Any]]]:
    base = _analysis_dir(config)
    if not base.exists():
        return [], build_error("ANALYSIS_DIR_MISSING", "尚无分析结果", suggestion="先执行 analyze")

    selected_ids: list[str]
    if raw_book_ids:
        selected_ids = [item.strip() for item in raw_book_ids.split(",") if item.strip()]
    else:
        selected_ids = [path.stem for path in sorted(base.glob("*.json"))]

    if len(selected_ids) < 2:
        return [], build_error("INSUFFICIENT_SOURCES", "merge 至少需要两本参考书", suggestion="增加 --book-ids 或先 analyze 更多样书")

    analyses: list[ReferenceBookAnalysis] = []
    missing: list[str] = []
    invalid: list[dict[str, Any]] = []
    for book_id in selected_ids:
        path = base / f"{book_id}.json"
        if not path.is_file():
            missing.append(book_id)
            continue
        try:
            analyses.append(_load_analysis(path))
        except ValidationError as exc:
            invalid.append({"book_id": book_id, "errors": exc.errors()})

    if missing:
        return [], build_error("ANALYSIS_NOT_FOUND", "部分 book_id 未找到", details={"missing": missing})
    if invalid:
        return [], build_error("ANALYSIS_INVALID", "部分分析文件结构非法", details={"invalid": invalid})
    return analyses, None


def _run_merge(args: argparse.Namespace, config: DataModulesConfig) -> tuple[dict[str, Any], int]:
    analyses, error_payload = _resolve_merge_inputs(config, args.book_ids)
    if error_payload is not None:
        return error_payload, 1

    try:
        profile = _merge_profiles(analyses, strategy=args.strategy)
    except ValueError as exc:
        return build_error("INSUFFICIENT_SOURCES", str(exc)), 1
    except ValidationError as exc:
        return (
            build_error(
                "SCHEMA_VALIDATION_FAILED",
                "合并结果结构校验失败",
                details={"errors": exc.errors()},
            ),
            1,
        )

    merged_dir = _merged_dir(config)
    profile_path = merged_dir / "merged_style_profile.json"
    report_path = merged_dir / "merge_report.md"

    _write_json(profile_path, profile.model_dump(mode="json"))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_merge_report(profile), encoding="utf-8")

    payload = build_success(
        {
            "profile_file": str(profile_path),
            "report_file": str(report_path),
            "summary": {
                "profile_id": profile.profile_id,
                "sources": profile.sources,
                "stable_rules": len(profile.stable_rules),
                "conflicts": len(profile.conflict_resolutions),
            },
        },
        message="merge_created",
    )
    return payload, 0


def _run_list(args: argparse.Namespace, config: DataModulesConfig) -> tuple[dict[str, Any], int]:
    records = _list_analyses(config)
    payload = build_success(records, message="analysis_list")
    return payload, 0


def _run_show(args: argparse.Namespace, config: DataModulesConfig) -> tuple[dict[str, Any], int]:
    path = _analysis_dir(config) / f"{args.book_id}.json"
    if not path.is_file():
        return build_error("ANALYSIS_NOT_FOUND", f"未找到分析: {args.book_id}"), 1

    try:
        analysis = _load_analysis(path)
    except ValidationError as exc:
        return (
            build_error(
                "ANALYSIS_INVALID",
                "分析文件结构非法",
                details={"errors": exc.errors()},
            ),
            1,
        )

    payload = build_success(
        {
            "summary": _analysis_summary(analysis),
            "structure": analysis.structure.model_dump(mode="json"),
            "evidence": [item.model_dump(mode="json") for item in analysis.evidence],
        },
        message="analysis_detail",
    )
    return payload, 0


def main() -> None:
    parser = build_parser()
    argv = normalize_global_project_root(sys.argv[1:])
    args = parser.parse_args(argv)

    config = _resolve_config(args.project_root)

    if args.command == "analyze":
        payload, code = _run_analyze(args, config)
    elif args.command == "merge":
        payload, code = _run_merge(args, config)
    elif args.command == "list":
        payload, code = _run_list(args, config)
    elif args.command == "show":
        payload, code = _run_show(args, config)
    else:
        payload, code = build_error("UNKNOWN_COMMAND", "未指定有效命令", suggestion="请查看 --help"), 2

    if getattr(args, "format", "text") == "json":
        print_json(payload)
    else:
        _emit_text(payload)

    raise SystemExit(code)


if __name__ == "__main__":
    main()
