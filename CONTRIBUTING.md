# Contributing

## Setup

Use Python 3.11 and uv:

```powershell
uv venv --python 3.11
.venv\Scripts\activate
uv pip install -r backend\requirements.txt
```

Use Node.js 18 for the frontend. Copy `.env.example` to `.env`; never commit `.env`, cookies, API keys, local Chroma data or PostgreSQL volumes.

## Change rules

- Keep PostgreSQL as the business source and Chroma rebuildable.
- Scope all user-owned reads and writes by `uid`.
- Preserve trusted-origin checks for write endpoints.
- Never treat timeouts, rate limits or region restrictions as confirmed invalid videos.
- Never transition inferred interests to `dormant` without explicit user confirmation.
- New external mutations require a second confirmation and a server-side recheck.
- Do not load untrusted dynamic Skill code.

## Verification

```powershell
.venv\Scripts\activate
python -m unittest discover -s backend -p "test_*.py"
Set-Location frontend
npm test
npm run build
```

Keep commits scoped to one delivery stage and include tests for behavior or security changes.
