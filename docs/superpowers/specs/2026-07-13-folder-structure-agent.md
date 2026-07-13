# Folder Structure Agent Design

## Goal

Turn a large, flat Bilibili favorites collection into an actionable folder
structure. The Agent delivers a reviewed organization blueprint rather than a
one-off category report.

## Information Architecture

The target structure is two levels:

- Level one is purpose: `待学习`, `待消遣`, `常用资料`, and `已完成/待复查`.
- Level two is a topic inferred from the user's saved content, such as `RAG 与
  知识库`, `Agent 开发`, `FastAPI`, `Python`, or `纪录片`.

The Agent limits the second level to a configurable sensible range, consolidates
near-duplicate topic names, and does not force low-confidence items into a
topic. They are placed in `待复查` with an explanation.

## Blueprint Workflow

1. Read the PostgreSQL favorite snapshot; do not re-crawl Bilibili.
2. Derive candidate purpose/topic groups from embeddings, existing folders,
   titles, descriptions, and favorite recency.
3. Produce a blueprint containing proposed folders, item counts, representative
   examples, confidence distribution, and folder-level action batches.
4. Persist the blueprint as a draft. The UI supports reviewing, skipping, or
   confirming each destination folder independently.
5. Confirmation creates a server-side execution batch. Before each mutation the
   executor verifies that every source favorite still exists in the expected
   folder. It records per-item results and triggers incremental synchronization.

## Safety

- The Agent never removes old folders in the first release.
- It never moves a low-confidence item without an explicit user confirmation.
- New folders and moves are separate actions; a failure to create a folder
  prevents only that folder's batch from running.
- The client cannot submit arbitrary resource identifiers. All items and source
  folders are loaded from the persisted blueprint owned by the session UID.
- Execution uses bounded folder/item concurrency, idempotency keys, operation
  logs, and result snapshots. Partial failure is visible and retryable.

## Data Model

PostgreSQL stores:

- `folder_structure_plans`: goal, status, purpose/topic blueprint, source
  snapshot timestamp, and aggregate counts.
- `folder_structure_actions`: destination folder, source folder/media IDs,
  classification confidence, review state, execution state, and result.
- `folder_structure_batches`: per-destination execution claim, timestamps,
  retries, and summary.

Chroma may assist semantic grouping but does not own plan state or execution
history.

## UI

The Agent workspace gains a `结构蓝图` view. It renders a compact tree with
counts, examples, confidence warnings, and one confirmation control per
destination. It surfaces execution progress and links to the existing folder
view after synchronization.

## Release Boundaries

The first release can generate and review real structure plans, but execution
will be enabled only after Bilibili's create-folder and move-resource contracts
are verified against current behavior. Until then, approved actions remain a
safe, persistent queue with no remote mutation.

## Verification

- Tests cover deterministic blueprint generation, confidence routing, ownership,
  review-state transitions, and idempotent batch claims.
- A mocked executor verifies that only stored, approved actions can invoke a
  Bilibili mutation.
- A production frontend build verifies large-plan rendering without layout
  shifts.
