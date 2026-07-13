# Safe Execution Agent Implementation Plan

**Goal:** Execute approved organization-plan actions only after a fresh server-side invalid-resource check, persist granular outcomes, and refresh the local snapshot after successful deletions.

**Architecture:** PostgreSQL owns the execution state and atomically claims a plan before a request can call Bilibili. A focused service performs validation and grouped deletion using the authenticated session cookies. The API never accepts client-provided resource IDs. The organization tab calls the execution endpoint and renders the persisted result.

## Task 1: Add persistent execution state

**Files:** `backend/database.py`

- [ ] Extend `organization_plans` with execution status and timestamps using migration-safe `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements.
- [ ] Extend `organization_plan_actions` with terminal execution state, result message, and execution timestamp.
- [ ] Add database functions to atomically claim an approved plan, read executable actions, persist an action outcome, and complete the plan.
- [ ] Make terminal outcomes idempotent and expose the execution fields from plan detail/history queries.

**Verify:** a temporary Postgres database can initialize twice, claim a plan only once, and return its persisted execution outcomes.

## Task 2: Implement the execution service

**Files:** `backend/organization_executor.py` (new)

- [ ] Load only actions from a successfully claimed plan whose review state is approved and whose execution state is retryable.
- [ ] Use the existing `_check_bvid` behavior with a bounded concurrency limit to recheck all candidates.
- [ ] Mark valid items `skipped_valid` and network/check failures `skipped_unreachable` without contacting the delete endpoint.
- [ ] Group confirmed-invalid `media_id:2` values by `folder_id`; call Bilibili batch-delete with CSRF per group.
- [ ] Record each deletion or API failure separately and aggregate the final plan status as completed, partial failed, or failed.

**Verify:** mocked validation/deletion tests cover valid, invalid, unreachable, batch rejection, and a mixed partial result.

## Task 3: Expose a guarded execution endpoint

**Files:** `backend/main.py`

- [ ] Add `POST /api/agents/organization-plans/{plan_id}/execute` behind the trusted-origin check and session dependency.
- [ ] Reject absent CSRF before claiming an operation; return the current plan for a concurrent or terminal execution request.
- [ ] Call the execution service with the server session cookies, write a counts-only operation log, and mark sync required only when deletion occurred.
- [ ] Trigger the existing background sync after at least one successful deletion.

**Verify:** FastAPI route import succeeds and the endpoint cannot act on a plan owned by another UID or on arbitrary client resource IDs.

## Task 4: Add execution controls and outcome display

**Files:** `frontend/src/api.js`, `frontend/src/agents-module.js`, `frontend/src/styles.css`

- [ ] Add an API wrapper that executes only by plan ID.
- [ ] For an approved plan, show one unambiguous execute button with a confirmation prompt that states invalid resources are rechecked before deletion.
- [ ] Disable the button during the request and show plan/action status, result message, and completion timestamp after it returns.
- [ ] Keep draft plans review-only; do not expose move or duplicate deletion controls.

**Verify:** production frontend build succeeds and the UI has stable states for idle, running, completed, partial failure, and failure.

## Task 5: Run focused verification and commit

- [ ] Compile the changed backend modules inside the activated uv environment.
- [ ] Run temporary Postgres integration checks for claim/outcome transitions and mocked Bilibili service checks.
- [ ] Build the frontend to an isolated temporary output directory to avoid interfering with an active dev server.
- [ ] Review `git diff`, preserve unrelated untracked files, and commit only the feature files and plan.
