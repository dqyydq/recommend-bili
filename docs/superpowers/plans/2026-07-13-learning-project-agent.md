# Learning Project Agent Implementation Plan

## Task 1: Project persistence

- [ ] Add PostgreSQL tables for projects, weekly tasks, immutable progress events, project-scoped conversations, and weekly review drafts.
- [ ] Add UID-scoped CRUD functions, draft-plan confirmation, task state transitions, review confirmation, and cascading project deletion.
- [ ] Return JSON task references as structured data and never expose a project owned by another user.

## Task 2: Bounded project Agent

- [ ] Build a project service that uses semantic search only to obtain an allow-list of saved favorites.
- [ ] Generate draft weekly tasks from that allow-list, with a deterministic fallback.
- [ ] Add project chat using a limited project summary, recent messages, active tasks, and retrieval results.
- [ ] Generate a metric-based weekly review with a draft next-week plan; confirmation creates active tasks.

## Task 3: API surface

- [ ] Add authenticated endpoints for project CRUD, draft generation/confirmation, task progress, chat, and weekly review.
- [ ] Require trusted origins for every mutation and an API key only for LLM-backed operations.
- [ ] Record project lifecycle and task changes in the operation log without storing sensitive message bodies there.

## Task 4: Project workspace

- [ ] Add a Learning Projects tab with project creation, current tasks, progress controls, compact chat, and review actions.
- [ ] Keep the existing one-off learning path available as a separate lightweight view.

## Task 5: Verification

- [ ] Add mocked Agent tests for allow-list task references and project-scoped chat.
- [ ] Run backend compilation, unit tests, temporary Postgres workflow verification, and a separate frontend production build.
- [ ] Commit only feature files and this plan.
