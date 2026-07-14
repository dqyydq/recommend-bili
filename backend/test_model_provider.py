import unittest

from model_provider import OpenAICompatibleProvider, create_model_provider


class ModelProviderTests(unittest.TestCase):
    def test_accepts_https_and_local_http_compatible_endpoints(self) -> None:
        remote = create_model_provider("key", "model", "https://models.example.com/v1")
        local = create_model_provider("key", "model", "http://localhost:9000/v1")
        self.assertIsInstance(remote, OpenAICompatibleProvider)
        self.assertIsInstance(local, OpenAICompatibleProvider)

    def test_rejects_insecure_remote_endpoint(self) -> None:
        with self.assertRaisesRegex(ValueError, "必须使用 HTTPS"):
            create_model_provider("key", "model", "http://models.example.com/v1")
        with self.assertRaises(ValueError):
            create_model_provider("key", "model", "http://127.0.0.1.evil.example/v1")

    def test_rejects_endpoint_credentials(self) -> None:
        with self.assertRaisesRegex(ValueError, "不能包含凭据"):
            create_model_provider("key", "model", "https://user:pass@models.example.com/v1")


if __name__ == "__main__":
    unittest.main()
