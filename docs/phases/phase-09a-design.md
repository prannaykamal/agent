# Phase 9A Design: Retrieval Primitives and Ranking

## 1. Executive Summary

Phase 9A creates reusable, deterministic retrieval primitives for summaries, structured episodes, semantic facts, and approved procedural skills without changing runtime chat behavior. It adds a read-only retrieval layer that Phase 9B can later use for adaptive retrieval planning and final context assembly.

Previous phases established the target stores:

- Phase 5B: immutable `summary_blocks` and token-bounded short-term reconstruction.
- Phase 6B: deterministic episodic triggers and structured episode writes.
- Phase 7C: semantic consolidation into dedup-aware permanent facts.
- Phase 8C: HITL-approved, versioned procedural skills plus reload and usage stats.

Current chat still uses `node_retrieval_gate()` to call legacy wrappers directly. Phase 9A must not replace that path. It should only introduce reusable retrieval foundations:

- `src/memory/retrieval_types.py`
- `src/memory/retrieval_ranker.py`
- `src/memory/retrieval_sources.py`

Core guarantees:

- Retrieval is read-only.
- Ranking is deterministic.
- Every result includes provenance and score diagnostics.
- Output is token-aware.
- No LLMs are called.
- No chat context assembly changes occur until Phase 9B.

## 2. Scope

In scope:

- Define retrieval request/result dataclasses.
- Define source identifiers and memory-kind contracts.
- Add deterministic lexical scoring helpers.
- Add score normalization and tie-breaking utilities.
- Add token counting and token-aware result trimming helpers.
- Add source-specific retrieval primitives for summary blocks, structured episodes, semantic facts, and active procedural skills.
- Read existing Phase 5B, 6B, 7C, and 8C stores.
- Use existing semantic embeddings only if already available.
- Include provenance metadata for every retrieval candidate.
- Include internal debug score components.
- Add tests for each primitive and ranking utility.

Likely implementation files:

- New: `src/memory/retrieval_types.py`
- New: `src/memory/retrieval_ranker.py`
- New: `src/memory/retrieval_sources.py`
- Tests only.

Files that should not change in Phase 9A:

- `src/harness/graph.py`
- `src/memory/retrieval_gate.py`
- `src/api/server.py`
- worker modules
- schema/migration modules

## 3. Out of Scope

Phase 9A must not implement:

- Adaptive retrieval planner.
- Task-type retrieval policy.
- Final prompt/context assembly.
- `node_agent()` changes.
- `node_retrieval_gate()` changes.
- Graph runtime behavior changes.
- Chat retrieval behavior changes.
- API response shape changes.
- New memory writes.
- LLM calls.
- Schema migrations.
- Worker behavior changes.
- Vector retrieval in chat.
- Embedding generation during retrieval.
- Usage-stat increments from retrieval.
- Procedural retrieval ranking in the production chat path.

Phase 9A may define primitives capable of procedural ranking, but existing `match_procedural_skills()` behavior must remain unchanged until Phase 9B explicitly integrates the new retrieval layer.

## 4. Current Retrieval Assessment

### `src/harness/graph.py`

Current retrieval path:

```python
node_retrieval_gate() -> should_retrieve_memory()
node_retrieval_gate() -> search_facts_top_k(query, k=3)
node_retrieval_gate() -> search_episodes_fts(query, limit=2)
node_retrieval_gate() -> match_procedural_skills(query)
node_retrieval_gate() -> append SystemMessage("[Retrieved Long-Term Memory]...")
```

Strengths:

- Runtime behavior is simple and stable.
- Retrieval is gated for greetings and simple utility prompts.
- The public chat response shape is established.

Gaps:

- Retrieval uses fixed top-k values.
- It mixes legacy and target stores.
- It cannot budget across memory kinds.
- It has no unified score semantics.
- It has limited provenance.
- It has no deterministic cross-source ranking contract.

Phase 9A stance:

- Do not modify `node_retrieval_gate()`.
- Do not change the injected memory block format.
- Build independent retrieval primitives for Phase 9B.

### `src/memory/retrieval_gate.py`

Current behavior:

- Keyword and regex prefilter.
- Skips simple greetings and pure math.
- Returns a boolean.

Phase 9A stance:

- Keep unchanged.
- Phase 9B can later treat it as a prefilter signal.

### `src/memory/summary_blocks.py`

Useful APIs:

- `SummaryBlockRepository.list_summary_blocks(session_id, limit, newest_first)`.
- `SummaryBlockRecord` contains summary text, sequence, covered turn IDs, token counts, model metadata, and timestamps.

Phase 9A stance:

- Build summary retrieval by reading summary blocks.
- Do not mutate or enqueue summaries.

### `src/memory/episode_store.py`

Useful APIs:

- `StructuredEpisodeRepository.list_by_session()`.
- `StructuredEpisodeRepository.search_text(query, session_id, limit)`.
- `StructuredEpisodeRecord` contains title, summary, goals, decisions, artifacts, topics, importance, action, parent, source job, and search text.

Phase 9A stance:

- Use structured episodes as the target episodic source.
- Do not change legacy `search_episodes_fts()`.

### `src/memory/semantic_store.py`

Useful APIs:

- `SemanticFactStore.list_facts()`.
- `SemanticFactStore.search_facts(query, limit)`.
- `SemanticFactRecord` contains id, category, fact text, source, confidence, and created time.

Phase 9A stance:

- Semantic retrieval reads permanent facts only.
- It may use existing `semantic_embeddings` rows.
- It must not generate missing embeddings or write dedup events.

### `src/memory/embeddings.py`

Useful APIs:

- `get_embedding_provider()` deterministic fallback.
- `SemanticEmbeddingStore.get_embedding()`.
- `cosine_similarity()`.
- `lexical_similarity()`.
- `canonical_semantic_fact_text()`.

Caution:

- `SemanticEmbeddingStore.top_k_similar_facts()` can upsert missing embeddings. Retrieval must not call it in Phase 9A.

### `src/memory/skill_store.py` and `src/memory/skill_reloader.py`

Useful APIs:

- `SkillVersionStore.list_active_versions()`.
- `SkillRuntimeReloader.get_snapshot()`.
- `SkillVersionRecord` includes active/enabled flags, confidence, tags, tools, workflow, content hash, and file path.

Phase 9A stance:

- Procedural retrieval reads active enabled versions only.
- Usage stats may be read directly from `skill_usage_stats` as a signal.
- Retrieval must not call `record_used()` or `reload_active_skills()` by default.

### `src/memory/procedural.py`

Current behavior:

- `match_procedural_skills()` keyword-matches active enabled skills and preserves legacy behavior.

Phase 9A stance:

- Do not modify the wrapper.
- New procedural retriever can rank richer signals, but production chat continues using the wrapper until Phase 9B.

## 5. Retrieval Type System

Create `src/memory/retrieval_types.py`.

Responsibilities:

- Define memory kind literals.
- Define retrieval request dataclasses.
- Define source result and candidate dataclasses.
- Define score and provenance structures.
- Keep types independent from graph/runtime code.

Proposed public types:

```python
RetrievalMemoryKind = Literal["summary", "episodic", "semantic", "procedural"]
RetrievalSourceName = Literal[
    "summary_blocks",
    "structured_episodes",
    "semantic_facts",
    "procedural_skills",
]

@dataclass(frozen=True)
class RetrievalRequest:
    query: str
    session_id: str | None = None
    memory_kinds: tuple[RetrievalMemoryKind, ...] = ("summary", "episodic", "semantic", "procedural")
    per_source_limit: int = 5
    token_budget: int | None = None
    provider: str = "openai"
    model_name: str = "gpt-4o-mini"
    include_debug: bool = False

@dataclass(frozen=True)
class RetrievalScore:
    raw_score: float
    normalized_score: float
    rank_score: float
    components: dict[str, float]
    strategy: str

@dataclass(frozen=True)
class RetrievalProvenance:
    source_name: RetrievalSourceName
    table_name: str | None
    record_id: str
    session_id: str | None
    created_at: str | None
    fields_matched: tuple[str, ...]
    source_module: str
    metadata: dict[str, Any]

@dataclass(frozen=True)
class RetrievedMemoryCandidate:
    id: str
    memory_kind: RetrievalMemoryKind
    title: str
    content: str
    token_count: int
    score: RetrievalScore
    provenance: RetrievalProvenance
    debug: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class RetrievalSourceResult:
    source_name: RetrievalSourceName
    memory_kind: RetrievalMemoryKind
    candidates: tuple[RetrievedMemoryCandidate, ...]
    errors: tuple[str, ...] = ()

@dataclass(frozen=True)
class RetrievalBundle:
    request: RetrievalRequest
    source_results: tuple[RetrievalSourceResult, ...]
    candidates: tuple[RetrievedMemoryCandidate, ...]
    omitted_candidate_ids: tuple[str, ...]
    total_tokens: int
```

Design rules:

- Types are immutable where practical.
- Scores are clamped to `0.0..1.0` after normalization.
- `content` is the exact text intended for future context assembly.
- `debug` is internal and should not be exposed through existing API responses in Phase 9A.
## 6. Source-specific Retrieval Design

Create `src/memory/retrieval_sources.py`.

Responsibilities:

- Implement retrieval classes/functions per source.
- Convert source records into `RetrievedMemoryCandidate`.
- Attach provenance metadata.
- Use `retrieval_ranker.py` for scoring and normalization.
- Avoid writes, LLM calls, and graph integration.

Proposed retriever protocol:

```python
class MemoryRetrievalSource(Protocol):
    source_name: RetrievalSourceName
    memory_kind: RetrievalMemoryKind

    def retrieve(self, request: RetrievalRequest) -> RetrievalSourceResult: ...
```

Concrete sources:

- `SummaryBlockRetrievalSource`
- `StructuredEpisodeRetrievalSource`
- `SemanticFactRetrievalSource`
- `ProceduralSkillRetrievalSource`

Convenience functions:

```python
def retrieve_summary_blocks(request: RetrievalRequest, *, repository: SummaryBlockRepository | None = None) -> RetrievalSourceResult: ...
def retrieve_structured_episodes(request: RetrievalRequest, *, repository: StructuredEpisodeRepository | None = None) -> RetrievalSourceResult: ...
def retrieve_semantic_facts(request: RetrievalRequest, *, store: SemanticFactStore | None = None) -> RetrievalSourceResult: ...
def retrieve_procedural_skills(request: RetrievalRequest, *, store: SkillVersionStore | None = None, snapshot: SkillRuntimeSnapshot | None = None) -> RetrievalSourceResult: ...
def retrieve_all_sources(request: RetrievalRequest, sources: Sequence[MemoryRetrievalSource] | None = None) -> RetrievalBundle: ...
```

Failure isolation:

- A source retrieval error returns a `RetrievalSourceResult` with `errors` populated.
- One source failure must not block other sources.
- Phase 9B can decide whether to surface diagnostics.

## 7. Summary Retrieval Primitive

Source:

- `summary_blocks`

Input:

- `RetrievalRequest.query`
- `RetrievalRequest.session_id`
- `RetrievalRequest.per_source_limit`

Data read:

- `SummaryBlockRepository.list_summary_blocks(session_id, newest_first=True)`.

Required session behavior:

- If `session_id` is missing, return no summary results.
- Summary blocks are session-scoped short-term memory, not global memory.

Candidate content format:

```text
Short-term summary block <sequence_number>:
<summary>
```

Scoring signals:

| Component | Description | Suggested Weight |
|---|---|---:|
| `lexical` | Query-summary token similarity | 0.70 |
| `recency` | Newer summary blocks | 0.20 |
| `coverage` | Larger covered source context, capped | 0.10 |

Filtering:

- Empty summaries are ignored.
- Very low lexical scores may still be returned when the query is broad and the limit is not filled, but diagnostics should show weak relevance.

Provenance metadata:

- `table_name = "summary_blocks"`
- `record_id = SummaryBlockRecord.id`
- `sequence_number`
- `covered_message_ids`
- `start_message_id`
- `end_message_id`
- `source_job_id`
- `model_provider`
- `model_name`

No writes:

- Do not enqueue summary jobs.
- Do not mutate `summary_blocks`.
- Do not delete raw turns.

## 8. Episodic Retrieval Primitive

Source:

- `structured_episodes`

Input:

- `RetrievalRequest.query`
- optional `RetrievalRequest.session_id`
- `RetrievalRequest.per_source_limit`

Data read:

- Prefer `StructuredEpisodeRepository.search_text(query, session_id, limit=N)` for an initial shortlist.
- If query-specific search is too narrow, fallback may read `list_by_session(session_id, newest_first=True)` and rank locally.

Session behavior:

- If `session_id` is present, search only that session.
- If `session_id` is absent, return no cross-session results in Phase 9A unless a safe repository API exists.

Candidate content format:

```text
Episode: <title>
Summary: <summary>
Goals: <goals>
Decisions: <decisions>
Artifacts: <artifacts>
Topics: <topics>
```

Scoring signals:

| Component | Description | Suggested Weight |
|---|---|---:|
| `lexical` | Query vs title/summary/search_text | 0.55 |
| `topic_overlap` | Query tokens vs topics/goals/artifacts | 0.15 |
| `importance` | Stored episode importance | 0.15 |
| `recency` | Newer episode rows | 0.10 |
| `action_boost` | CREATE/UPDATE/MERGE/SPLIT diagnostics, low weight | 0.05 |

Tie-breakers:

1. Higher rank score.
2. Higher importance.
3. Newer `created_at`.
4. Stable episode ID.

Provenance metadata:

- `table_name = "structured_episodes"`
- `record_id = StructuredEpisodeRecord.id`
- `action`
- `parent_episode_id`
- `source_job_id`
- `start_message_id`
- `end_message_id`
- matched structured fields.

No legacy behavior change:

- Do not change `src/memory/episodic.py`.
- Do not change `search_episodes_fts()`.
- Do not write to legacy `episodes`.

## 9. Semantic Retrieval Primitive

Source:

- `facts`
- optional read-only `semantic_embeddings`

Input:

- `RetrievalRequest.query`
- `RetrievalRequest.per_source_limit`

Data read:

- `SemanticFactStore.list_facts()` for permanent facts.
- Optional existing embeddings through `SemanticEmbeddingStore.get_embedding()`.

Important no-write rule:

- Do not call any helper that upserts missing embeddings.
- Do not call `SemanticFactStore.add_explicit_fact()`.
- Do not call dedup services.
- Do not write `semantic_dedup_events`.
- Do not update `MEMORY.md`.

Read-only embedding strategy:

1. Build canonical query text in memory.
2. Use deterministic fallback embedding provider to embed the query in memory.
3. For each fact, call `SemanticEmbeddingStore.get_embedding("semantic_fact", fact.id, query_model)`.
4. If an embedding exists, use cosine similarity.
5. If no embedding exists, use lexical similarity.
6. Record strategy as `embedding_existing` or `lexical_fallback`.

Candidate content format:

```text
Semantic fact (<category>): <fact_text>
```

Scoring signals:

| Component | Description | Suggested Weight |
|---|---|---:|
| `semantic_similarity` | Existing embedding or lexical fallback | 0.70 |
| `confidence` | Fact confidence | 0.15 |
| `category_overlap` | Query/category token overlap | 0.10 |
| `recency` | Newer permanent fact rows | 0.05 |

Provenance metadata:

- `table_name = "facts"`
- `record_id = facts.rowid`
- `category`
- `source`
- `confidence`
- `embedding_used`
- `embedding_model`
- `similarity_strategy`

Compatibility:

- Existing `search_facts_top_k()` remains unchanged.
- Existing `/api/memory` and `/api/memory/full` behavior remains unchanged.

## 10. Procedural Retrieval Primitive

Source:

- `skill_versions`
- optional read-only `skill_usage_stats`
- optional caller-supplied `SkillRuntimeSnapshot`

Input:

- `RetrievalRequest.query`
- `RetrievalRequest.per_source_limit`

Data read:

- `SkillVersionStore.list_active_versions()`.
- `skill_usage_stats` read-only for usage signal.
- Optional `SkillRuntimeSnapshot` from `SkillRuntimeReloader.get_snapshot()`.

Important no-write rule:

- Do not call `SkillRuntimeReloader.reload_active_skills()` by default because reload records `times_loaded`.
- Do not call `SkillRuntimeReloader.record_skill_used()`.
- Do not call `SkillVersionStore.record_used()`.
- Do not modify `skill_versions`, `skill_usage_stats`, `skill_candidates`, or `procedural_skill_approvals`.

Eligibility:

- Retrieve only active enabled skill versions.
- Exclude disabled, archived, inactive, and candidate-only records.
- User-authored skill files must not be touched or overwritten.

Candidate content format:

```text
Skill: <name>
Description: <description>
Triggers: <trigger_keywords>
Workflow: <execution_steps>
Preferred tools: <preferred_tools>
```

Scoring signals:

| Component | Description | Suggested Weight |
|---|---|---:|
| `trigger_overlap` | Query vs trigger keywords | 0.35 |
| `lexical` | Query vs title/description/workflow/tags/tools | 0.25 |
| `confidence` | Candidate confidence if available | 0.15 |
| `usage` | Read-only usage stats, log-scaled | 0.10 |
| `recency` | Active version creation/update recency | 0.10 |
| `tool_overlap` | Query vs preferred tools | 0.05 |

Usage scoring:

- `usage = log1p(times_used) / log1p(max_times_used_in_result_set)`.
- If all `times_used` are zero, usage component is `0`.
- `times_loaded` may appear in debug metadata but should not dominate ranking.

Provenance metadata:

- `table_name = "skill_versions"`
- `record_id = SkillVersionRecord.id`
- `skill_id`
- `version`
- `candidate_id`
- `approval_id`
- `file_path`
- `content_hash`
- `preferred_tools`
- `tags`
- `times_used`
- `times_loaded`

Compatibility:

- Existing `match_procedural_skills()` remains unchanged.
- Existing `/api/skills` behavior remains unchanged.
- No procedural ranking is used by chat until Phase 9B.

## 11. Ranking and Score Normalization

Create `src/memory/retrieval_ranker.py`.

Responsibilities:

- Tokenize text deterministically.
- Compute lexical similarity.
- Compute exact phrase and token overlap boosts.
- Normalize score components.
- Merge and sort candidates deterministically.
- Apply token-aware trimming.

Core helpers:

```python
def normalize_retrieval_text(text: str) -> str: ...
def tokenize_retrieval_text(text: str) -> tuple[str, ...]: ...
def lexical_similarity(left: str, right: str) -> float: ...
def recency_score(created_at: str | None, *, newest: str | None = None) -> float: ...
def clamp_score(value: float) -> float: ...
def weighted_score(components: Mapping[str, float], weights: Mapping[str, float]) -> float: ...
def normalize_candidates(candidates: Sequence[RetrievedMemoryCandidate]) -> tuple[RetrievedMemoryCandidate, ...]: ...
def rank_candidates(candidates: Sequence[RetrievedMemoryCandidate]) -> tuple[RetrievedMemoryCandidate, ...]: ...
```

Deterministic tokenizer rules:

- Lowercase.
- Split on non-alphanumeric characters.
- Drop common stop words.
- Drop one-character tokens except digits.
- Preserve simple numeric tokens.
- Apply a conservative plural trim for words longer than four characters ending in `s`.

Score normalization:

- Each component is clamped to `0..1`.
- `raw_score` is source-specific weighted score before cross-source normalization.
- `normalized_score` is min/max normalized within a source result.
- `rank_score` defaults to `normalized_score` in Phase 9A.
- Phase 9B may apply planner-specific source weights.

Tie-breaking order:

1. `rank_score` descending.
2. `normalized_score` descending.
3. `raw_score` descending.
4. memory kind order: semantic, episodic, procedural, summary.
5. `created_at` descending if available.
6. stable candidate ID ascending.

Phase 9A should not decide final cross-kind source allocation. It only provides deterministic ranking utilities that Phase 9B can compose.

## 12. Token Budget / Trimming Design

Token-aware output boundaries belong in Phase 9A primitives, but final prompt assembly belongs in Phase 9B.

Token counting:

- Reuse Phase 5A token budget primitives where possible.
- Fallback to deterministic `len(text) // 4` compatible behavior.
- Count each candidate's `content` plus minimal metadata label overhead.

Proposed helpers:

```python
def estimate_retrieval_candidate_tokens(candidate: RetrievedMemoryCandidate, *, provider: str, model_name: str) -> int: ...
def trim_retrieval_candidates_to_budget(
    candidates: Sequence[RetrievedMemoryCandidate],
    token_budget: int,
    *,
    provider: str = "openai",
    model_name: str = "gpt-4o-mini",
    allow_truncation: bool = False,
) -> tuple[tuple[RetrievedMemoryCandidate, ...], tuple[str, ...], int]: ...
```

Default trimming behavior:

- Keep whole candidates when possible.
- Omit candidates that do not fit.
- Preserve ranking order.
- Return omitted candidate IDs.
- If `token_budget <= 0`, return no candidates.

Oversized candidate behavior:

- Default: omit oversized candidate.
- Optional `allow_truncation=True`: produce a copied candidate with deterministic prefix truncation and debug metadata:
  - `content_truncated = True`
  - `original_token_count`
  - `truncated_token_count`

No assembly behavior:

- Do not create `SystemMessage` blocks.
- Do not alter graph messages.
- Do not alter `/api/chat` response fields.

## 13. Provenance and Debug Metadata

Every retrieval result must explain where it came from and why it ranked where it did.

Required provenance fields:

- memory kind,
- source name,
- table name,
- record ID,
- session ID when available,
- created timestamp,
- source module,
- matched fields,
- source-specific metadata.

Required score debug fields:

- component scores,
- weights used,
- raw score,
- normalized score,
- rank score,
- strategy used.

Source-specific debug examples:

Summary:

```json
{
  "sequence_number": 4,
  "covered_message_count": 12,
  "original_token_count": 3800
}
```

Episodic:

```json
{
  "importance": 0.82,
  "topics": ["deployment", "staging"],
  "action": "CREATE"
}
```

Semantic:

```json
{
  "category": "preference",
  "confidence": 0.95,
  "similarity_strategy": "embedding_existing"
}
```

Procedural:

```json
{
  "skill_id": "deploy-staging",
  "version": 2,
  "times_used": 5,
  "preferred_tools": ["shell", "github"]
}
```

Debug metadata remains internal in Phase 9A. API observability can be designed in Phase 10 unless Phase 9B chooses to surface diagnostics behind an explicit debug flag.

## 14. Compatibility Boundaries

Phase 9A must preserve existing runtime behavior.

Do not modify:

- `src/harness/graph.py`
- `node_retrieval_gate()`
- `node_agent()`
- `src/memory/retrieval_gate.py`
- `search_facts_top_k()`
- `search_episodes_fts()`
- `match_procedural_skills()`
- API response shapes
- worker behavior

Wrapper compatibility:

- If any existing test imports retrieval-related public functions, keep them unchanged.
- New retrievers should live beside existing wrappers rather than replacing them.
- Phase 9B will decide whether `retrieval_gate.py` delegates to the new primitives.

Database compatibility:

- No migrations.
- No writes.
- No schema assumptions beyond Phase 2 tables and existing legacy tables.
- Retrieval primitives should work on empty databases and return empty results.

Embedding compatibility:

- Existing embeddings can improve semantic ranking.
- Missing embeddings must not be generated during retrieval.
- Lexical fallback is mandatory.

Procedural compatibility:

- Disabled/inactive skills excluded.
- Candidate-only procedural data excluded.
- Usage stats read-only.
- `record_skill_used()` not called.

## 15. Test Plan

Suggested test files:

- `tests/test_phase9a_retrieval_types.py`
- `tests/test_phase9a_retrieval_ranker.py`
- `tests/test_phase9a_summary_retrieval.py`
- `tests/test_phase9a_episodic_retrieval.py`
- `tests/test_phase9a_semantic_retrieval.py`
- `tests/test_phase9a_procedural_retrieval.py`
- `tests/test_phase9a_retrieval_sources_bundle.py`
- `tests/test_phase9a_retrieval_compatibility.py`

Tests to add:

Type system:

- Retrieval request defaults are deterministic.
- Candidate/provenance/score dataclasses are immutable or treated as immutable.
- Empty query validation behaves consistently.

Ranker:

- Tokenization is deterministic.
- Stop words are removed.
- Lexical similarity is stable.
- Component weights clamp to `0..1`.
- Rank tie-breakers are deterministic.
- Score normalization handles empty, one-item, and equal-score lists.

Summary retrieval:

- Empty session returns no summaries.
- Session-scoped summaries are retrieved only for matching session.
- Query-relevant summary ranks above unrelated summary.
- Recency contributes but does not overwhelm lexical relevance.
- Provenance includes covered message IDs and sequence number.

Episodic retrieval:

- Structured episodes are retrieved from `structured_episodes`.
- Legacy `episodes` rows are not required.
- Query-relevant episode ranks above unrelated episode.
- Importance contributes to ranking.
- Provenance includes action, topics, start/end message IDs, and source job ID.

Semantic retrieval:

- Permanent facts are retrieved from `facts`.
- Existing embedding rows are used when present.
- Missing embedding rows do not cause writes.
- Lexical fallback works without embeddings.
- Confidence contributes to ranking.
- No `semantic_dedup_events` rows are written.
- `MEMORY.md` is not modified.

Procedural retrieval:

- Active enabled skill versions are retrieved.
- Disabled, archived, inactive, and candidate-only skills are excluded.
- Trigger keywords rank strongly.
- Preferred tool overlap contributes.
- Usage stats are read-only and affect score deterministically.
- `record_used()` is not called.
- No `SKILL.md` files are written.

Token trimming:

- Candidates are omitted when budget is exhausted.
- Candidate order is preserved after trimming.
- Oversized candidates are omitted by default.
- Optional truncation marks debug metadata correctly.

Bundle retrieval:

- Source failures are isolated.
- Empty database returns empty bundle.
- Each source result includes source name and errors.
- No source writes to any memory table.

Compatibility regressions:

- Existing Phase 5B tests pass.
- Existing Phase 6B tests pass.
- Existing Phase 7C tests pass.
- Existing Phase 8C tests pass.
- `tests/test_harness.py` still passes.
- `tests/test_api_server.py` still passes.

Suggested focused run:

```bash
python -m pytest tests/test_phase9a_retrieval_types.py tests/test_phase9a_retrieval_ranker.py tests/test_phase9a_summary_retrieval.py tests/test_phase9a_episodic_retrieval.py tests/test_phase9a_semantic_retrieval.py tests/test_phase9a_procedural_retrieval.py tests/test_phase9a_retrieval_sources_bundle.py tests/test_phase9a_retrieval_compatibility.py -q
```

Suggested regression run:

```bash
python -m pytest tests/test_phase5b_summary_blocks_repository.py tests/test_phase5b_graph_short_term.py tests/test_phase6b_episode_handler.py tests/test_phase7c_consolidation_handler.py tests/test_phase8c_skill_reload_usage.py tests/test_api_server.py tests/test_harness.py -q
```

Then run the full suite if focused tests pass.

## 16. Risks

### Risk: Retrieval primitives accidentally write embeddings

Mitigation:

- Do not call write-capable embedding helpers.
- Use `get_embedding()` only.
- Add tests counting `semantic_embeddings` rows before and after semantic retrieval.

### Risk: Phase 9A silently changes chat behavior

Mitigation:

- Do not modify graph or existing retrieval wrappers.
- Add compatibility tests asserting current graph/API shapes still pass.

### Risk: Scores are hard to compare across memory kinds

Mitigation:

- Normalize within source in Phase 9A.
- Keep cross-source allocation for Phase 9B planner.
- Include score components and strategy metadata.

### Risk: Procedural retrieval uses inactive or unapproved skills

Mitigation:

- Read only `SkillVersionStore.list_active_versions()`.
- Add disabled/archive tests.
- Do not read `skill_candidates` for retrieval.

### Risk: Token trimming hides important records

Mitigation:

- Preserve ranked order.
- Return omitted IDs and token diagnostics.
- Leave final context allocation to Phase 9B.

### Risk: Source-specific failures block all retrieval

Mitigation:

- Return source-level errors.
- Keep `retrieve_all_sources()` failure-isolated.

## 17. Acceptance Criteria

Phase 9A is complete when:

- `src/memory/retrieval_types.py` exists and defines shared retrieval request/result/provenance/score types.
- `src/memory/retrieval_ranker.py` exists and provides deterministic tokenization, lexical scoring, normalization, ranking, and token trimming helpers.
- `src/memory/retrieval_sources.py` exists and provides retrieval primitives for summaries, episodes, semantic facts, and procedural skills.
- Summary retrieval reads `summary_blocks` and is session-scoped.
- Episodic retrieval reads `structured_episodes`.
- Semantic retrieval reads permanent `facts` and optionally existing embeddings without writing missing embeddings.
- Procedural retrieval reads active enabled `skill_versions` and read-only `skill_usage_stats`.
- Disabled/inactive procedural skills are excluded.
- Every result has provenance and score diagnostics.
- Token-aware trimming works deterministically.
- Empty databases return empty results without errors.
- Source failures are isolated.
- No LLM calls occur.
- No memory writes occur.
- No schema migrations are added.
- No graph, API, worker, or production chat retrieval behavior changes occur.
- Focused Phase 9A tests and listed regressions pass.

## 18. Implementation Checklist

1. Create `src/memory/retrieval_types.py`.
2. Define `RetrievalMemoryKind`, `RetrievalSourceName`, `RetrievalRequest`, `RetrievalScore`, `RetrievalProvenance`, `RetrievedMemoryCandidate`, `RetrievalSourceResult`, and `RetrievalBundle`.
3. Create `src/memory/retrieval_ranker.py`.
4. Implement deterministic text normalization and tokenization.
5. Implement lexical similarity and exact-overlap helpers.
6. Implement score clamping and weighted scoring.
7. Implement candidate normalization and deterministic sorting.
8. Implement token estimation and token-budget trimming.
9. Create `src/memory/retrieval_sources.py`.
10. Implement `SummaryBlockRetrievalSource`.
11. Implement `StructuredEpisodeRetrievalSource`.
12. Implement read-only `SemanticFactRetrievalSource`.
13. Implement read-only `ProceduralSkillRetrievalSource`.
14. Implement `retrieve_all_sources()` with source failure isolation.
15. Add focused Phase 9A tests.
16. Add no-write assertions around semantic embeddings, dedup events, MEMORY.md, skill usage stats, and SKILL.md files.
17. Run focused tests.
18. Run listed regressions.
19. Run full suite if feasible.
20. Perform filesystem wiring check.

## 19. Filesystem Wiring Check Required After Implementation

Before final implementation approval, verify actual files changed on disk instead of relying on the UI edited-files list.

Required checks:

- Verify `src/memory/retrieval_types.py` exists.
- Verify `src/memory/retrieval_ranker.py` exists.
- Verify `src/memory/retrieval_sources.py` exists.
- Verify `src/harness/graph.py` was not modified.
- Verify `src/memory/retrieval_gate.py` was not modified unless explicitly justified.
- Verify `src/api/server.py` was not modified.
- Verify worker modules were not modified.
- Verify `src/db.py`, `src/db_migrations.py`, and `src/memory/schema.py` were not modified.
- Verify no retrieval primitive calls LLM route helpers or `.invoke()`.
- Verify semantic retrieval does not call embedding upsert helpers.
- Verify procedural retrieval does not call `record_used()` or `reload_active_skills()` by default.
- Verify existing wrappers `search_facts_top_k()`, `search_episodes_fts()`, and `match_procedural_skills()` still behave as before.
- Verify no API response shapes changed.
- Verify no chat context assembly changed.
- Run:

```bash
git status --short
```

The final implementation summary should report:

- Actual files changed.
- Which retrieval primitives were added.
- Ranking and token trimming behavior.
- No-write verification results.
- Tests run and results.
- Any deviations from this design.
