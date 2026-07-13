# Local Start Scripts Design

## Goal

Provide a one-command local startup path for the project without making global
machine changes. The scripts operate only inside this repository and only on
processes they start themselves.

## Start Script

`scripts/start.ps1` will:

1. Resolve the repository root relative to the script location.
2. Check that Docker, Node/npm, and `.venv` exist; it will not install or
   upgrade anything.
3. Refuse to start when ports 8000 or 3000 are already occupied. It never kills
   the existing process because it may belong to another project.
4. Start only this repository's Compose PostgreSQL service and wait for it to
   become ready.
5. Launch the backend in a hidden child PowerShell with process-scoped `PORT`
   and `CORS_ORIGINS` values, after activating the uv virtual environment.
6. Wait for the backend health endpoint, then launch Vite in a hidden child
   PowerShell with a process-scoped API proxy target.
7. Persist only child process IDs under ignored `data/runtime/` and write logs
   under ignored `data/logs/`.
8. Print the local browser URL and log locations.

## Stop Script

`scripts/stop.ps1` reads only process IDs recorded by `start.ps1`, stops those
processes if they still exist, then runs `docker compose down`. It preserves the
PostgreSQL volume and all local user data. It does not inspect or stop unrelated
Docker containers.

## Safety

- No registry, PATH, execution-policy, service, firewall, or global environment
  setting is changed.
- Environment variables are set only inside backend/frontend child processes.
- Existing port listeners fail fast with a human-readable message.
- The scripts do not touch `.env`; it remains the user's configuration source.

## Verification

- PowerShell parser validation for both scripts.
- Start from a free-port state and verify PostgreSQL, backend `/docs`, frontend
  `/`, and frontend `/api/me`.
- Run the stop script and verify ports 8000/3000 are released while the Docker
  volume remains available for the next startup.
