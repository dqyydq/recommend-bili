import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

import organization_executor


class _Response:
    status_code = 200

    @staticmethod
    def json() -> dict:
        return {"code": 0}


class _Client:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    async def post(self, url: str, data: dict, timeout: int) -> _Response:
        self.requests.append({"url": url, "data": data, "timeout": timeout})
        return _Response()


class OrganizationExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_invalid_resources_are_deleted(self) -> None:
        actions = [
            {"id": "valid", "folder_id": 10, "media_id": 101, "bvid": "BV-valid", "title": "valid"},
            {"id": "invalid", "folder_id": 10, "media_id": 102, "bvid": "BV-invalid", "title": "invalid"},
            {"id": "unknown", "folder_id": 11, "media_id": 103, "bvid": "BV-unknown", "title": "unknown"},
        ]
        outcomes: dict[str, tuple[str, str]] = {}
        finished: list[str] = []
        client = _Client()

        async def claim(uid: str, plan_id: str) -> bool:
            return True

        async def get_actions(uid: str, plan_id: str) -> list[dict]:
            return actions

        async def set_outcome(uid: str, plan_id: str, action_id: str, state: str, message: str) -> None:
            outcomes[action_id] = (state, message)

        async def finish(uid: str, plan_id: str, status: str) -> None:
            finished.append(status)

        async def get_plan(uid: str, plan_id: str) -> dict:
            return {"id": plan_id, "execution_status": finished[-1] if finished else "running"}

        @asynccontextmanager
        async def fake_client(cookies: dict):
            yield client

        async def check_bvid(bvid: str, _client: _Client) -> str:
            return {"BV-valid": "valid", "BV-invalid": "invalid", "BV-unknown": "unknown"}[bvid]

        with (
            patch.object(organization_executor, "claim_organization_plan_execution", claim),
            patch.object(organization_executor, "get_executable_plan_actions", get_actions),
            patch.object(organization_executor, "set_plan_action_execution_result", set_outcome),
            patch.object(organization_executor, "finish_organization_plan_execution", finish),
            patch.object(organization_executor, "get_organization_plan", get_plan),
            patch.object(organization_executor, "_client", fake_client),
            patch.object(organization_executor, "_check_bvid", check_bvid),
        ):
            result = await organization_executor.execute_organization_plan(
                "user", "plan", {"bili_jct": "csrf"},
            )

        self.assertTrue(result["claimed"])
        self.assertEqual(result["counts"], {"deleted": 1, "skipped_valid": 1, "skipped_unreachable": 1, "failed": 0})
        self.assertEqual(outcomes["valid"][0], "skipped_valid")
        self.assertEqual(outcomes["invalid"][0], "deleted")
        self.assertEqual(outcomes["unknown"][0], "skipped_unreachable")
        self.assertEqual(finished, ["partial_failed"])
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(client.requests[0]["data"]["media_id"], 10)
        self.assertEqual(client.requests[0]["data"]["resources"], "102:2")

    async def test_unclaimed_plan_does_not_contact_bilibili(self) -> None:
        async def claim(uid: str, plan_id: str) -> bool:
            return False

        async def get_plan(uid: str, plan_id: str) -> dict:
            return {"id": plan_id, "execution_status": "running"}

        with (
            patch.object(organization_executor, "claim_organization_plan_execution", claim),
            patch.object(organization_executor, "get_organization_plan", get_plan),
        ):
            result = await organization_executor.execute_organization_plan(
                "user", "plan", {"bili_jct": "csrf"},
            )

        self.assertFalse(result["claimed"])
        self.assertEqual(result["counts"], {})


if __name__ == "__main__":
    unittest.main()
