# Folder Structure Agent Implementation Plan

## Task 1: Persist blueprints

- [ ] Add structure-plan and structure-action tables with UID ownership,
  reviewed states, confidence, and source favorite IDs.
- [ ] Add CRUD functions for creating a plan, listing plans, loading details,
  and approving/skipping a destination action.

## Task 2: Build deterministic structure blueprints

- [ ] Analyze the local favorite snapshot without a Bilibili crawl.
- [ ] Assign purpose from recency/title signals and topic from a conservative
  keyword taxonomy; route uncertain items to `待复查`.
- [ ] Consolidate each destination into a compact action with count and
  representative items, then persist it as a draft plan.

## Task 3: Expose review APIs

- [ ] Add UID-scoped endpoints to build, list, load, and review blueprints.
- [ ] Require trusted origins for mutation endpoints and log only aggregate
  review actions.

## Task 4: Add the structure blueprint workspace

- [ ] Add a `结构蓝图` Agent tab with purpose/topic tree, counts, examples,
  confidence warnings, history, and per-destination review controls.

## Task 5: Verify and commit

- [ ] Add unit tests for routing and low-confidence handling.
- [ ] Run backend compilation, a temporary PostgreSQL plan workflow check, and
  a frontend production build.
- [ ] Commit and push only feature files and this plan.
