import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Literal, Mapping, Optional, Sequence

from src.memory.procedural_candidates import (
    SkillCandidateRecord,
    SkillCandidateStatus,
    SkillCandidateValidationError,
    SkillCandidateWrite,
    ProceduralSkillCandidateStore,
    validate_skill_candidate_write,
)
from src.memory.skill_store import SkillVersionStore


ProceduralDedupAction = Literal["NEW", "DUPLICATE", "UPDATE", "MERGE"]
VALID_PROCEDURAL_DEDUP_ACTIONS = {"NEW", "DUPLICATE", "UPDATE", "MERGE"}

STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "when",
    "then",
    "into",
    "from",
    "use",
    "user",
    "asks",
    "asked",
    "workflow",
    "skill",
}


@dataclass(frozen=True)
class ProceduralDedupInput:
    incoming: SkillCandidateWrite
    source_episode_id: str
    source_job_id: Optional[str]
    llm_route_payload: Mapping[str, Any]


@dataclass(frozen=True)
class ProceduralDedupMatch:
    candidate_id: str
    title: str
    trigger_score: float
    tool_score: float
    tag_score: float
    category_score: float
    title_score: float
    total_score: float
    status: SkillCandidateStatus | str
    source_type: str = "candidate"


@dataclass(frozen=True)
class ProceduralDedupDecision:
    action: ProceduralDedupAction
    target_candidate_id: Optional[str] = None
    merged_candidate_ids: List[str] = field(default_factory=list)
    reason: str = ""
    confidence: float = 0.5


def tokenize_for_procedural_dedup(text: str) -> set[str]:
    tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", str(text or "").lower())
        if len(token) >= 3 and token not in STOP_WORDS
    }
    return tokens


def jaccard_score(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def overlap_score(left: Sequence[str], right: Sequence[str]) -> float:
    left_set = {str(item).strip().lower() for item in left if str(item).strip()}
    right_set = {str(item).strip().lower() for item in right if str(item).strip()}
    if not left_set and not right_set:
        return 0.0
    denominator = max(len(left_set), len(right_set), 1)
    return len(left_set & right_set) / denominator


def _extract_json_value(text: str) -> Any:
    content = str(text or "").strip()
    if content.startswith("```json"):
        content = content[7:].strip()
        if content.endswith("```"):
            content = content[:-3].strip()
    elif content.startswith("```"):
        content = content[3:].strip()
        if content.endswith("```"):
            content = content[:-3].strip()
    return json.loads(content)


class ProceduralDedupService:
    def __init__(
        self,
        *,
        db_path: Optional[Path] = None,
        candidate_store: Optional[ProceduralSkillCandidateStore] = None,
        skill_store: Optional[SkillVersionStore] = None,
    ):
        self.db_path = db_path
        self.candidate_store = candidate_store or ProceduralSkillCandidateStore(db_path=db_path)
        self.skill_store = skill_store or SkillVersionStore(db_path=db_path)

    def shortlist(self, incoming: SkillCandidateWrite, limit: int = 10) -> List[ProceduralDedupMatch]:
        normalized = validate_skill_candidate_write(incoming)
        matches: List[ProceduralDedupMatch] = []
        for candidate in self.candidate_store.list_recent(limit=250):
            if candidate.status in {"PROMOTED", "REJECTED", "WAITING_FOR_APPROVAL"}:
                continue
            match = self._score_candidate(normalized, candidate)
            if self._include_match(match):
                matches.append(match)

        for skill in self.skill_store.list_active_versions():
            candidate_like = SkillCandidateRecord(
                id=f"active_skill:{skill.skill_id}",
                title=skill.name,
                description=skill.description,
                trigger_description=" ".join(list(skill.frontmatter.get("trigger_keywords", [])) + [skill.description]),
                workflow=[],
                preferred_tools=skill.preferred_tools,
                tags=skill.tags,
                workflow_category=None,
                confidence=1.0,
                occurrences=999,
                source_episode_ids=[],
                status="ACTIVE_SKILL",
                dedup_group_id=skill.skill_id,
                source_job_id=None,
                created_at=skill.created_at,
                updated_at=skill.updated_at,
            )
            match = self._score_candidate(normalized, candidate_like, source_type="active_skill")
            if self._include_match(match):
                matches.append(match)

        return sorted(
            matches,
            key=lambda match: (
                -match.total_score,
                -match.trigger_score,
                -match.title_score,
                match.source_type,
                match.candidate_id,
            ),
        )[: max(1, int(limit))]

    def classify_with_secondary(
        self,
        route: Any,
        incoming: SkillCandidateWrite,
        matches: Sequence[ProceduralDedupMatch],
    ) -> ProceduralDedupDecision:
        normalized = validate_skill_candidate_write(incoming)
        prompt = (
            "Classify whether an incoming procedural skill candidate is NEW, DUPLICATE, UPDATE, or MERGE. "
            "Return only JSON: {\"action\":\"NEW|DUPLICATE|UPDATE|MERGE\",\"target_candidate_id\":null,\"merged_candidate_ids\":[],\"reason\":\"...\",\"confidence\":0.0}. "
            "Do not approve, promote, create skill files, or modify active skills.\n\n"
            f"Incoming: {json.dumps(_candidate_for_prompt(normalized), sort_keys=True)}\n"
            f"Matches: {json.dumps([match.__dict__ for match in matches], sort_keys=True)}"
        )
        response = route.llm.invoke(prompt)
        parsed = _extract_json_value(str(getattr(response, "content", response)))
        if not isinstance(parsed, Mapping):
            raise SkillCandidateValidationError("dedup_action", "classifier output must be a JSON object")
        return validate_dedup_decision(parsed)

    def decide(self, dedup_input: ProceduralDedupInput, route: Any) -> tuple[ProceduralDedupDecision, List[ProceduralDedupMatch]]:
        matches = self.shortlist(dedup_input.incoming)
        if not matches:
            return ProceduralDedupDecision(action="NEW", reason="no deterministic shortlist matches", confidence=1.0), matches
        decision = self.classify_with_secondary(route, dedup_input.incoming, matches)
        return decision, matches

    def _score_candidate(
        self,
        incoming: SkillCandidateWrite,
        candidate: SkillCandidateRecord,
        *,
        source_type: str = "candidate",
    ) -> ProceduralDedupMatch:
        trigger_score = jaccard_score(
            tokenize_for_procedural_dedup(incoming.trigger_description),
            tokenize_for_procedural_dedup(candidate.trigger_description),
        )
        title_score = jaccard_score(
            tokenize_for_procedural_dedup(incoming.title),
            tokenize_for_procedural_dedup(candidate.title),
        )
        tool_score = overlap_score(incoming.preferred_tools, candidate.preferred_tools)
        tag_score = overlap_score(incoming.tags, candidate.tags)
        category_score = (
            1.0
            if incoming.workflow_category
            and candidate.workflow_category
            and str(incoming.workflow_category).lower() == str(candidate.workflow_category).lower()
            else 0.0
        )
        total_score = (
            0.35 * trigger_score
            + 0.25 * title_score
            + 0.20 * tool_score
            + 0.15 * tag_score
            + 0.05 * category_score
        )
        return ProceduralDedupMatch(
            candidate_id=candidate.id,
            title=candidate.title,
            trigger_score=trigger_score,
            tool_score=tool_score,
            tag_score=tag_score,
            category_score=category_score,
            title_score=title_score,
            total_score=total_score,
            status=candidate.status,
            source_type=source_type,
        )

    @staticmethod
    def _include_match(match: ProceduralDedupMatch) -> bool:
        return bool(
            match.total_score >= 0.25
            or match.title_score >= 0.50
            or match.trigger_score >= 0.45
            or (match.category_score == 1.0 and (match.tag_score > 0 or match.tool_score > 0))
        )


def validate_dedup_decision(value: Mapping[str, Any]) -> ProceduralDedupDecision:
    action = str(value.get("action") or "").strip().upper()
    if action not in VALID_PROCEDURAL_DEDUP_ACTIONS:
        raise SkillCandidateValidationError("dedup_action", "must be NEW, DUPLICATE, UPDATE, or MERGE")
    confidence = float(value.get("confidence", 0.5))
    if confidence < 0 or confidence > 1:
        raise SkillCandidateValidationError("confidence", "must be between 0 and 1")
    merged_ids = value.get("merged_candidate_ids") or []
    if not isinstance(merged_ids, list):
        raise SkillCandidateValidationError("merged_candidate_ids", "must be a list")
    target = value.get("target_candidate_id")
    return ProceduralDedupDecision(
        action=action,  # type: ignore[arg-type]
        target_candidate_id=str(target) if target else None,
        merged_candidate_ids=[str(item) for item in merged_ids if str(item).strip()],
        reason=str(value.get("reason") or ""),
        confidence=confidence,
    )


def _candidate_for_prompt(candidate: SkillCandidateWrite) -> dict[str, Any]:
    return {
        "title": candidate.title,
        "description": candidate.description,
        "trigger_description": candidate.trigger_description,
        "workflow_category": candidate.workflow_category,
        "preferred_tools": list(candidate.preferred_tools),
        "tags": list(candidate.tags),
        "confidence": candidate.confidence,
        "workflow": list(candidate.workflow),
    }

