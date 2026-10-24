import io
import http.client
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

    def test_malformed_api_key_is_rejected_without_exposing_its_value(self):
        for key in ("DUMMY_SECRET\n", "DUMMY_SECRET\r", "DUMMY_SECRET ü", "DUMMY_SECRET\t"):
            with self.subTest(key=key), patch("urllib.request.build_opener") as opener:
                with self.assertRaises(ValueError) as caught:
                    ChatCompletionsPlanner("http://127.0.0.1:1/v1", "model", api_key=key, allow_network=True)
                self.assertNotIn("DUMMY_SECRET", str(caught.exception))
                opener.assert_not_called()
        planner = ChatCompletionsPlanner("http://127.0.0.1:1/v1", "model", allow_network=True)
        planner.api_key = "DUMMY_SECRET\n"
        with self.assertRaises(ValueError) as caught:
            planner.next_action([], [])
        self.assertNotIn("DUMMY_SECRET", str(caught.exception))

    def test_transport_encoding_errors_are_sanitized(self):
        errors = [ValueError("Invalid header value DUMMY_SECRET"),
                  UnicodeEncodeError("ascii", "DUMMY_SECRET ü", 13, 14, "encoding failed"),
                  http.client.InvalidURL("DUMMY_SECRET")]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                opener = Mock()
                opener.open.side_effect = error
                planner = ChatCompletionsPlanner("https://example.test/v1", "model", allow_network=True)
                with patch("urllib.request.build_opener", return_value=opener), self.assertRaises(PlannerError) as caught:
                    planner.next_action([], [])
                self.assertNotIn("DUMMY_SECRET", str(caught.exception))

    def test_response_limit_requires_a_positive_integer(self):
        for limit in (-2, -1, 0, True, False, 1.5, None):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                ChatCompletionsPlanner("https://example.test/v1", "model", max_response_bytes=limit)

    def test_timeout_requires_a_bounded_real_number(self):
        for timeout in (True, False, None, "30", 0, -1, 61, float("inf"), float("nan"), 10**1000):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                ChatCompletionsPlanner("https://example.test/v1", "model", timeout=timeout)

    def test_model_name_requires_text(self):
        for model in (None, 123, [], "", "x" * 201):
            with self.subTest(model=model), self.assertRaises(ValueError):
                ChatCompletionsPlanner("https://example.test/v1", model)

    def test_deeply_nested_response_is_a_protocol_error(self):
        # The body is below the byte limit but exceeds the JSON parser's depth.
        raw = b"[" * 20_000 + b"0" + b"]" * 20_000
        opener = Mock()
        opener.open.return_value = io.BytesIO(raw)
        planner = ChatCompletionsPlanner("https://example.test/v1", "model", allow_network=True)
        with patch("urllib.request.build_opener", return_value=opener), self.assertRaises(PlannerError):
            planner.next_action([], [])


if __name__ == "__main__":
    unittest.main()
