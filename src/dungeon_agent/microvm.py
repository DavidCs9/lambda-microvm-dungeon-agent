"""Shared primitives for authenticated Lambda MicroVM communication."""

from __future__ import annotations

import http.client
import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_lambda_microvms import LambdaMicroVMsClient


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: object
    latency_ms: float


def wait_for_state(
    client: LambdaMicroVMsClient,
    microvm_id: str,
    expected_state: str,
    *,
    timeout_seconds: int = 180,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = client.get_microvm(microvmIdentifier=microvm_id)
        state = response["state"]
        if state == expected_state:
            return
        if state in {"FAILED", "TERMINATED"} and state != expected_state:
            reason = response.get("stateReason", "No state reason returned")
            raise RuntimeError(f"MicroVM entered {state}: {reason}")
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for MicroVM {microvm_id} to reach {expected_state}")


def request_json(
    endpoint: str,
    token: str,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> HttpResult:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {
        "X-aws-proxy-auth": token,
        "X-aws-proxy-port": "8080",
        "Accept": "application/json",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"

    connection = http.client.HTTPSConnection(endpoint, timeout=15)
    started = time.perf_counter()
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        response_body = response.read()
    finally:
        connection.close()
    latency_ms = (time.perf_counter() - started) * 1_000
    if not response_body:
        decoded: object = None
    else:
        try:
            decoded = json.loads(response_body)
        except json.JSONDecodeError:
            decoded = response_body.decode(errors="replace")
    return HttpResult(status=response.status, body=decoded, latency_ms=latency_ms)


def require_success(result: HttpResult, operation: str) -> None:
    if not 200 <= result.status < 300:
        raise RuntimeError(f"{operation} returned HTTP {result.status}: {result.body}")
