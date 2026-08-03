# Phase 4 Design: Correct Dual-LLM Role Routing

## 1. Executive Summary

Phase 4 introduces explicit role-aware LLM routing so primary models are used only for user-facing work and secondary models are used only for background memory jobs. The phase creates a thin routing layer over the existing provider catalog rather than replacing the catalog or changing public API shapes.

The target behavior is:

- Chat/agent response generation resolves only the primary role.
- Background memory job handlers resolve only the secondary role.
- Memory enqueue payloads preserve primary and secondary selectors for later worker execution.
- If the secondary model is unavailable, chat still succeeds and memory jobs fail/retry/dead-letter through Phase 3B infrastructure.
- Existing provider/model APIs remain backward compatible.

Phase 4 does not implement semantic extraction, episode generation, procedural generation, retrieval changes, or real memory LLM handlers. It only provides the boundaries and model resolution rules future handlers must use.

## 2. Scope

In scope:

- Add a role-aware LLM router.
- Define primary/secondary model selector normalization.
- Define fallback rules for provider aliases, missing models, unknown providers, and unavailable credentials.
- Update chat-side primary LLM resolution to use the router.
- Update worker-side secondary LLM resolution boundary for future real handlers.
- Ensure job payload model selectors from Phase 3A are preserved and can be resolved.
- Eliminate secondary-model use from chat-side title generation or route it outside the memory secondary role.
- Preserve `/api/chat` and `/api/models` compatibility.
- Add tests for mixed-provider primary/secondary routing and failure isolation.

Likely files for implementation:

- `src/harness/llm_router.py` new
- `src/harness/models.py`
- `src/harness/graph.py`
- `src/api/server.py`
- `src/memory/jobs.py`
- `src/memory/job_router.py`
- `src/memory/job_handlers.py`
- `src/memory/worker.py`
- Tests only

## 3. Out of Scope

Phase 4 must not implement:

- Semantic extraction.
- Episode generation.
- Procedural candidate generation.
- Semantic or procedural consolidation.
- Skill promotion.
- Skill writing.
- Embeddings.
- Retrieval changes.
- Real memory LLM handlers.
- Queue schema changes.
- Worker auto-start.
- Chat response shape changes.

No Phase 4 worker handler should call an LLM to perform memory work. It may verify that a secondary route can be resolved or return metadata for future handlers, but no prompts should be sent for memory processing in this phase.

## 4. Current Model Routing Assessment

### `src/harness/models.py`

Current strengths:

- Central provider catalog exists in `SUPPORTED_PROVIDERS`.
- Tiered pair defaults exist in `MODEL_PAIRS`.
- Context window lookup is centralized.
- `get_model_instance()` handles OpenAI, Anthropic, Gemini, and Grok.
- Existing wrappers `get_primary_llm()` and `get_secondary_llm()` provide rough role intent.
- `get_model_role_config()` exposes Phase 1 primary/secondary default metadata.

Current gaps:

- Role selection is caller-driven and not enforced by a single router.
- `get_secondary_llm(provider=...)` interprets the `provider` argument as the secondary provider, but older call sites sometimes pass the primary provider.
- Provider alias normalization, especially `xai` -> `grok`, exists in `src/api/server.py` but not as a shared model-selector rule.
- Unknown provider fallback happens inside `get_model_instance()`, but callers do not get structured diagnostics.
- Missing credentials return `None`, but there is no role-aware result that distinguishes unavailable secondary from primary offline fallback.

### `src/harness/graph.py`

Current behavior:

- `node_agent()` calls `get_primary_llm(provider=provider, model_name=model_name)` for user-facing response generation.
- If primary LLM resolution returns `None`, graph uses an offline AIMessage fallback and chat still succeeds.
- `node_consolidate()` is enqueue-only after Phase 3A and does not call secondary LLMs.
- Retrieval still uses legacy stores, but this phase must not change retrieval behavior.

Gaps:

- `node_agent()` should route through a role-aware primary resolver instead of a direct factory wrapper.
- Existing compatibility imports for legacy tests (`extract_and_save_facts`, `log_episode`) remain in `graph.py`; Phase 4 should avoid adding any new memory behavior calls.

### `src/harness/state.py`

Current state already includes:

- `provider`
- `model_name`
- `secondary_provider`
- `secondary_model_name`
- `memory_job_ids`

This is sufficient for Phase 4. No new state fields are required unless implementation wants optional route diagnostics for tests. Any additions must be optional and must not affect API response shape.

### `src/api/server.py`

Current behavior:

- `/api/chat` accepts `provider`, `model_name`, `secondary_provider`, and `secondary_model_name`.
- API code normalizes `xai` to `grok`.
- API builds graph state with primary and secondary selectors.
- On first turn of temporary sessions, API calls `generate_thread_title()` with secondary selector arguments before invoking the graph.

Gaps:

- Provider normalization is duplicated at the API layer and should move into the router.
- First-turn title generation may use `get_secondary_llm()` during chat. This violates the strict Phase 4 goal if secondary role means background-memory-only. Phase 4 should route title generation as chat-side auxiliary work using the primary role or deterministic fallback, or defer LLM title generation out of the chat path.
- API response shape must not change.

### `src/memory/jobs.py`

Current behavior:

- Enqueued payloads include:
  - `models.primary_provider`
  - `models.primary_model_name`
  - `models.secondary_provider`
  - `models.secondary_model_name`
- Idempotency includes both primary and secondary selectors.

This aligns with Phase 4. The payload structure should remain stable. At most, Phase 4 can normalize selector values before persistence so worker routing is consistent.

### `src/memory/worker.py`, `src/memory/job_router.py`, `src/memory/job_handlers.py`

Current behavior:

- Worker claims jobs and dispatches to no-op handlers.
- No-op handlers do not call LLMs.
- Router decodes payload and dispatches by job type.

Phase 4 integration point:

- Add a worker-side secondary-route resolver utility that real future handlers can use.
- Keep no-op handlers no-op.
- Do not instantiate secondary LLMs in the default no-op handler path unless a test explicitly calls a resolver function.

## 5. Proposed LLM Router Design

Create `src/harness/llm_router.py`.

Responsibilities:

- Normalize provider aliases and model selectors.
- Resolve role-specific model defaults.
- Instantiate model clients through `src.harness.models.get_model_instance()`.
- Return structured route results with diagnostics.
- Enforce role boundaries for callers.

Non-responsibilities:

- No prompts.
- No memory extraction.
- No provider catalog replacement.
- No retry/dead-letter logic.
- No chat response formatting.

Design-level types:

```python
ModelRole = Literal["primary", "secondary"]

@dataclass(frozen=True)
class LLMSelector:
    role: ModelRole
    provider: str
    model_name: str
    temperature: float
    context_window: int
    source: str

@dataclass(frozen=True)
class LLMRouteResult:
    selector: LLMSelector
    llm: Any | None
    available: bool
    fallback_used: bool
    error: str | None = None
```

Public functions:

```python
def normalize_provider(provider: str | None) -> str: ...
def normalize_model_name(provider: str, model_name: str | None, role: ModelRole) -> str: ...
def resolve_llm_selector(
    role: ModelRole,
    provider: str | None = None,
    model_name: str | None = None,
    temperature: float | None = None,
    source: str = "runtime",
) -> LLMSelector: ...
def resolve_primary_llm(provider: str | None = None, model_name: str | None = None) -> LLMRouteResult: ...
def resolve_secondary_llm(provider: str | None = None, model_name: str | None = None) -> LLMRouteResult: ...
def resolve_secondary_from_job_payload(payload: Mapping[str, Any]) -> LLMRouteResult: ...
```

`src/harness/models.py` should remain the provider catalog and instantiation layer. The new router should call existing functions instead of duplicating provider implementation.

### Fallback rules

Provider normalization:

- `None`, empty string -> `openai`
- `xai` -> `grok`
- known provider -> lowercase known provider
- unknown provider -> `openai` with `fallback_used=True`

Model normalization:

- If provided model name is non-empty, keep it unless it maps to a known future alias handled by `get_model_instance()`.
- If missing:
  - primary role uses `MODEL_PAIRS[provider]["primary"]`, fallback `gpt-4o-mini`.
  - secondary role uses `MODEL_PAIRS[provider]["secondary"]`, fallback `gpt-4o-mini`.
- Context window comes from `get_context_window(model_name, provider)`.

Temperature defaults:

- Primary: `0.7`
- Secondary: `0.3`
- Defaults should align with Phase 1 `MemoryArchitectureConfig`.

Availability:

- `available=True` only when `get_model_instance()` returns an LLM object.
- Missing keys, placeholder keys, import failures, provider errors, and construction errors return `available=False` with `llm=None`.
- Primary unavailability is handled by chat offline fallback.
- Secondary unavailability is handled by worker failure isolation.

## 6. Primary Role Behavior

Primary role is used for:

- User-facing `node_agent()` response generation.
- Tool-call reasoning in the graph.
- Optional chat-side title generation if title generation remains synchronous.

Primary role must not be used for:

- Background memory extraction.
- Episode generation.
- Semantic deduplication.
- Procedural skill generation.
- Memory consolidation.

`node_agent()` design:

```python
route = resolve_primary_llm(
    provider=state.get("provider"),
    model_name=state.get("model_name"),
)
llm = route.llm
context_window = route.selector.context_window
```

If `route.available` is false:

- Keep the current offline fallback response behavior.
- Use normalized selector values for fallback response text.
- Do not raise because provider credentials are absent.

Short-term memory context-window lookup:

- `node_manage_memory()` should use the primary selector/context window.
- It should not infer context from secondary fields.

Title generation:

- Preferred Phase 4 behavior: make chat first-turn title generation primary-role or deterministic, not secondary-role.
- If title generation needs an LLM during chat, call `resolve_primary_llm()` or a dedicated `resolve_chat_auxiliary_llm()` that is explicitly classified as primary/user-facing.
- Do not call `get_secondary_llm()` from the chat path.
- Preserve existing test expectations that a non-empty title is produced, using deterministic fallback when no primary LLM is available.

## 7. Secondary Role Behavior

Secondary role is used only for:

- Background memory jobs running outside chat.
- Future semantic extraction handlers.
- Future episodic generation handlers.
- Future semantic/procedural consolidation handlers.
- Future procedural candidate and skill promotion handlers.

Secondary role must not be used for:

- `/api/chat` response generation.
- Chat-side title generation after Phase 4.
- Retrieval injection.
- Tool-call planning.

Worker-side selector source order:

1. Job payload `models.secondary_provider` and `models.secondary_model_name`.
2. Phase 1 memory config secondary defaults.
3. Provider/model fallback rules in `llm_router.py`.

Design function:

```python
def resolve_secondary_from_job_payload(payload: Mapping[str, Any]) -> LLMRouteResult:
    models = payload.get("models", {})
    return resolve_secondary_llm(
        provider=models.get("secondary_provider"),
        model_name=models.get("secondary_model_name"),
    )
```

Phase 4 no-op handlers:

- Should not instantiate or invoke secondary LLMs by default.
- May accept an injected `LLMRouteResult` or resolver in tests/future handlers.
- Real memory handlers in later phases must call only `resolve_secondary_from_job_payload()`.

## 8. Worker Integration Plan

Phase 3B worker stays explicit-call only. Phase 4 should not auto-start it.

Recommended integration:

- Add `src/harness/llm_router.py`.
- Extend `MemoryJobRouter.dispatch()` to pass decoded payload to handlers as it already does.
- Add a small helper in router or handlers for future use:

```python
def resolve_memory_job_secondary_route(payload: Mapping[str, Any]) -> LLMRouteResult:
    return resolve_secondary_from_job_payload(payload)
```

- Keep default no-op handlers independent from the resolver.
- Future real handlers can depend on the helper without knowing API state shape.

Worker failure isolation when secondary unavailable:

- Future handler calls `resolve_secondary_from_job_payload(payload)`.
- If `available=False`, handler returns `JobHandlerResult(success=False, retryable=True, result={...})`.
- Phase 3B worker retry/dead-letter infrastructure handles the failure.
- Chat is unaffected because worker execution is outside chat.

Result/error shape for unavailable secondary:

```json
{
  "handler": "semantic_candidate_extraction",
  "processed": false,
  "phase": "4-routing",
  "message": "Secondary LLM unavailable",
  "provider": "anthropic",
  "model_name": "claude-3-5-haiku-latest"
}
```

This is a boundary contract for later phases, not a real memory handler implementation.

## 9. API Compatibility

`/api/chat` request fields remain unchanged:

- `message`
- `session_id`
- `provider`
- `model_name`
- `secondary_provider`
- `secondary_model_name`

`/api/chat` response fields remain unchanged.

API normalization changes:

- Move provider alias normalization into `llm_router.normalize_provider()`.
- `api_chat()` may still call normalization helpers before building state.
- `xai` remains accepted and maps to `grok`.
- Unknown provider falls back to OpenAI behavior, matching current factory behavior.

`/api/models` remains backward compatible:

- Preserve existing `catalog`.
- Preserve existing `memory_defaults`.
- Additive optional field allowed:

```json
{
  "catalog": {},
  "memory_defaults": {},
  "role_routing": {
    "primary_default": {},
    "secondary_default": {},
    "provider_aliases": {"xai": "grok"}
  }
}
```

This additive field is optional. Existing tests expecting `catalog` and provider entries must continue to pass.

## 10. Failure Handling

Primary unavailable:

- `resolve_primary_llm()` returns `available=False`, `llm=None`.
- `node_agent()` uses current offline fallback.
- Chat returns normally.

Secondary unavailable:

- Chat does not fail.
- Enqueue still succeeds because it only stores selectors.
- Worker-side future memory handlers return retryable failure.
- Phase 3B retry/dead-letter handles eventual exhaustion.

Invalid provider/model:

- Normalize provider first.
- Missing model uses role default.
- Unknown provider falls back to OpenAI and reports `fallback_used=True`.
- Unknown model name is passed through to `get_model_instance()`; if instantiation fails, route returns unavailable.

Router construction errors:

- `llm_router` catches provider import/construction failures via `get_model_instance()` behavior and structured route result.
- It should not raise in normal chat or worker routing paths for missing credentials.

Title generation:

- If primary title LLM is unavailable, deterministic fallback title generation should be used.
- Title failure must not fail chat.

## 11. Test Plan

Suggested new test file:

- `tests/test_phase4_llm_router.py`

Suggested updates:

- `tests/test_tiered_models.py`
- `tests/test_dual_llm_selectors.py`
- `tests/test_model_selection_and_thread_title.py`
- Phase 3A/3B job payload/worker tests as regression coverage.

Router unit tests:

- `normalize_provider("xai") == "grok"`.
- Unknown provider falls back to `openai` and marks fallback.
- Primary selector defaults to provider primary model.
- Secondary selector defaults to provider secondary model.
- Provided model name is preserved.
- Context windows come from `get_context_window()`.
- Missing credentials return `available=False` without raising.

Primary chat routing tests:

- `node_agent()` calls `resolve_primary_llm()` or equivalent primary route, not `get_secondary_llm()`.
- Mixed provider state, such as OpenAI primary plus Anthropic secondary, uses OpenAI for `node_agent()`.
- Primary unavailable produces offline fallback and chat succeeds.
- Chat first-turn title generation does not call secondary resolver.
- `/api/chat` accepts existing selector fields and returns existing response shape.

Secondary worker routing tests:

- `resolve_secondary_from_job_payload()` uses `payload.models.secondary_provider`.
- Mixed provider job, such as OpenAI primary plus Anthropic secondary, resolves Anthropic secondary.
- Missing secondary credentials return unavailable route without raising.
- Future handler boundary can convert unavailable secondary into retryable `JobHandlerResult`.
- No-op Phase 3B handlers still do not call LLMs.

Failure isolation tests:

- Secondary resolver monkeypatched to unavailable: chat still succeeds and memory job remains queued or worker retries when explicitly processed by a test handler.
- Primary resolver monkeypatched unavailable: chat returns offline fallback.
- Invalid secondary provider in payload does not crash worker route resolution.

Regression tests:

- Phase 1 memory interface/config tests.
- Phase 3A enqueue tests.
- Phase 3B worker tests.
- Existing model/provider tests.
- Full suite if feasible.

## 12. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Secondary model still used in chat title path | Violates role separation | Move title generation to primary-role route or deterministic fallback. |
| Breaking existing direct helper tests | Test churn and API confusion | Keep `get_primary_llm()` and `get_secondary_llm()` as compatibility wrappers backed by router rules. |
| Over-refactoring provider catalog | Larger diff and new bugs | Leave `MODEL_PAIRS`, `SUPPORTED_PROVIDERS`, `get_model_instance()`, and context windows mostly intact. |
| Secondary unavailable causes chat failure | User-facing regression | Enqueue stores selectors only; worker failures retry outside chat. |
| Future handlers choose wrong provider | Incorrect memory cost/quality | Provide `resolve_secondary_from_job_payload()` and tests for mixed providers. |
| Unknown provider fallback hides config mistakes | Silent misrouting | Return structured `fallback_used` diagnostics while preserving current fallback behavior. |
| Circular imports between router/models/config | Runtime import errors | Keep `llm_router.py` thin; `models.py` owns catalog and instantiation, router owns selection. |

## 13. Acceptance Criteria

Phase 4 is complete when:

- A role-aware router exists for primary and secondary LLM resolution.
- Primary chat generation uses primary route only.
- Secondary route is not used by `/api/chat` or `node_agent()`.
- Chat first-turn title generation no longer uses secondary role.
- Memory job payload selectors remain stable and include primary/secondary metadata.
- Worker/future handler boundary can resolve secondary route from job payload.
- Secondary unavailable does not break chat.
- Primary unavailable still uses offline fallback.
- Mixed-provider combinations are preserved and tested.
- Existing `/api/chat` request/response shape remains backward compatible.
- Existing `/api/models` behavior remains backward compatible.
- No semantic extraction, episodic generation, procedural generation, retrieval changes, or real memory LLM handlers are implemented.
- Full model/provider and Phase 3 queue/worker tests pass.

## 14. Implementation Checklist

1. Create `src/harness/llm_router.py`.
2. Define `LLMSelector` and `LLMRouteResult`.
3. Add provider alias normalization.
4. Add model default resolution for primary and secondary roles.
5. Add `resolve_primary_llm()`.
6. Add `resolve_secondary_llm()`.
7. Add `resolve_secondary_from_job_payload()`.
8. Keep `src/harness/models.py` as the provider catalog and client factory.
9. Optionally update `get_primary_llm()` and `get_secondary_llm()` wrappers to delegate to the router while preserving return shapes.
10. Update `src/harness/graph.py` `node_agent()` to resolve primary via the router.
11. Update `node_manage_memory()` to use normalized primary selector context.
12. Update `/api/chat` provider normalization to use router helper.
13. Change first-turn title generation to primary-role or deterministic fallback; do not use secondary role in chat.
14. Add worker-side helper or contract for secondary route resolution from job payload.
15. Keep no-op handlers no-op.
16. Add mixed-provider routing tests.
17. Add unavailable-primary and unavailable-secondary tests.
18. Run Phase 1 model/config tests.
19. Run Phase 3A/3B queue and worker tests.
20. Run full suite if feasible.

## File-by-File Design

### New: `src/harness/llm_router.py`

Add the role-aware selector and route result layer. This file should import catalog/factory helpers from `src.harness.models`, but `models.py` should not need to import the router at module import time unless wrapper delegation is carefully done inside functions.

### Modify: `src/harness/models.py`

Keep:

- `CONTEXT_WINDOW_CAPACITIES`
- `MODEL_PAIRS`
- `SUPPORTED_PROVIDERS`
- `get_model_catalog()`
- `get_model_instance()`
- `get_context_window()`

Possible refactor:

- Have `get_primary_llm()` and `get_secondary_llm()` delegate to `llm_router` internally while preserving current return shapes:
  - `get_primary_llm()` returns `(llm, context_window)`.
  - `get_secondary_llm()` returns `llm`.

This preserves legacy tests and call sites.

### Modify: `src/harness/graph.py`

Update:

- `node_agent()` to use primary route.
- `node_manage_memory()` to use normalized primary context window.

Do not change:

- `node_consolidate()` enqueue-only behavior.
- Retrieval behavior.
- Graph edges.
- Chat response state shape.

### Modify: `src/api/server.py`

Update:

- Provider normalization to call router helper.
- First-turn title generation to avoid secondary role.

Do not change:

- `ChatRequest` field names.
- `/api/chat` response fields.
- Data inspector behavior.

### Modify: `src/memory/jobs.py`

Only if needed:

- Normalize provider values before storing payload selectors.
- Preserve existing payload keys and idempotency semantics.

### Modify: `src/memory/job_router.py` or `src/memory/job_handlers.py`

Only if needed:

- Add future-handler helper to resolve secondary from job payload.
- Keep no-op handlers from invoking LLMs.

### Avoid Modify: `src/memory/worker.py`

No required worker-loop changes. If adding route diagnostics, keep them outside automatic execution and do not auto-start workers.

## Compatibility With Future Phases

Phase 7 and Phase 8 real memory handlers should use only `resolve_secondary_from_job_payload()` for LLM work. They should never inspect API request fields directly and should never fall back to the primary route for memory processing. Phase 4's main value is establishing that boundary before real memory LLM behavior arrives.

