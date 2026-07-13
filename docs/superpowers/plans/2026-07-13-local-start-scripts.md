# Local Start Scripts Implementation Plan

## Task 1: Add `scripts/start.ps1`

- [ ] Resolve the repository root and create ignored runtime/log directories.
- [ ] Check prerequisites and fail clearly on occupied ports 8000/3000.
- [ ] Start the project Compose PostgreSQL service, wait for readiness, then
  launch uv-activated FastAPI and Vite as hidden child processes.
- [ ] Wait for backend/frontend HTTP readiness and persist only child PIDs.

## Task 2: Add `scripts/stop.ps1`

- [ ] Read recorded PIDs, stop only live child processes, and remove stale PID
  files.
- [ ] Run `docker compose down` without removing volumes.

## Task 3: Verify and commit

- [ ] Validate both scripts with the PowerShell parser.
- [ ] Exercise start and stop from a free-port state, checking health endpoints
  and released ports.
- [ ] Commit and push only scripts and this implementation plan.
