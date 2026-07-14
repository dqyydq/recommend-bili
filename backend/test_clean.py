import unittest

import httpx

from clean import inspect_bvid


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class FakeClient:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response

    async def get(self, *args, **kwargs) -> FakeResponse:
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class CleanupVerdictTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_not_found_is_confirmed_invalid(self) -> None:
        verdict, _ = await inspect_bvid("BV1", FakeClient(FakeResponse(200, {"code": -404, "message": "啥都木有"})))
        self.assertEqual(verdict, "confirmed_invalid")

    async def test_access_restriction_requires_review(self) -> None:
        verdict, _ = await inspect_bvid("BV1", FakeClient(FakeResponse(200, {"code": -403, "message": "权限不足"})))
        self.assertEqual(verdict, "review_required")

    async def test_rate_limit_and_timeout_are_unknown(self) -> None:
        limited, _ = await inspect_bvid("BV1", FakeClient(FakeResponse(429, {})))
        timeout, _ = await inspect_bvid("BV1", FakeClient(httpx.ReadTimeout("timeout")))
        self.assertEqual(limited, "unknown")
        self.assertEqual(timeout, "unknown")

    async def test_available_video_is_not_selected_for_cleanup(self) -> None:
        verdict, _ = await inspect_bvid("BV1", FakeClient(FakeResponse(200, {"code": 0})))
        self.assertEqual(verdict, "available")


if __name__ == "__main__":
    unittest.main()
