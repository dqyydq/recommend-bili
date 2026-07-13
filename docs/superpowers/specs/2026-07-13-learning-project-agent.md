# Learning Project Agent Design

## Product Goal

Help a user turn their saved Bilibili content into a sustained learning habit.
A learning project is the private, persistent container for one goal. It joins
semantic retrieval, a practical weekly plan, progress signals, focused
conversation, and a weekly review.

## User Journey

1. The user creates a project with a goal, target duration in weeks, and weekly
   available minutes.
2. The Agent retrieves relevant saved videos and proposes a first weekly plan
   with three to five concrete tasks. Each task cites one or more saved videos.
3. The user marks a task complete, skipped, or blocked and can add a short note.
4. Within the project, the user asks contextual questions such as "what did I
   get stuck on?" or "make this week lighter". The Agent uses only that
  project's summary, recent dialogue, plan, and retrieved favorites.
5. At the start of a new week, or on request, the Agent provides a review:
   completion rate, obstacles, useful content, and a proposed next-week plan.
   The user explicitly confirms the next-week plan before it becomes active.

## Data Boundaries

PostgreSQL is the source of truth for:

- `learning_projects`: goal, duration, weekly time budget, lifecycle, current
  week, and project-level summary.
- `learning_tasks`: project week, title, rationale, linked favorite IDs,
  estimated time, state, and user note.
- `learning_progress_events`: immutable task-state changes and notes for a
  defensible review history.
- `learning_conversations`: user and assistant messages scoped to one project.
- `learning_weekly_reviews`: calculated metrics, assistant review, and the
  proposed/confirmed next-week plan.

Chroma remains a per-user retrieval index only. It does not store task state,
chat history, or user feedback. Project messages are never supplied to another
project. Project deletion cascades through its conversations, plans, and events.

## Agent Design

The backend exposes separate bounded functions rather than a free-form agent
with database access:

- Plan builder: semantic-searches the user's favorites, then asks the LLM for
  structured tasks using only retrieved IDs from an allow-list. A deterministic
  fallback creates a compact plan when LLM generation fails.
- Project chat: loads the current project summary, recent messages, task state,
  and up to eight search results; it returns a concise response and an updated
  project summary. It cannot execute Bilibili actions.
- Review builder: derives completion and blockage metrics from progress events,
  asks the LLM for reflection and next-week suggestions, and stores the result
  as a draft. Confirmation creates the next week's tasks.

Sensitive user notes and conversations are sent to the configured LLM only
when the user asks the Agent to generate a plan, chat response, or review. API
keys remain outside PostgreSQL as in the current application.

## API And UI

- Create/list/get/archive/delete learning projects.
- Generate a week plan; confirm it before making its tasks active.
- Update a task state and optional note.
- Send a project-scoped chat message and return the persisted response.
- Generate and confirm a weekly review.

The Agent tab gains a "Learning Projects" view: project list, project detail,
current tasks, compact conversation surface, and a review panel. The existing
one-off learning-path generator remains available during migration but links
users toward a project when they want to track progress.

## Safety And Reliability

- Every write is owned by the session UID; IDs supplied by the frontend are
  always joined against that UID.
- Task and plan creation is draft-first; confirmation is explicit and
  idempotent.
- LLM output is parsed as bounded JSON and can only reference favorites returned
  by retrieval. Invalid output falls back to deterministic tasks.
- The Agent never alters a Bilibili favorite from this feature.
- Deletion requires explicit user action and deletes all project-scoped history.

## Verification

- Database tests cover ownership, cascading deletion, task transitions, draft
  confirmation, and review lifecycle.
- Agent tests mock Chroma/LLM responses and verify that unknown favorite IDs
  cannot be attached to tasks.
- API tests cover cross-project and cross-user access rejection.
- A production frontend build verifies project, progress, chat, and review
  states.

## First Release Boundaries

No background reminders, notification service, calendar integration, or
cross-platform content import. A review is user-triggered, and a project has a
single active weekly plan at a time.
