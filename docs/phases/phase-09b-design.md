# Phase 9B Design: Adaptive Retrieval Planner and Context Assembly

## 1. Executive Summary

Phase 9B wires the Phase 9A read-only retrieval primitives into the chat retrieval path. It replaces the current fixed legacy top-k retrieval inside `node_retrieval_gate()` with deterministic adaptive planning, token-aware retrieval execution, and final memory context assembly.

The phase must preserve the outer chat contract:

- `/api/chat` request and response shapes remain unchanged.
- `node_agent()` remains unchanged.
- Simple greeting and simple math retrieval skips still work through `should_retrieve_memory()`.
- The injected memory context remains a `SystemMessage` beginning with `[Retrieved Long-Term Memory]`.
- Retrieval debug metadata is internal only and not exposed publicly by default.
- Retrieval never writes memory, calls LLMs, starts workers, or changes schema.

Phase 9A established:

- `src/memory/retrieval_types.py`
- `src/memory/retrieval_ranker.py`
- `src/memory/retrieval_sources.py`

Phase 9B should add:

- `src/memory/retrieval_planner.py`
- `src/memory/context_assembler.py`

Phase 9B should refactor only the retrieval section of `src/harness/graph.py`, specifically `node_retrieval_gate()` imports and body. Phase 9A primitives should remain unchanged except for small bug fixes discovered during implementation.

## 2. Scope

In scope:

- Add deterministic task/intent classification for retrieval planning.
- Select memory kinds by task type.
- Allocate retrieval token budget across memory kinds.
- Execute Phase 9A retrieval sources using a single retrieval bundle.
- Assemble a token-bounded memory context block for chat.
- Preserve existing memory block header and broad section names.
- Keep `retrieved_memories` state compatible as a list of dictionaries.
- Keep retrieval gate skip behavior for simple greetings and math.
- Add fallback to current legacy wrappers if the new retrieval layer fails.
- Add deterministic unit and graph integration tests.

Files expected to be created:

- `src/memory/retrieval_planner.py`
- `src/memory/context_assembler.py`

Files expected to be modified:

- `src/harness/graph.py` only for `node_retrieval_gate()` imports and integration.
- Phase 9A modules only for narrow bug fixes if tests expose an issue.
- Tests only.

Suggested tests:

- `tests/test_phase9b_retrieval_planner.py`
- `tests/test_phase9b_context_assembler.py`
- `tests/test_phase9b_graph_retrieval_integration.py`
- `tests/test_phase9b_retrieval_fallback.py`
- `tests/test_phase9b_retrieval_budgeting.py`

## 3. Out of Scope

Phase 9B must not implement:

- Memory store changes.
- Memory writes.
- LLM calls.
- Worker behavior changes.
- Schema migrations.
- API response shape changes.
- Frontend changes.
- New semantic extraction, consolidation, or promotion behavior.
- Procedural usage-stat increments during retrieval.
- Embedding generation or embedding upserts during retrieval.
- Public exposure of retrieval debug metadata by default.
- Changes to `node_agent()`.
- Changes to short-term summary generation behavior.

Phase 9B may use token budget calculations from `src/memory/token_budget.py`, but it must not modify short-term memory stores or enqueue summary jobs.

## 4. Current Chat Retrieval Assessment

Current `src/harness/graph.py` retrieval flow:

```python
node_retrieval_gate(state):
    messages = list(state.get("messages", []))
    last_user_msg = latest HumanMessage content
    needs_retrieval = should_retrieve_memory(last_user_msg)

    if needs_retrieval:
        facts = search_facts_top_k(query, k=3)
        episodes = search_episodes_fts(query, limit=2)
        skills = match_procedural_skills(query)
        build fixed sections
        append SystemMessage("[Retrieved Long-Term Memory]...")

    return {
        "messages": messages,
        "retrieval_triggered": needs_retrieval,
        "retrieved_memories": retrieved_items,
    }
```

Strengths:

- Simple and stable.
- Uses `should_retrieve_memory()` to avoid retrieval for greetings and simple utility prompts.
- Injected context format is easy for the primary LLM to consume.

Gaps:

- Fixed `k=3` facts, `limit=2` episodes, unbounded procedural matches.
- Does not use summary blocks.
- Does not use structured episodes.
- Cannot adapt memory kinds to the user request.
- Cannot budget memory context by tokens.
- Cannot rank across memory kinds.
- Cannot isolate source failures except by failing the whole block construction.
- Does not use Phase 9A provenance or normalized ranking.

Phase 9B stance:

- Keep the retrieval gate skip decision.
- Replace successful retrieval execution with Phase 9A primitives.
- Preserve legacy fallback for safety.
- Preserve the existing header and section names where possible.

## 5. Adaptive Retrieval Planner Design

Create `src/memory/retrieval_planner.py`.

Responsibilities:

- Classify the latest user message into deterministic retrieval task types.
- Decide whether retrieval should proceed after the existing gate approves it.
- Select memory kinds.
- Allocate token budget by memory kind.
- Build a `RetrievalRequest` for Phase 9A.
- Return internal planning metadata for tests and diagnostics.

The planner must be deterministic and regex/token based. It must not call LLMs or write data.

### Proposed Types

```python
RetrievalTaskType = Literal[
    "identity_or_preference",
    "episodic_recall",
    "procedural_how_to",
    "project_context",
    "summary_context",
    "broad_memory",
]

@dataclass(frozen=True)
class RetrievalPolicyProfile:
    task_type: RetrievalTaskType
    memory_kinds: tuple[RetrievalMemoryKind, ...]
    per_source_limit: int
    token_budget: int
    allocation: dict[RetrievalMemoryKind, int]
    rationale: tuple[str, ...]

@dataclass(frozen=True)
class RetrievalPlan:
    query: str
    session_id: str | None
    provider: str
    model_name: str
    should_retrieve: bool
    gate_reason: str
    task_type: RetrievalTaskType
    memory_kinds: tuple[RetrievalMemoryKind, ...]
    per_source_limit: int
    total_token_budget: int
    budget_by_kind: dict[RetrievalMemoryKind, int]
    retrieval_request: RetrievalRequest | None
    debug: dict[str, Any]
```

### Public Functions

```python
def classify_retrieval_task(query: str) -> RetrievalTaskType:
    ...

def select_memory_kinds(task_type: RetrievalTaskType) -> tuple[RetrievalMemoryKind, ...]:
    ...

def allocate_retrieval_budget(
    task_type: RetrievalTaskType,
    total_budget: int,
) -> dict[RetrievalMemoryKind, int]:
    ...

def build_retrieval_plan(
    *,
    query: str,
    session_id: str | None,
    provider: str | None,
    model_name: str | None,
    messages: Sequence[BaseMessage],
    gate_allows_retrieval: bool,
    include_debug: bool = False,
) -> RetrievalPlan:
    ...
```

## 6. Task Type / Intent Signals

The planner should use deterministic signals from the latest user message. It should normalize text using Phase 9A ranker helpers where useful.

### Task Types

`identity_or_preference`:

- Example queries: "what is my email", "what do I prefer", "what is my name", "remembered preference".
- Signals: `my name`, `my email`, `my preference`, `what do I like`, `what do you know about me`.
- Primary memory: semantic.
- Secondary memory: summary, episodic.

`episodic_recall`:

- Example queries: "what did we decide last time", "when did we discuss deployment", "recall the meeting".
- Signals: `last time`, `previously`, `earlier`, `when did`, `what did we decide`, `meeting`, `conversation`, `episode`, `worked on`.
- Primary memory: episodic.
- Secondary memory: summary, semantic.

`procedural_how_to`:

- Example queries: "how do I deploy staging", "run the release process", "what steps should I use".
- Signals: `how do`, `steps`, `procedure`, `workflow`, `process`, `deploy`, `run`, `execute`, `checklist`.
- Primary memory: procedural.
- Secondary memory: semantic, episodic.

`project_context`:

- Example queries: "what is the current architecture", "continue the migration", "what was the plan for phase 9".
- Signals: `project`, `architecture`, `phase`, `roadmap`, `implementation`, `migration`, `design`, `current code`.
- Primary memory: summary and episodic.
- Secondary memory: semantic and procedural.

`summary_context`:

- Example queries: "summarize where we are", "catch me up", "what is the context".
- Signals: `summarize`, `catch me up`, `context`, `where are we`, `recap`.
- Primary memory: summary.
- Secondary memory: episodic and semantic.

`broad_memory`:

- Default when retrieval gate allows retrieval but no stronger task signal is found.
- Uses all memory kinds with balanced allocation.

### Priority Order

When multiple signals match, classify in this order:

1. `procedural_how_to`
2. `identity_or_preference`
3. `episodic_recall`
4. `summary_context`
5. `project_context`
6. `broad_memory`

Rationale:

- Procedural requests usually need actionable instructions and should not be diluted by broad recall.
- Identity/preference questions are often answerable from semantic facts.
- Episodic and summary requests benefit from broader context but still have distinct source priorities.

## 7. Memory Kind Selection Policy

The planner should map task types to memory kinds in deterministic priority order.

| Task type | Memory kinds | Rationale |
| --- | --- | --- |
| `identity_or_preference` | `semantic`, `summary`, `episodic` | Stable facts first; summaries/episodes provide backup context. |
| `episodic_recall` | `episodic`, `summary`, `semantic` | Structured events first; summaries support older context. |
| `procedural_how_to` | `procedural`, `semantic`, `episodic` | Skills first; facts and episodes explain constraints. |
| `project_context` | `summary`, `episodic`, `semantic`, `procedural` | Broad but history-heavy. |
| `summary_context` | `summary`, `episodic`, `semantic` | Summary blocks are primary. |
| `broad_memory` | `semantic`, `episodic`, `procedural`, `summary` | Balanced cross-source fallback. |

Selection rules:

- Never select a memory kind that Phase 9A cannot read.
- Summary retrieval requires `session_id`; if `session_id` is missing, keep the kind in the plan but expect the source to return empty.
- Procedural retrieval must remain active-enabled only and must not increment usage stats.
- Semantic retrieval must not generate embeddings.
- The planner may request all selected kinds in one `RetrievalRequest`; Phase 9A ranking handles cross-kind order.

## 8. Token Budget Allocation

Phase 9B must respect token budgets for final memory context.

### Budget Inputs

Use `calculate_budget_for_primary_route()` from `src/memory/token_budget.py` to resolve:

- primary provider
- primary model
- context window
- historical conversation budget
- current user message token count
- output reserve
- safety margin

The retrieval planner should pass the current message list, provider, and model from `AgentState`. It must not call `resolve_primary_llm()` or any LLM factory.

### Total Retrieval Budget

Recommended default:

```text
retrieval_budget = min(
    max(512, int(context_window * 0.08)),
    4096,
    max(0, available_input_tokens - historical_conversation_tokens - current_user_message_tokens)
)
```

For small local context windows, the lower bound must not exceed available room. Therefore the implementation should compute:

```text
soft_target = min(max(512, context_window * 0.08), 4096)
available_room = max(0, available_input_tokens - historical_tokens - current_user_tokens)
retrieval_budget = max(0, min(soft_target, available_room))
```

If `retrieval_budget == 0`, the plan should set `should_retrieve=False` with `gate_reason="no_token_room"`.

### Per-kind Allocation

Use deterministic weighted allocation by task type.

| Task type | Semantic | Episodic | Procedural | Summary |
| --- | ---: | ---: | ---: | ---: |
| `identity_or_preference` | 0.65 | 0.20 | 0.00 | 0.15 |
| `episodic_recall` | 0.20 | 0.55 | 0.00 | 0.25 |
| `procedural_how_to` | 0.20 | 0.15 | 0.55 | 0.10 |
| `project_context` | 0.20 | 0.30 | 0.10 | 0.40 |
| `summary_context` | 0.20 | 0.25 | 0.00 | 0.55 |
| `broad_memory` | 0.35 | 0.25 | 0.20 | 0.20 |

Allocation rules:

- Exclude weights for memory kinds not selected.
- Normalize remaining weights to 1.0.
- Round down each allocation, then distribute remaining tokens by memory-kind priority order for the task type.
- Keep a minimum per selected kind of `min(128, retrieval_budget // selected_kind_count)` when possible.
- The final sum must be less than or equal to `retrieval_budget`.

### Phase 9A Request Budget

`RetrievalRequest.token_budget` should be the total retrieval budget. Phase 9A currently applies global trimming across ranked candidates. Phase 9B should also enforce section-level allocation during assembly to prevent one source from consuming all context.

## 9. Retrieval Execution Flow

Planned flow inside `node_retrieval_gate()`:

1. Copy existing messages.
2. Extract latest `HumanMessage` content.
3. Call `should_retrieve_memory(latest_user_msg)`.
4. If gate returns false, return current behavior unchanged:
   - messages unchanged
   - `retrieval_triggered=False`
   - `retrieved_memories=[]`
5. Build a `RetrievalPlan` with current provider, model, session, and messages.
6. If plan says `should_retrieve=False`, return no injected context but keep `retrieval_triggered` aligned with the gate decision or plan decision. Preferred value: `False` when no retrieval executes due to no token room.
7. Call `retrieve_all_sources(plan.retrieval_request)`.
8. Assemble context via `assemble_retrieved_memory_context()`.
9. If assembled block is non-empty, append `SystemMessage(content=block_text)`.
10. Return:
    - messages
    - `retrieval_triggered=True` only if retrieval executed or legacy fallback executed
    - `retrieved_memories=assembled.legacy_retrieved_items`

### Source Failure Handling

`retrieve_all_sources()` already isolates source failures into `RetrievalSourceResult.errors`. Phase 9B should:

- Continue if at least one candidate is available.
- Keep source errors in internal debug only.
- Use legacy fallback only when retrieval execution raises before returning a bundle, or assembly raises.
- Avoid falling back when only one source fails but other sources succeed.

## 10. Context Assembly Format

Create `src/memory/context_assembler.py`.

Responsibilities:

- Convert a `RetrievalBundle` into the final chat memory `SystemMessage` text.
- Keep the existing header: `[Retrieved Long-Term Memory]`.
- Use familiar section labels:
  - `Semantic Facts:`
  - `Past Episodes:`
  - `Procedural Skills:`
  - `Conversation Summaries:`
- Respect total and per-kind token budgets.
- Omit candidates that do not fit.
- Produce legacy-compatible `retrieved_memories` dictionaries.
- Keep provenance/debug metadata internal.

### Proposed Types

```python
@dataclass(frozen=True)
class ContextAssemblyOptions:
    total_token_budget: int
    budget_by_kind: dict[RetrievalMemoryKind, int]
    include_debug: bool = False
    preserve_legacy_header: bool = True
    max_items_per_kind: int | None = None

@dataclass(frozen=True)
class AssembledMemoryContext:
    block_text: str
    legacy_retrieved_items: list[dict[str, Any]]
    included_candidate_ids: tuple[str, ...]
    omitted_candidate_ids: tuple[str, ...]
    token_count: int
    source_errors: tuple[str, ...]
    debug: dict[str, Any]
```

### Public Functions

```python
def assemble_retrieved_memory_context(
    bundle: RetrievalBundle,
    options: ContextAssemblyOptions,
) -> AssembledMemoryContext:
    ...

def candidate_to_legacy_retrieved_item(candidate: RetrievedMemoryCandidate) -> dict[str, Any]:
    ...

def format_candidate_for_context(candidate: RetrievedMemoryCandidate) -> str:
    ...
```

### Section Formatting

Semantic candidate format:

```text
Semantic Facts:
- [category] fact text
```

Mapping:

- `category` from provenance metadata `category`, fallback to candidate title.
- `fact_text` from candidate content.

Episodic candidate format:

```text
Past Episodes:
- created_at: title - summary/content
```

Mapping:

- `created_at` from provenance.
- Prefer candidate title plus content, trimmed to budget.

Procedural candidate format:

```text
Procedural Skills:
- Skill 'name': workflow/content
```

Mapping:

- `name` from candidate title.
- `workflow/content` from candidate content with `Name:` and `Description:` prefixes collapsed if needed.

Summary candidate format:

```text
Conversation Summaries:
- Summary block N: summary text
```

Mapping:

- sequence number from provenance metadata.
- content from candidate content.

If only one section has content, still include the header and the section label to preserve predictable prompt structure.

### Debug Metadata

Debug metadata must stay internal:

- Do not include score details in `block_text` by default.
- Do not include provenance JSON in `block_text`.
- Do not add debug fields to `/api/chat` responses.
- Internal `AssembledMemoryContext.debug` may include plan task type, omitted IDs, source errors, and token budget diagnostics for tests.

## 11. Graph Integration Design

Modify only `node_retrieval_gate()` and its imports in `src/harness/graph.py`.

### New Imports

```python
from src.memory.context_assembler import (
    ContextAssemblyOptions,
    assemble_retrieved_memory_context,
)
from src.memory.retrieval_planner import build_retrieval_plan
from src.memory.retrieval_sources import retrieve_all_sources
```

Keep legacy imports for fallback:

```python
from src.memory.semantic import search_facts_top_k
from src.memory.episodic import search_episodes_fts
from src.memory.procedural import match_procedural_skills
```

### Refactored `node_retrieval_gate()` Shape

```python
def node_retrieval_gate(state: AgentState) -> dict:
    messages = list(state.get("messages", []))
    last_user_msg = latest HumanMessage content
    gate_allows = should_retrieve_memory(str(last_user_msg))

    if not gate_allows or not last_user_msg:
        return unchanged skip result

    try:
        plan = build_retrieval_plan(...)
        if not plan.should_retrieve or plan.retrieval_request is None:
            return no-injection result
        bundle = retrieve_all_sources(plan.retrieval_request)
        assembled = assemble_retrieved_memory_context(
            bundle,
            ContextAssemblyOptions(
                total_token_budget=plan.total_token_budget,
                budget_by_kind=plan.budget_by_kind,
            ),
        )
        if assembled.block_text:
            messages.append(SystemMessage(content=assembled.block_text))
        return {
            "messages": messages,
            "retrieval_triggered": bool(assembled.block_text),
            "retrieved_memories": assembled.legacy_retrieved_items,
        }
    except Exception:
        return _legacy_retrieval_gate_fallback(messages, last_user_msg)
```

### Helper Function

Add a private helper in `graph.py`:

```python
def _legacy_retrieval_gate_fallback(messages: list[BaseMessage], query: str) -> dict:
    ...
```

This helper should contain the current legacy retrieval block nearly verbatim. That minimizes risk and keeps fallback behavior reviewable.

### State Compatibility

`AgentState` does not need new public fields in Phase 9B. If implementation needs internal metadata for tests, prefer not adding it to state. Tests can call planner and assembler directly. If graph-level debug is needed later, defer to Phase 10 observability.

## 12. Fallback / Failure Behavior

Fallback must be conservative.

Use legacy fallback when:

- `build_retrieval_plan()` raises unexpectedly.
- `retrieve_all_sources()` raises unexpectedly before returning a bundle.
- `assemble_retrieved_memory_context()` raises unexpectedly.

Do not fallback when:

- `should_retrieve_memory()` returns false.
- The planner returns no retrieval due to no token room.
- The bundle returns zero candidates without errors.
- One or more sources fail but at least one source succeeds and assembly succeeds.

Legacy fallback should:

- Use current `search_facts_top_k(query, k=3)`.
- Use current `search_episodes_fts(query, limit=2)`.
- Use current `match_procedural_skills(query)`.
- Append the exact current `[Retrieved Long-Term Memory]` block format.
- Return list dictionary items as today.
- Never write memory.

Fallback errors:

- If legacy fallback also fails, return messages unchanged, `retrieval_triggered=False`, `retrieved_memories=[]`.
- Do not fail chat because retrieval failed.

## 13. Compatibility Boundaries

API compatibility:

- No `/api/chat` request field changes.
- No `/api/chat` response field changes.
- No `/api/memory` or `/api/memory/full` changes.
- No data inspector allow-list changes.

Runtime compatibility:

- `node_agent()` unchanged.
- Primary LLM routing unchanged.
- Secondary LLM routing unchanged.
- No worker/job behavior changes.
- No memory writes.
- No schema/migrations.

Prompt compatibility:

- Keep `[Retrieved Long-Term Memory]` header.
- Keep semantic, episode, and procedural section labels recognizable.
- Add `Conversation Summaries:` only when summary candidates are included.
- Do not include raw debug metadata in the prompt.

Legacy wrapper compatibility:

- Keep `search_facts_top_k()`, `search_episodes_fts()`, and `match_procedural_skills()` unchanged.
- Keep these imports in graph only for fallback.
- Existing tests for these wrappers should continue to pass.

Phase 9A compatibility:

- Use `RetrievalRequest`, `RetrievalBundle`, `RetrievedMemoryCandidate`, and `retrieve_all_sources()` as designed.
- Do not alter Phase 9A ranking behavior unless a bug blocks Phase 9B.
- Do not call write-capable embedding helpers.

## 14. Test Plan

### Planner Tests

Create `tests/test_phase9b_retrieval_planner.py`.

Test cases:

- Greeting/math skip remains governed by `should_retrieve_memory()` at graph level.
- `classify_retrieval_task()` identifies identity/preference queries.
- `classify_retrieval_task()` identifies episodic recall queries.
- `classify_retrieval_task()` identifies procedural how-to queries.
- `classify_retrieval_task()` identifies project context queries.
- `classify_retrieval_task()` identifies summary context queries.
- Ambiguous query uses deterministic priority order.
- Memory kind selection matches policy table.
- Token allocation sums to total budget.
- Token allocation excludes unselected memory kinds.
- No token room returns `should_retrieve=False`.
- Planner does not call LLM route helpers that create models.

### Context Assembler Tests

Create `tests/test_phase9b_context_assembler.py`.

Test cases:

- Empty bundle returns empty block and empty retrieved items.
- Header is `[Retrieved Long-Term Memory]`.
- Semantic section uses legacy `Semantic Facts:` label and bullet format.
- Episodic section uses legacy `Past Episodes:` label.
- Procedural section uses legacy `Procedural Skills:` label.
- Summary section uses `Conversation Summaries:` label.
- Assembly respects total token budget.
- Assembly respects per-kind token budget.
- Omitted candidate IDs are reported internally.
- Debug metadata is not included in block text.
- Legacy retrieved item dictionaries are stable and JSON-serializable.

### Graph Integration Tests

Create `tests/test_phase9b_graph_retrieval_integration.py`.

Test cases:

- Simple greeting does not retrieve and appends no context block.
- Simple math does not retrieve and appends no context block.
- Query with semantic fact appends one retrieved memory system block.
- Query with structured episode uses new structured episode retrieval, not legacy FTS episode table.
- Query with approved procedural skill includes procedural section.
- Summary block can be included when task type selects summaries.
- Current user message remains present exactly once.
- `/api/chat` response shape remains unchanged.
- `node_agent()` remains primary-route behavior only.

### Fallback Tests

Create `tests/test_phase9b_retrieval_fallback.py`.

Test cases:

- Planner exception falls back to legacy wrappers.
- Retrieval bundle exception falls back to legacy wrappers.
- Assembler exception falls back to legacy wrappers.
- Single source failure in `retrieve_all_sources()` does not fallback if other candidates exist.
- Legacy fallback failure does not fail chat.
- Fallback uses existing block text format.

### Budgeting Tests

Create `tests/test_phase9b_retrieval_budgeting.py`.

Test cases:

- Retrieval budget uses primary context window diagnostics.
- Large context window caps retrieval budget at 4096 tokens.
- Small context window does not exceed available input room.
- Per-kind budget prevents one memory kind from consuming everything.
- Final assembled context token estimate is less than or equal to budget.

### Regression Tests To Run

Focused Phase 9B tests:

```powershell
python -m pytest tests/test_phase9b_retrieval_planner.py tests/test_phase9b_context_assembler.py tests/test_phase9b_graph_retrieval_integration.py tests/test_phase9b_retrieval_fallback.py tests/test_phase9b_retrieval_budgeting.py -q
```

Phase 9A regression:

```powershell
python -m pytest tests/test_phase9a_retrieval_types.py tests/test_phase9a_retrieval_ranker.py tests/test_phase9a_summary_retrieval.py tests/test_phase9a_episodic_retrieval.py tests/test_phase9a_semantic_retrieval.py tests/test_phase9a_procedural_retrieval.py tests/test_phase9a_retrieval_sources_bundle.py tests/test_phase9a_retrieval_compatibility.py -q
```

Graph/API/harness regression:

```powershell
python -m pytest tests/test_api_server.py tests/test_harness.py tests/test_long_term_memory.py tests/test_procedural_memory.py -q
```

Full suite:

```powershell
python -m pytest -q
```

## 15. Risks

Risk: Adaptive retrieval changes answer content.

Mitigation:

- Preserve the existing memory block header and section labels.
- Keep legacy fallback.
- Add graph tests that assert the context block is present and bounded, not overfit to exact ranking unless deterministic fixtures require it.

Risk: Token budgeting underestimates prompt size.

Mitigation:

- Use Phase 5A token budget primitives.
- Keep retrieval budget conservative.
- Trim whole candidates first.
- Add tests for small context windows.

Risk: Retrieval source errors could suppress useful memory.

Mitigation:

- Use Phase 9A source failure isolation.
- Fallback only for planner/assembly/global failures.
- Continue with partial source success.

Risk: Debug metadata leaks into chat or API.

Mitigation:

- Keep debug only in planner/assembler return objects.
- Do not add state fields or API fields in Phase 9B.
- Add tests that block text excludes score/provenance/debug JSON.

Risk: Procedural retrieval increments usage stats accidentally.

Mitigation:

- Keep Phase 9A procedural source read-only.
- Add graph-level tests with monkeypatched `record_used()`/`reload_active_skills()` failures.

Risk: Semantic retrieval generates embeddings accidentally.

Mitigation:

- Continue forbidding `top_k_similar_facts()` in retrieval path.
- Add tests that missing embeddings remain missing after graph retrieval.

Risk: Fallback path duplicates context blocks.

Mitigation:

- Ensure new retrieval and fallback are mutually exclusive in `node_retrieval_gate()`.
- Add tests that exactly one `[Retrieved Long-Term Memory]` system block is appended.

## 16. Acceptance Criteria

Phase 9B is accepted when:

- `src/memory/retrieval_planner.py` exists and contains deterministic planning helpers.
- `src/memory/context_assembler.py` exists and assembles token-bounded memory context blocks.
- `node_retrieval_gate()` uses the new planner, Phase 9A retrieval bundle, and context assembler.
- Simple greeting/math retrieval skips still work.
- Final memory context block starts with `[Retrieved Long-Term Memory]`.
- Semantic, episodic, procedural, and summary sections are included only when selected and non-empty.
- Retrieval context respects total token budget and per-kind allocation.
- Retrieval failures do not fail chat.
- Legacy fallback works for global planner/retrieval/assembly failures.
- Debug metadata is not exposed publicly by default.
- No memory stores are modified.
- No memory writes are introduced.
- No LLM calls are introduced.
- No schema/migration/API response/worker changes are introduced.
- Phase 9A tests still pass.
- Graph/API/harness regression tests pass.
- Full suite passes or any failure is clearly unrelated and documented.

## 17. Implementation Checklist

1. Create `src/memory/retrieval_planner.py`.
2. Add task type literals and planner dataclasses.
3. Implement deterministic query normalization and task classification.
4. Implement memory-kind selection policy.
5. Implement retrieval token budget calculation using Phase 5A token budget primitives.
6. Implement per-kind budget allocation.
7. Implement `build_retrieval_plan()` returning a `RetrievalRequest`.
8. Create `src/memory/context_assembler.py`.
9. Add context assembly dataclasses.
10. Implement candidate formatting by memory kind.
11. Implement legacy-compatible retrieved item conversion.
12. Implement total and per-kind token trimming during assembly.
13. Modify `src/harness/graph.py` imports for planner, retriever, and assembler.
14. Extract current legacy retrieval logic into a private fallback helper.
15. Refactor `node_retrieval_gate()` to use the new planner/retriever/assembler.
16. Ensure fallback uses legacy wrappers and current block format.
17. Add Phase 9B planner tests.
18. Add context assembler tests.
19. Add graph integration tests.
20. Add fallback tests.
21. Add budget tests.
22. Run focused Phase 9B tests.
23. Run Phase 9A regression tests.
24. Run graph/API/harness regression tests.
25. Run full suite.
26. Perform filesystem wiring check.

## 18. Filesystem Wiring Check Required After Implementation

Before final implementation approval, verify actual filesystem state, not only the UI edited-files list.

Required checks:

- Verify `src/memory/retrieval_planner.py` exists.
- Verify `src/memory/context_assembler.py` exists.
- Verify `src/harness/graph.py` was modified only for `node_retrieval_gate()` imports/body and private fallback helper.
- Verify `src/memory/retrieval_gate.py` was not modified.
- Verify `src/memory/retrieval_types.py`, `src/memory/retrieval_ranker.py`, and `src/memory/retrieval_sources.py` were not modified except documented bug fixes.
- Verify `src/api/server.py` was not modified.
- Verify worker/job modules were not modified.
- Verify schema/migration files were not modified.
- Verify memory store modules were not modified.
- Verify retrieval path does not call LLM route helpers that instantiate models.
- Verify retrieval path does not call `.invoke()`.
- Verify retrieval path does not call embedding upsert helpers.
- Verify retrieval path does not call `SemanticFactStore.add_explicit_fact()`.
- Verify retrieval path does not call procedural usage write helpers.
- Verify no API response shapes changed.
- Verify no chat response shape changed.
- Verify no memory writes are introduced.

Suggested commands:

```powershell
git status --short
rg -n "resolve_primary_llm|resolve_secondary_llm|get_primary_llm|get_secondary_llm|\.invoke\(|upsert_embedding|top_k_similar_facts|add_explicit_fact|record_used|reload_active_skills|INSERT|UPDATE|DELETE|commit\(" src/memory/retrieval_planner.py src/memory/context_assembler.py src/harness/graph.py
```

Expected result:

- New planner and assembler files are present.
- `graph.py` is the only runtime file changed.
- No schema/API/worker/store files changed.
- Static scan finds no forbidden calls in planner/assembler and only legacy read-wrapper calls in the graph fallback.
