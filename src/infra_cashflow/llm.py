"""Optional Chat Completions-compatible planner; all financial math stays local.

This adapter is deliberately provider-neutral. It is opt-in and supports a local
model endpoint. API keys are supplied in memory from an environment variable;
neither prompts nor keys are persisted. The adapter is tested against a mocked
HTTP transport, not against a live commercial model.
"""

from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


class PlannerError(RuntimeError):
    """A provider or protocol failure, without leaking credentials or payloads."""


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PlannerError("The model endpoint attempted a redirect; redirects are disabled.")


def validate_endpoint(base_url: str) -> str:
    """Allow HTTPS or plain HTTP on loopback, without embedded credentials."""
    p = urlparse(base_url)
    if not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError("Model base URL must be an origin/path without credentials, query or fragment.")
    is_local = p.hostname.lower() == "localhost"
    try:
        is_local = is_local or ipaddress.ip_address(p.hostname).is_loopback
    except ValueError:
        pass
    if p.scheme != "https" and not (p.scheme == "http" and is_local):
        raise ValueError("Model endpoint requires HTTPS, except for explicit loopback endpoints.")
    return base_url.rstrip("/") + "/chat/completions"


@dataclass
class ChatCompletionsPlanner:
    """Minimal client; constructing it never performs network I/O."""

    base_url: str
    model: str
    api_key: str = field(default="", repr=False)
    allow_network: bool = False
    timeout: float = 30.0
    max_response_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        self.endpoint = validate_endpoint(self.base_url)
        if not self.model or len(self.model) > 200:
            raise ValueError("An explicit model name of at most 200 characters is required.")
        if not 0 < self.timeout <= 60:
            raise ValueError("Model timeout must be in (0, 60] seconds.")

    def next_action(self, messages: list[dict], tools: list[dict]) -> dict[str, Any]:
        if not self.allow_network:
            raise PlannerError("Network access requires the explicit --allow-network option.")
        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "required",
            "parallel_tool_calls": False,
            "stream": False,
        }, ensure_ascii=False, allow_nan=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        request = urllib.request.Request(self.endpoint, data=payload, headers=headers, method="POST")
        opener = urllib.request.build_opener(_NoRedirects())
        try:
            with opener.open(request, timeout=self.timeout) as response:
                raw = response.read(self.max_response_bytes + 1)
        except PlannerError:
            raise
        except urllib.error.HTTPError as exc:
            raise PlannerError(f"Model endpoint returned HTTP {exc.code}.") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise PlannerError("Model endpoint could not be reached within the configured timeout.") from None
        if len(raw) > self.max_response_bytes:
            raise PlannerError("Model response exceeded the response size limit.")
        try:
            body = json.loads(raw, parse_constant=lambda value: _reject_constant(value))
            choices = body["choices"]
            message = choices[0]["message"]
            if not isinstance(message, dict):
                raise ValueError("message must be object")
        except (ValueError, KeyError, IndexError, TypeError):
            raise PlannerError("Model endpoint returned an invalid Chat Completions response.") from None
        return message


def _reject_constant(value: str):
    raise ValueError(f"Non-finite JSON constant: {value}")

