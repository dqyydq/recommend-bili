# Agent Workspace Redesign

## Product Goal

Replace the current feature-menu experience with a task-oriented workspace.
Users should enter with a goal, see what the Agent is doing, understand what
needs confirmation, and reach their collection without guessing which tool to
open.

## Navigation

The primary navigation contains four destinations:

- `工作台`: Agent command, active work, collection insights, and contextual
  status.
- `收藏库`: browse, search, filter, and inspect saved videos.
- `学习项目`: persistent plans, progress, project chat, and weekly reviews.
- `操作记录`: synchronization, reviewed blueprints, execution outcomes, and
  failures.

Classification, semantic retrieval, dust detection, and organization plans are
internal capabilities or contextual views. They are no longer equal-level
navigation entries.

## Workspace Layout

The workspace uses a responsive two-column grid. The main column is wider and
contains:

1. A compact Agent command surface with suggested intents.
2. Current work: sync progress, active learning tasks, draft structure
   blueprints, and pending confirmations.
3. Collection insights: recent additions, duplicate/invalid risk, unreviewed
   topics, and useful content resurfacing.

The context column contains today's recommendation, project progress, pending
confirmations, and a direct collection-library entry. On narrow screens it
moves below the main column without changing reading order.

## Agent Command Behavior

The first release uses explicit, reliable intent routing rather than autonomous
tool execution. A command is classified into one of these bounded actions:

- Search saved content.
- Create or continue a learning project.
- Generate a folder-structure blueprint.
- Inspect collection health or synchronization state.

The response always includes a conclusion, supporting saved-content evidence,
and a clear next action. Any mutation remains draft-first and requires existing
confirmation flows.

## Existing Feature Mapping

- `整理收藏夹` is removed as a label.
- Folder classification becomes an analysis tool inside the collection library.
- `结构蓝图` owns proposed purpose/topic organization.
- `待确认操作` surfaces reviewed blueprints and executable safe plans.
- Existing search, learning-project, organization-plan, profile, and dashboard
  APIs are reused where their contracts fit.

## Visual Direction

This is a quiet operational product, not a marketing page. Use a cool neutral
palette with one restrained Bilibili-pink accent, compact typography, clear
dividers, and unframed page sections. Avoid nested cards, large decorative
heroes, gradients, and equal-sized feature-card grids. Use stable grid tracks,
visible keyboard focus, tabular figures for counts, and clear loading, empty,
error, and pending states.

## Component Boundaries

- `workspace-module.js`: orchestration and the four workspace regions.
- `collection-library.js`: saved-content browsing and contextual analysis.
- Existing learning and structure components remain responsible for their own
  detailed workflows.
- `console-page.js` owns only global navigation, user/sync status, and route
  selection.

No frontend framework or UI library is introduced. The implementation stays in
the current Vite and vanilla JavaScript stack.

## Verification

- Route and state tests verify that each command maps to a bounded capability.
- Existing feature APIs remain reachable through the new navigation.
- Production build and browser checks cover desktop and mobile widths, loading,
  empty, error, and authenticated workspace states.
- No Bilibili mutation is added by this redesign.
