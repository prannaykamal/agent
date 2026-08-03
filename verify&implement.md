Implementation Plan - Phase X: Dual-LLM Memory Architecture

Implement a production-grade memory architecture for the 24x7 Personal AI Assistant. The implementation must support two LLMs (Primary + Secondary), adaptive short-term memory management, episodic memory with an episode detector, and semantic memory with both immediate extraction and periodic consolidation.

IMPORTANT DESIGN PRINCIPLES

• The Primary LLM is responsible only for user-facing tasks (conversation, reasoning, planning, tool orchestration, HITL reasoning).
• The Secondary LLM is responsible only for asynchronous memory processing.
• Memory processing must NEVER block the user response.
• All memory operations should execute in background tasks/worker.
• The assistant should remain responsive even if memory generation fails.
• Every memory component should be independently replaceable.

──────────────────────────────────────
SECTION 1: Dual LLM Architecture
──────────────────────────────────────

Implement support for two configurable LLMs.

Primary LLM responsibilities

• Conversation
• Reasoning
• Planning
• Tool Calling
• HITL reasoning
• Browser reasoning
• RAG answer generation

Secondary LLM responsibilities

• Short-term conversation summarization
• Episodic summary generation
• Semantic fact extraction
• Semantic consolidation
• Memory deduplication
• Reflection generation
• Conversation title generation
• Metadata extraction

The secondary model should always execute asynchronously.

Memory failures must never interrupt conversation.

LLM configuration should support different providers.

Example

Primary:
OpenAI GPT-5.5

Secondary:
GPT-5 nano

or

Primary:
Claude Sonnet 4

Secondary:
Gemini Flash-Lite

Implementation should allow any provider combination.

──────────────────────────────────────
SECTION 2: Short-Term Memory
──────────────────────────────────────

Implement adaptive token-budget based short-term memory.

Never use fixed message counts.

Conversation context should be calculated as

Conversation Tokens

excluding

• System Prompt
• Tool Schemas
• Retrieved Memories
• Current User Message
• Reserved Output Tokens

Conversation Budget

conversation_budget =
context_window
- system_prompt
- tool_schema
- retrieved_memory
- output_reserve
- safety_margin

Reserve

25% of total context

for

• retrieved memories
• tool schemas
• output
• safety margin

Therefore

conversation_budget = 75% of model context.

Summarization trigger

When conversation reaches

90%

of conversation_budget.

Summarization strategy

Do NOT summarize the overflow.

Instead

Summarize the oldest X%

of conversation TOKENS.

Never summarize by message count.

Adaptive chunk size

Models up to 200k context

Summarize oldest

30%

Models between 200k and 500k

Summarize oldest

25%

Models above 500k

Summarize oldest

20%

The summary should replace the removed messages.

Older summaries must NEVER be regenerated.

Maintain immutable summary blocks.

Example

Summary 1

Summary 2

Summary 3

Recent Messages

Each summary block stores

• summary
• covered message ids
• token count
• timestamp

──────────────────────────────────────
SECTION 3: Episodic Memory
──────────────────────────────────────

Implement an Episode Detector.

Episodes should NOT be generated after every message.

Generate episodes only when one of the following occurs.

Task completed

Workflow completed

Conversation trimming occurred

Conversation idle timeout

Explicit "remember this"

Long conversation session

Episode detector should use deterministic rules.

Do NOT use LLM for deciding whether an episode exists.

When triggered

Call Secondary LLM

to generate a structured episodic memory.

Episode schema

title

summary

participants

goals

decisions

artifacts

topics

importance

start_message_id

end_message_id

created_at

source

The same LLM call used for conversation trimming should also generate the episodic memory whenever trimming caused the episode.

Avoid duplicate summarization calls.

──────────────────────────────────────
Episodic Memory Continuation
──────────────────────────────────────

When a previous episodic memory is retrieved and the user continues discussing the same topic or project, the Episode Detector should attempt to UPDATE the existing episode instead of always creating a new one.

Continuation should be treated as another episode-generation trigger.

Possible actions

• CREATE
• UPDATE
• MERGE
• SPLIT

The Episode Detector should determine whether the current conversation extends an existing episode or starts a new one using retrieved episodic context, conversation history, and deterministic heuristics.

──────────────────────────────────────
SECTION 4: Semantic Memory
──────────────────────────────────────

Semantic memory has TWO write paths.

Path 1

Immediate storage.

Used only for explicit stable user facts.

Examples

"My name is..."

"My email is..."

"I prefer..."

"Remember that..."

Implement deterministic extraction using

Regex

Rule-based matching

Pattern matching

Store immediately.

No LLM required.

These memories bypass consolidation.

──────────────────────────────────────

Path 2

LLM Candidate Extraction.

After each conversation turn

The Secondary LLM should extract semantic fact candidates asynchronously.

Do NOT directly store them.

Return structured candidates.

Example

{
    fact
    category
    confidence
    explicit
}

Store candidates in

Pending Fact Queue

Do NOT write directly into semantic memory.

──────────────────────────────────────
Semantic Memory Deduplication
──────────────────────────────────────

Every semantic memory write (both immediate and consolidation) MUST perform semantic deduplication.

Process

1. Retrieve the top 3–10 semantically similar stored facts.
2. Provide the new fact, retrieved facts, and surrounding conversation/episode context to the Secondary LLM.
3. The Secondary LLM MUST classify the new fact as exactly one of:

   • NEW
   • DUPLICATE
   • UPDATE
   • MERGE

4. Execute the chosen action.

5. If UPDATE or MERGE occurred, regenerate the embedding for the final stored fact.

6. Persist the updated fact and embedding.

Deduplication is mandatory for BOTH direct semantic writes and periodic semantic consolidation.

──────────────────────────────────────
SECTION 5: Semantic Consolidation
──────────────────────────────────────

Implement periodic consolidation.

Consolidation should run asynchronously.

Trigger

Every

10 episodic memories

OR

100 pending fact candidates

OR

Daily idle maintenance

Consolidation input

Recent episodic memories

Pending fact queue

Current semantic memory

The Secondary LLM should

Extract stable facts

Merge duplicates

Increase confidence

Update changed preferences

Discard temporary facts

Generate semantic updates.

Example output

New Facts

Updated Facts

Deleted Facts

Confidence

Reason

Only after consolidation

write into Semantic Memory.

──────────────────────────────────────
SECTION 6: Procedural Memory
──────────────────────────────────────

Implement Procedural Memory using Markdown-based SKILL.md files inspired by Anthropic Agent Skills and Waku Agent.

Procedural memory stores reusable workflows describing HOW the assistant should perform recurring tasks.

Procedural memory must remain completely independent from semantic and episodic memory.

Do NOT store procedural memory inside a vector database.

Each skill must be human-readable and editable.

Assistant-generated procedural memory should never overwrite user-authored skills.

──────────────────────────────────────
Procedural Memory Write Paths
──────────────────────────────────────

Procedural memory has TWO write paths.

Path 1

Immediate Skill Creation.

Trigger only when the user explicitly provides permanent behavioral instructions.

Examples

Always do...

Never do...

From now on...

Whenever I ask...

Always follow this workflow...

These instructions should immediately generate a procedural skill.

No candidate generation.

No consolidation required.

──────────────────────────────────────

Path 2

Skill Candidate Generation.

After every newly created episodic memory

The Secondary LLM should asynchronously analyze the episode.

Determine whether the episode contains a reusable workflow.

Generate a structured Skill Candidate.

Do NOT generate SKILL.md directly.

Store candidates inside the Skill Candidate Store.

──────────────────────────────────────
Skill Candidate Schema
──────────────────────────────────────

Every Skill Candidate should contain

id

title

description

trigger_description

workflow

preferred_tools

confidence

occurrences

source_episode_ids

created_at

updated_at

status

Status

NEW

OBSERVING

READY_FOR_PROMOTION

WAITING_FOR_APPROVAL

PROMOTED

REJECTED

──────────────────────────────────────
Workflow Format
──────────────────────────────────────

Workflow steps should be structured.

Each step contains

step_number

instruction

optional_tools

Example

workflow

1.

Retrieve relevant memories

2.

Search documentation

3.

Generate implementation plan

4.

Implement incrementally

5.

Run tests

6.

Summarize output

Avoid free-form workflow descriptions.

──────────────────────────────────────
Procedural Candidate Deduplication
──────────────────────────────────────

Every newly generated Skill Candidate MUST perform deterministic candidate retrieval before deduplication.

Do NOT use vector embeddings for procedural candidate deduplication.

Candidate retrieval should first filter using

Trigger description

Preferred tools

Tags

Workflow category

Only retrieve the top 3–10 most relevant Skill Candidates and existing procedural skills.

Provide

• New candidate

• Retrieved Skill Candidates

• Retrieved procedural skills

• Supporting episodic memories

to the Secondary LLM.

The Secondary LLM MUST classify the candidate as exactly one of

NEW

DUPLICATE

UPDATE

MERGE

Execute the selected action.

If UPDATE or MERGE occurred

Merge workflow steps

Increase confidence

Merge supporting episodes

Increment occurrence count

Update metadata

The final candidate replaces the previous version.

──────────────────────────────────────
Procedural Consolidation
──────────────────────────────────────

Implement asynchronous procedural consolidation.

Trigger

Every

10 episodic memories

OR

20 procedural candidates

OR

Daily idle maintenance

Consolidation input

Recent episodic memories

Skill Candidate Store

Existing procedural skills

The Secondary LLM should

Merge duplicate workflows

Improve workflow descriptions

Merge similar candidates

Increase confidence

Discard temporary workflows

Generate procedural updates

Only update Skill Candidates.

Do NOT automatically generate SKILL.md during consolidation.

──────────────────────────────────────
Skill Promotion
──────────────────────────────────────

Skill promotion must use deterministic rules.

The LLM must NEVER decide promotion.

Promote only when

Occurrences >= configurable threshold

(default 3)

AND

Confidence >= configurable threshold

(default 0.90)

Candidates satisfying promotion requirements enter

WAITING_FOR_APPROVAL.

──────────────────────────────────────
Human Approval
──────────────────────────────────────

Assistant-generated procedural skills require approval before activation.

Display

Title

Description

Trigger

Workflow

Preferred Tools

Confidence

Occurrences

Supporting Episodes

Allow

Approve

Reject

Modify

If modified

Generate the final procedural skill using the modified workflow.

Upon approval

Generate SKILL.md

Activate the skill

Mark candidate as PROMOTED.

──────────────────────────────────────
Procedural Skill Format
──────────────────────────────────────

Every procedural skill is stored as Markdown.

Each SKILL.md begins with YAML frontmatter.

Required fields

id

name

description

version

priority

enabled

author

created_at

updated_at

confidence

tags

preferred_tools

Optional fields

dependencies

approval_required

The Markdown body should contain

Workflow

Failure Handling

Notes

Examples (optional)

──────────────────────────────────────
Skill Versioning
──────────────────────────────────────

Never overwrite an existing SKILL.md.

Every modification creates a new version.

Maintain version history.

Support rollback.

The newest approved version remains active.

──────────────────────────────────────
Skill Retrieval
──────────────────────────────────────

Procedural retrieval occurs before planning.

Retrieval pipeline

Metadata Filtering

↓

Embedding Similarity

↓

Keyword Matching

↓

Optional LLM Reranking

↓

Top 1–3 Skills

Never inject every procedural skill.

Only inject selected SKILL.md files.

Ranking should consider

Priority

Confidence

Embedding Similarity

Keyword Similarity

Recency

Usage Frequency

Disabled skills must never be retrieved.

──────────────────────────────────────
Skill Statistics
──────────────────────────────────────

Track

times_loaded

times_used

last_loaded

last_used

last_updated

Usage statistics should improve retrieval ranking.

──────────────────────────────────────
Skill Editing
──────────────────────────────────────

Users may

Create

Modify

Delete

Enable

Disable

Rename

Archive

procedural skills manually.

The loader should automatically detect file changes.

Restarting the assistant must not be required.

──────────────────────────────────────
SECTION 7: Memory Retrieval
──────────────────────────────────────

Memory retrieval is adaptive.

The planner first determines the task type.

Examples

• Coding
• Research
• Project Continuation
• Personal Question
• Planning
• General Conversation

The retrieval pipeline dynamically prioritizes

Procedural Memory

Semantic Memory

Episodic Memory

Conversation Summary Blocks

according to the detected task.

Retrieve only the memories required for the current task.

Do NOT retrieve every memory of a given type.

Each memory type should independently retrieve its top-k most relevant entries before adaptive prioritization.

The final context must always respect the model's token budget.

──────────────────────────────────────
SECTION 8: Background Memory Queue
──────────────────────────────────────

All memory processing must execute asynchronously.

Queue

Conversation Finished

↓

Background Queue

↓

Job Router

↓

Episode Generation

Semantic Candidate Extraction

Procedural Candidate Generation

Semantic Consolidation

Procedural Consolidation

Skill Promotion

↓

Memory Stores

If queue processing fails

Conversation should continue normally.

Retry failed jobs.

No user-facing latency.

──────────────────────────────────────
SECTION 9: Configuration
──────────────────────────────────────

Memory configuration should be fully configurable.

No hardcoded values.

Support configuration for

Primary LLM

Secondary LLM

Conversation Budget %

Summarization Trigger %

Adaptive Summarization %

Output Reserve

Safety Margin

Conversation Idle Timeout

Episode Generation Thresholds

Episode Idle Timeout

Maximum Conversation Summary Blocks

Maximum Episodic Memories

Maximum Pending Semantic Facts

Semantic Consolidation Frequency

Semantic Candidate Batch Size

Semantic Deduplication Top-K

Procedural Promotion Threshold

(default 3 occurrences)

Procedural Confidence Threshold

(default 0.90)

Maximum Procedural Candidates

Maximum Active Procedural Skills

Maximum Retrieved Procedural Skills

Procedural Consolidation Frequency

Background Worker Count

Maximum Queue Size

Retry Limit

Retry Backoff

Job Timeout

Queue Persistence

Idle Maintenance Interval

Monitoring should also be configurable.

Enable / Disable

Memory Metrics

Queue Metrics

Timing Metrics

Cost Metrics

The implementation should support future configuration sources

Environment Variables

YAML

JSON

Database

Configuration values should be reloadable without requiring code changes whenever possible.

──────────────────────────────────────
SECTION 10: Testing
──────────────────────────────────────

Implement comprehensive automated tests.

Dual LLM

• Routing
• Provider switching
• Failure isolation

Short-Term Memory

• Conversation budget calculation

• Token counting

• Adaptive summarization thresholds

• Token-based trimming

• Immutable summary blocks

Episode Detection

• Task completion trigger

• Workflow completion trigger

• Conversation trimming trigger

• Idle timeout trigger

• Explicit "remember this"

• Episode continuation

• CREATE

• UPDATE

• MERGE

• SPLIT

Semantic Memory

• Immediate fact extraction

• Pending Fact Queue

• Candidate extraction

• Semantic deduplication

• NEW

• DUPLICATE

• UPDATE

• MERGE

• Consolidation

• Confidence updates

Procedural Memory

• Immediate skill generation

• Skill candidate generation

• Candidate deduplication

• Procedural consolidation

• Candidate promotion

• Human approval

• Skill versioning

• SKILL.md generation

• Metadata validation

• Manual skill editing

• Automatic reload

• Retrieval ranking

Memory Retrieval

• Adaptive retrieval strategy

• Procedural retrieval

• Semantic retrieval

• Episodic retrieval

• Summary retrieval

• Context assembly

Background Memory Pipeline

• Queue execution

• Job routing

• Concurrent workers

• Retry logic

• Queue persistence

• Dead Letter Queue

• Failure recovery

• Idempotent execution

End-to-End

• Complete memory lifecycle

Conversation

↓

Episode

↓

Semantic Candidate

↓

Procedural Candidate

↓

Consolidation

↓

Retrieval

↓

Planner

Failure Testing

• Secondary LLM unavailable

• Queue failure

• Worker crash

• Database unavailable

• Partial consolidation failure

The assistant should continue responding normally even if any memory component fails.

──────────────────────────────────────
Acceptance Criteria
──────────────────────────────────────

✓ Primary and Secondary LLMs operate independently.

✓ Memory generation never blocks user responses.

✓ Short-term memory uses token budgets instead of message counts.

✓ Oldest conversation tokens are summarized adaptively.

✓ Summary blocks are immutable.

✓ Episodic memories are generated only when meaningful episodes occur.

✓ Trimming reuses the same summarization call to create episodic memory.

✓ Explicit user facts are immediately stored in semantic memory.

✓ Implicit facts are stored as candidates and consolidated later.

✓ Semantic consolidation merges, updates, deduplicates, and removes stale facts.

✓ Procedural memory stores reusable workflows as Markdown SKILL.md files.

✓ Explicit procedural instructions create skills immediately.

✓ Repeated workflows become Skill Candidates.

✓ Procedural candidates are deduplicated before promotion.

✓ Skill promotion is deterministic.

✓ Assistant-generated skills require approval.

✓ Procedural skills are versioned.

✓ Only relevant procedural skills are retrieved.

✓ Memory retrieval adapts to task type.

✓ Background pipeline supports semantic, episodic and procedural memory generation.

✓ All memory operations run asynchronously.

✓ Architecture is modular and extensible for future reflection memory, procedural memory, and multi-agent support.