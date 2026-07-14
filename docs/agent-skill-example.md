# Agent Skill Example

Favorite Agent keeps Skills explicit and locally reviewed. It does not scan directories and execute arbitrary third-party Python modules.

```python
from harness import AgentSkill

skill = AgentSkill(
    name="retrieve_favorites",
    description="Search the authenticated user's local favorite snapshot",
    risk="read",
)
```

Risk levels:

- `read`: reads local data and may run automatically.
- `draft`: creates a local plan or suggestion and may run automatically.
- `mutate`: changes an external system and requires explicit confirmation.

A new Skill should define a bounded Pydantic input model, a JSON-compatible output contract, user isolation tests, error behavior and risk level. `mutate` Skills must be registered behind the Harness Guardrail and revalidate server-side targets before execution.
