import io
import json
import unittest
import urllib.error
from unittest.mock import Mock, patch

from infra_cashflow.llm import ChatCompletionsPlanner, PlannerError, validate_endpoint


class TestPlannerTransport(unittest.TestCase):
    def test_explicit_network_opt_in(self):
        planner = ChatCompletionsPlanner("https://example.test/v1", "test-model")
        with patch("urllib.request.build_opener") as opener:
            with self.assertRaises(PlannerError):
                planner.next_action([], [])
            opener.assert_not_called()

    def test_endpoint_contract(self):
        self.assertEqual(validate_endpoint("http://127.0.0.1:8000/v1/"), "http://127.0.0.1:8000/v1/chat/completions")
        self.assertEqual(validate_endpoint("http://[::1]:8000/v1"), "http://[::1]:8000/v1/chat/completions")
        for endpoint in ("http://external.test/v1", "https://key:secret@example.test/v1", "file:///etc/passwd", "https://example.test/v1?key=abc"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                validate_endpoint(endpoint)

    def test_mocked_valid_response(self):
        call = {"id": "one", "type": "function", "function": {"name": "finalize", "arguments": "{}"}}
        response = {"choices": [{"message": {"role": "assistant", "tool_calls": [call]}}]}
        opener = Mock()
        opener.open.return_value = io.BytesIO(json.dumps(response).encode())
        planner = ChatCompletionsPlanner("https://example.test/v1", "test-model", "not-a-real-key", True)
        with patch("urllib.request.build_opener", return_value=opener):
            result = planner.next_action([{"role": "user", "content": "test"}], [])
        self.assertEqual(result["tool_calls"], [call])
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.test/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer not-a-real-key")
        body = json.loads(request.data)
        self.assertEqual(body["tool_choice"], "required")
        self.assertFalse(body["parallel_tool_calls"])

    def test_malformed_nonfinite_or_oversized_response_rejected(self):
        for raw in (b'{"choices":[]}', b'{"x":NaN}', b'not-json', b'x' * 101):
            with self.subTest(raw=raw):
                opener = Mock()
                opener.open.return_value = io.BytesIO(raw)
                planner = ChatCompletionsPlanner("https://example.test/v1", "model", allow_network=True, max_response_bytes=100)
                with patch("urllib.request.build_opener", return_value=opener), self.assertRaises(PlannerError):
                    planner.next_action([], [])

    def test_http_error_does_not_echo_provider_body(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError("https://example.test/v1", 401, "secret-body", {}, None)
        planner = ChatCompletionsPlanner("https://example.test/v1", "model", allow_network=True)
        with patch("urllib.request.build_opener", return_value=opener), self.assertRaises(PlannerError) as caught:
            planner.next_action([], [])
        self.assertEqual(str(caught.exception), "Model endpoint returned HTTP 401.")


if __name__ == "__main__":
    unittest.main()
