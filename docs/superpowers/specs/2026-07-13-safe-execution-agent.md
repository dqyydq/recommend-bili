# Safe Execution Agent Design

## Goal

Turn an approved organization plan into a controlled operation. The first release
only removes favorites that Bilibili now reports as invalid. It must never move,
deduplicate, or otherwise alter a valid favorite.

## Scope

- A plan action is eligible only when its action type is `review_stale` or
  `review_duplicate`, its state is `approved`, and the plan itself is approved.
- The executor rechecks each candidate against Bilibili immediately before any
  mutation. Only candidates confirmed invalid are sent to Bilibili's existing
  batch-delete endpoint.
- Actions that remain valid or cannot be checked are recorded as skipped; they
  are not deleted.
- The response exposes per-action outcomes, plus aggregate counts. The UI can
  render those outcomes from the stored plan.

## Data Model

Add execution fields to `organization_plans` and
`organization_plan_actions`:

- Plan: `execution_status` (`idle`, `running`, `completed`, `partial_failed`,
  `failed`), start and completion timestamps.
- Action: `execution_state` (`pending`, `deleted`, `skipped_valid`,
  `skipped_unreachable`, `failed`), execution timestamp and a bounded
  user-visible result message.

An execution request atomically claims an approved, idle plan before contacting
Bilibili. A repeated click while a job is running returns the current plan
instead of starting a second operation.

## API And Flow

`POST /api/agents/organization-plans/{plan_id}/execute` requires a trusted
origin and an authenticated session.

1. Load the plan by the session UID and atomically claim it.
2. Recheck the approved items concurrently with a conservative bounded limit.
3. Group only confirmed-invalid resources by folder and call the existing
   Bilibili batch-delete endpoint.
4. Persist every action outcome and the final plan execution status.
5. Write an operation log with counts only, mark a sync required when at least
   one deletion succeeds, and start a background sync.

No client supplied item identifiers are accepted by this endpoint. The plan is
the server-side source of truth.

## Failures And Safety

- Missing CSRF cookie, rejected Bilibili response, and transport failures leave
  the corresponding action undeleted and recorded as failed or unreachable.
- A partially successful batch returns `partial_failed`; it does not hide the
  successful deletions.
- Results are idempotent: terminal actions are not run again. A later retry may
  re-run only actions that ended in a retryable failure.
- There is no fake rollback: Bilibili deletion is irreversible, so each action
  is independently approved and revalidated at execution time.

## Verification

- Database tests cover claim, per-action updates, duplicate-click prevention,
  and retry eligibility.
- Service tests mock Bilibili validation and deletion for valid, invalid,
  transport failure, and partial batch failure cases.
- Frontend build verifies the execute control and its terminal result states.

## Deferred Work

Moving favorites between folders and deleting duplicates remain suggestion-only.
They require verified Bilibili resource-ID contracts, pre-execution snapshots,
and an explicit product decision about irreversible moves.
