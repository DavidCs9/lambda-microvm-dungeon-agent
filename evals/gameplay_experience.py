"""Original black-box evaluation for deterministic gameplay quality."""

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from itertools import pairwise
from pathlib import Path


@dataclass(frozen=True)
class Journey:
    name: str
    actions: tuple[str, ...]


@dataclass(frozen=True)
class JourneyEvidence:
    name: str
    actions: tuple[str, ...]
    states: tuple[dict[str, object], ...]


JOURNEYS = (
    Journey(
        "independent_escape",
        ("look around", "enter the cellar", "take the brass key", "return to tavern", "open door"),
    ),
    Journey(
        "help_mira",
        ("talk to Mira", "enter the cellar", "inspect the machine", "use the tuning fork"),
    ),
    Journey("ignore_the_warning", tuple(f"wait and do nothing {turn}" for turn in range(1, 10))),
)

REQUIRED_WORLD_FIELDS = {
    "health",
    "danger",
    "objective",
    "discovered_clues",
    "npc_relationships",
    "completed_events",
    "status",
    "last_result",
}


def evaluate(project_root: Path) -> dict[str, object]:
    evidence = tuple(_run_journey(project_root, journey) for journey in JOURNEYS)
    return _score(evidence)


def evaluate_microvm(
    profile: str,
    region: str,
    image_arn: str,
    image_version: str,
) -> dict[str, object]:
    from dungeon_agent.cli import create_clients
    from dungeon_agent.orchestrator.session import MicrovmSession

    microvms, _ = create_clients(profile, region)
    collected: list[JourneyEvidence] = []
    for journey in JOURNEYS:
        with MicrovmSession(microvms, image_arn, image_version) as session:
            states: list[dict[str, object]] = []
            for action in journey.actions:
                state = session.apply_action(action)
                states.append(state)
                if state.get("status") in {"won", "lost"}:
                    break
        collected.append(JourneyEvidence(journey.name, journey.actions, tuple(states)))
    return _score(tuple(collected))


def _score(evidence: tuple[JourneyEvidence, ...]) -> dict[str, object]:
    dimensions = {
        "player_agency": _agency_score(evidence),
        "guidance_and_information": _guidance_score(evidence),
        "danger_and_challenge": _challenge_score(evidence),
        "state_consistency": _consistency_score(evidence),
        "world_depth": _world_depth_score(evidence),
    }
    return {
        "rubricVersion": "1.0",
        "evaluationGoals": [
            "support meaningfully different player strategies",
            "communicate goals and consequences clearly",
            "create fair urgency and reachable failure",
            "preserve consistent state across turns",
            "provide enough structured world state for grounded narration",
        ],
        "score": sum(dimensions.values()),
        "maximumScore": 100,
        "dimensions": dimensions,
        "journeys": [asdict(item) for item in evidence],
    }


def _run_journey(project_root: Path, journey: Journey) -> JourneyEvidence:
    port = _available_port()
    target, python_path = _application_target(project_root)
    with tempfile.TemporaryDirectory(prefix="dungeon-eval-") as workspace:
        environment = os.environ.copy()
        environment["DUNGEON_WORKSPACE_DIR"] = workspace
        environment["PYTHONPATH"] = python_path
        command = [
            sys.executable,
            "-m",
            "uvicorn",
            target,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ]
        process = subprocess.Popen(
            command,
            cwd=project_root,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            _wait_until_ready(process, port)
            collected: list[dict[str, object]] = []
            for action in journey.actions:
                state = _post_action(port, action)
                collected.append(state)
                if state.get("status") in {"won", "lost"}:
                    break
            states = tuple(collected)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    return JourneyEvidence(journey.name, journey.actions, states)


def _application_target(project_root: Path) -> tuple[str, str]:
    source = project_root / "src"
    if source.is_dir():
        return "dungeon_agent.api.main:app", str(source)
    return "app.main:app", str(project_root)


def _available_port() -> int:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _wait_until_ready(process: subprocess.Popen[str], port: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            detail = process.stderr.read() if process.stderr is not None else ""
            raise RuntimeError(f"Evaluation server stopped unexpectedly: {detail}")
        try:
            _request(port, "GET", "/health")
            return
        except OSError, urllib.error.URLError:
            time.sleep(0.05)
    raise TimeoutError("Evaluation server did not become ready")


def _post_action(port: int, action: str) -> dict[str, object]:
    response = _request(port, "POST", "/v1/actions", {"action": action})
    if not isinstance(response, dict):
        raise TypeError("Action endpoint returned a non-object response")
    return response


def _request(
    port: int,
    method: str,
    path: str,
    payload: dict[str, str] | None = None,
) -> object:
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        return json.loads(response.read())


def _agency_score(evidence: tuple[JourneyEvidence, ...]) -> int:
    endings = {
        str(state.get("ending"))
        for journey in evidence
        for state in journey.states
        if state.get("status") == "won" and state.get("ending")
    }
    return 20 if len(endings) >= 2 else 10 if endings else 0


def _guidance_score(evidence: tuple[JourneyEvidence, ...]) -> int:
    states = [state for journey in evidence for state in journey.states]
    guided = sum(
        bool(state.get("objective"))
        and isinstance(state.get("last_result"), dict)
        and bool(state["last_result"].get("consequence"))
        and bool(state["last_result"].get("suggestions"))
        for state in states
    )
    return round(20 * guided / len(states)) if states else 0


def _challenge_score(evidence: tuple[JourneyEvidence, ...]) -> int:
    danger_changes = any(
        len({state.get("danger") for state in journey.states}) > 1 for journey in evidence
    )
    loss_reachable = any(
        state.get("status") == "lost" for journey in evidence for state in journey.states
    )
    return (10 if danger_changes else 0) + (10 if loss_reachable else 0)


def _consistency_score(evidence: tuple[JourneyEvidence, ...]) -> int:
    checks = 0
    passed = 0
    for journey in evidence:
        for index, state in enumerate(journey.states, start=1):
            checks += 1
            passed += state.get("revision") == index
        inventories = [state.get("inventory") for state in journey.states]
        for before, after in pairwise(inventories):
            if isinstance(before, list) and isinstance(after, list):
                checks += 1
                passed += set(before).issubset(after)
    return round(20 * passed / checks) if checks else 0


def _world_depth_score(evidence: tuple[JourneyEvidence, ...]) -> int:
    states = [state for journey in evidence for state in journey.states]
    if not states:
        return 0
    coverage = sum(len(REQUIRED_WORLD_FIELDS.intersection(state)) for state in states)
    return round(20 * coverage / (len(states) * len(REQUIRED_WORLD_FIELDS)))


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate deterministic gameplay quality.")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--profile", default="personal")
    parser.add_argument("--region", default="us-east-2")
    parser.add_argument("--image-arn")
    parser.add_argument("--image-version")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    if bool(args.image_arn) != bool(args.image_version):
        raise SystemExit("--image-arn and --image-version must be provided together")
    report = (
        evaluate_microvm(args.profile, args.region, args.image_arn, args.image_version)
        if args.image_arn is not None and args.image_version is not None
        else evaluate(args.project_root.resolve())
    )
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
