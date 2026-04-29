#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pydantic schemas for data_modules outputs.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError, ConfigDict


class EntityAppeared(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    type: str
    mentions: List[str] = Field(default_factory=list)
    confidence: float = 1.0


class EntityNew(BaseModel):
    model_config = ConfigDict(extra="allow")

    suggested_id: str
    name: str
    type: str
    tier: str = "装饰"


class StateChange(BaseModel):
    model_config = ConfigDict(extra="allow")

    entity_id: str
    field: str
    old: Optional[str] = None
    new: str
    reason: Optional[str] = None


class RelationshipNew(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    from_entity: str = Field(alias="from")
    to_entity: str = Field(alias="to")
    type: str
    description: Optional[str] = None
    chapter: Optional[int] = None


class UncertainCandidate(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    id: str


class UncertainMention(BaseModel):
    model_config = ConfigDict(extra="allow")

    mention: str
    candidates: List[UncertainCandidate] = Field(default_factory=list)
    confidence: float = 0.0
    adopted: Optional[str] = None


class TimelineEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    event: str
    chapter: Optional[int] = None
    time_hint: Optional[str] = None
    event_type: Optional[str] = None


class WorldRule(BaseModel):
    model_config = ConfigDict(extra="allow")

    rule: str
    scope: Optional[str] = None
    domain: Optional[str] = None
    field: Optional[str] = None


class OpenLoop(BaseModel):
    model_config = ConfigDict(extra="allow")

    content: str
    status: Optional[str] = None
    urgency: Optional[float] = None
    planted_chapter: Optional[int] = None
    expected_payoff: Optional[str] = None


class ReaderPromise(BaseModel):
    model_config = ConfigDict(extra="allow")

    content: str
    type: Optional[str] = None
    target: Optional[str] = None


class MemoryFacts(BaseModel):
    model_config = ConfigDict(extra="allow")

    timeline_events: List[TimelineEvent] = Field(default_factory=list)
    world_rules: List[WorldRule] = Field(default_factory=list)
    open_loops: List[OpenLoop] = Field(default_factory=list)
    reader_promises: List[ReaderPromise] = Field(default_factory=list)




class DataAgentOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    entities_appeared: List[EntityAppeared] = Field(default_factory=list)
    entities_new: List[EntityNew] = Field(default_factory=list)
    state_changes: List[StateChange] = Field(default_factory=list)
    relationships_new: List[RelationshipNew] = Field(default_factory=list)
    scenes_chunked: int = 0
    uncertain: List[UncertainMention] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    memory_facts: Optional[MemoryFacts] = None


class ErrorSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str
    message: str
    suggestion: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class StyleEvidence(BaseModel):
    model_config = ConfigDict(extra="allow")

    label: str
    detail: str
    excerpt: Optional[str] = None


class ReferenceBookMetrics(BaseModel):
    model_config = ConfigDict(extra="allow")

    sentence_avg_len: float = Field(ge=0)
    dialogue_ratio: float = Field(ge=0, le=1)
    chapter_count_estimate: int = Field(ge=0)


class ReferenceBookStyle(BaseModel):
    model_config = ConfigDict(extra="allow")

    pov: str
    primary_tense: str
    dialogue_tags: List[str] = Field(default_factory=list)
    lexical_markers: List[str] = Field(default_factory=list)


class ReferenceBookStructure(BaseModel):
    model_config = ConfigDict(extra="allow")

    opening_patterns: List[str] = Field(default_factory=list)
    ending_hook_patterns: List[str] = Field(default_factory=list)
    act_beats: List[str] = Field(default_factory=list)


class ReferenceBookAnalysis(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str
    book_id: str
    title: str
    author: Optional[str] = None
    source_path: str
    source_sha256: str
    analyzed_at: str
    metrics: ReferenceBookMetrics
    style: ReferenceBookStyle
    structure: ReferenceBookStructure
    evidence: List[StyleEvidence] = Field(default_factory=list)


class StableRule(BaseModel):
    model_config = ConfigDict(extra="allow")

    rule: str
    evidence_books: List[str] = Field(default_factory=list)


class RangedRule(BaseModel):
    model_config = ConfigDict(extra="allow")

    field: str
    min_value: float
    max_value: float
    unit: Optional[str] = None


class BookSpecificTrait(BaseModel):
    model_config = ConfigDict(extra="allow")

    book_id: str
    trait: str
    reason: Optional[str] = None


class ConflictResolution(BaseModel):
    model_config = ConfigDict(extra="allow")

    topic: str
    decision: str
    rationale: str


class MergedStyleProfile(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str
    profile_id: str
    strategy: str
    sources: List[str] = Field(default_factory=list)
    generated_at: str
    stable_rules: List[StableRule] = Field(default_factory=list)
    ranged_rules: List[RangedRule] = Field(default_factory=list)
    book_specific_traits: List[BookSpecificTrait] = Field(default_factory=list)
    conflict_resolutions: List[ConflictResolution] = Field(default_factory=list)
    writing_guidelines: List[str] = Field(default_factory=list)


def validate_data_agent_output(payload: Dict[str, Any]) -> DataAgentOutput:
    return DataAgentOutput.model_validate(payload)


def validate_reference_book_analysis(payload: Dict[str, Any]) -> ReferenceBookAnalysis:
    return ReferenceBookAnalysis.model_validate(payload)


def validate_merged_style_profile(payload: Dict[str, Any]) -> MergedStyleProfile:
    return MergedStyleProfile.model_validate(payload)


def format_validation_error(exc: ValidationError) -> Dict[str, Any]:
    return {
        "code": "SCHEMA_VALIDATION_FAILED",
        "message": "数据结构校验失败",
        "details": {"errors": exc.errors()},
        "suggestion": "请检查 data-agent 输出字段是否完整且类型正确",
    }


def normalize_data_agent_output(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    # 操作副本，避免修改调用方原始数据
    payload = dict(payload)

    def _ensure_list(key: str):
        value = payload.get(key)
        if value is None:
            payload[key] = []
        elif isinstance(value, list):
            return
        else:
            payload[key] = [value]

    for key in [
        "entities_appeared",
        "entities_new",
        "state_changes",
        "relationships_new",
        "uncertain",
        "warnings",
    ]:
        _ensure_list(key)

    memory_facts = payload.get("memory_facts")
    if memory_facts is None:
        payload["memory_facts"] = {}
    elif not isinstance(memory_facts, dict):
        payload["memory_facts"] = {}
    else:
        memory_facts = dict(memory_facts)
        payload["memory_facts"] = memory_facts
        for key in ["timeline_events", "world_rules", "open_loops", "reader_promises"]:
            value = memory_facts.get(key)
            if value is None:
                memory_facts[key] = []
            elif not isinstance(value, list):
                memory_facts[key] = [value]

    payload.setdefault("scenes_chunked", 0)

    return payload
