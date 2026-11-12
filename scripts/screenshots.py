#!/usr/bin/env python3
"""Regenerate the dashboard screenshots in docs/screenshots/ from OFFLINE demo data.

    uv run python scripts/screenshots.py                 # seed, serve, capture
    uv run python scripts/screenshots.py --seed-only DIR # only create the demo data

Everything shown is produced by the scripted provider (no API key, no model
calls): the tour (scripts/tour.py), the starter benchmark, the step-budget
demo experiment and one run paused at the human approval gate. The pictures
show the pipeline and the dashboard, never model performance.

Capturing needs Node.js with Playwright and a Chromium it can launch
(`npm i -g playwright && npx playwright install chromium`); neither is a
project dependency. The API (:8000) and the dashboard dev server (:3000) are
started for the capture and stopped afterwards, so both ports must be free.

Exit status: 0 when every screenshot was written, 1 otherwise.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
API = "http://127.0.0.1:8000"
WEB = "http://localhost:3000"  # the API's default CORS origin
APPROVAL_AGENT = "approval-demo"
# `agentforge ...` with this interpreter (works without the console script on PATH).
CLI = [sys.executable, "-c", "import sys; from agentforge.cli import main; sys.exit(main())"]

# CLI steps that create the demo data, in order (paths relative to the repository).
SEED_COMMANDS: list[list[str]] = [
    [
        "bench",
        "run",
        "examples/benchmarks/starter.yaml",
        "-a",
        "examples/agents/scripted-demo.yaml",
        "--save-agent",
    ],
    ["experiment", "run", "examples/experiments/step-budget.yaml"],
]


def approval_run_request() -> dict[str, Any]:
    """A scripted run that pauses at the approval gate before writing a file."""
    return {
        "goal": "Add a release note for the next version to NOTES.md",
        "config": {
            "name": APPROVAL_AGENT,
            "description": "Offline demo: file writes wait for a human decision.",
            "model": {
                "provider": "scripted",
                "model": "scripted-v1",
                "options": {
                    "turns": [
                        {
                            "text": "I'll add the release note to NOTES.md.",
                            "tool_calls": [
                                {
                                    "name": "write_file",
                                    "arguments": {
                                        "path": "NOTES.md",
                                        "content": "## Next\n\n- Offline tour and docs index.\n",
                                    },
                                }
                            ],
                        },
                        {"text": "Added the release note to NOTES.md."},
                    ]
                },
            },
            "tools": ["filesystem"],
            "approval": {"require_for": ["fs:write"], "timeout_seconds": 3600},
            "limits": {"max_steps": 5, "timeout_seconds": 3600},
            "sandbox": {"kind": "local"},
        },
    }


def child_env(data_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("AGENTFORGE_DATABASE_URL", None)
    env.pop("AGENTFORGE_API_KEY", None)
    env["AGENTFORGE_DATA_DIR"] = str(data_dir)
    return env


def seed(data_dir: Path) -> None:
    """Create the demo data in ``data_dir`` with the documented offline commands."""
    data_dir.mkdir(parents=True, exist_ok=True)
    env = child_env(data_dir)
    commands = [[sys.executable, str(ROOT / "scripts" / "tour.py"), "--keep", str(data_dir)]]
    commands += [[*CLI, *argv] for argv in SEED_COMMANDS]
    for command in commands:
        done = subprocess.run(  # noqa: S603 - fixed commands
            command, cwd=ROOT, env=env, capture_output=True, text=True, check=False
        )
        if done.returncode != 0:
            raise RuntimeError(
                f"seed step failed ({done.returncode}): {' '.join(command)}\n"
                f"{done.stdout}{done.stderr}"
            )


def http_json(url: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    request = urllib.request.Request(url, data=data, headers=headers)  # noqa: S310 - localhost
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        return json.loads(response.read())


def dashboard_up() -> bool:
    with urllib.request.urlopen(WEB, timeout=5) as response:
        return bool(response.status == 200)


def wait_until(what: str, check: Any, timeout: float = 120.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with contextlib.suppress(urllib.error.URLError, ConnectionError, TimeoutError):
            result = check()
            if result:
                return result
        time.sleep(0.5)
    raise RuntimeError(f"timed out waiting for {what}")


@contextlib.contextmanager
def background(command: list[str], cwd: Path, env: dict[str, str], log: Path) -> Iterator[None]:
    with log.open("w") as handle:
        process = subprocess.Popen(  # noqa: S603 - fixed commands
            command,
            cwd=cwd,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            yield
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, 15)
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=10)


def start_approval_run() -> str:
    """Start the approval demo run and wait until it is paused at the gate."""
    run_id: str = http_json(f"{API}/api/v1/runs", approval_run_request())["id"]
    wait_until(
        "the run to await approval",
        lambda: http_json(f"{API}/api/v1/runs/{run_id}")["status"] == "awaiting_approval",
        timeout=30,
    )
    return run_id


def capture(data_dir: Path, out_dir: Path) -> int:
    node, npm = shutil.which("node"), shutil.which("npm")
    if node is None or npm is None:
        raise RuntimeError("node and npm are required to capture screenshots")
    if not (ROOT / "web" / "node_modules").is_dir():
        raise RuntimeError("install the dashboard first: cd web && npm ci")
    env = child_env(data_dir)
    serve = [*CLI, "serve", "--port", "8000"]
    with contextlib.ExitStack() as stack:
        stack.enter_context(background(serve, ROOT, env, data_dir / "api.log"))
        wait_until("the API", lambda: http_json(f"{API}/api/v1/health")["status"] == "ok")
        run_id = start_approval_run()
        web_env = {**env, "NEXT_PUBLIC_API_URL": API}
        stack.enter_context(
            background([npm, "run", "dev"], ROOT / "web", web_env, data_dir / "web.log")
        )
        wait_until("the dashboard", dashboard_up)
        shots = subprocess.run(  # noqa: S603
            [node, str(ROOT / "scripts" / "screenshots.cjs"), str(out_dir)],
            cwd=ROOT,
            env={**env, "AF_API": API, "AF_WEB": WEB, "AF_APPROVAL_RUN": run_id},
            check=False,
        )
        with contextlib.suppress(urllib.error.URLError):
            http_json(f"{API}/api/v1/runs/{run_id}/cancel", {})
        return shots.returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seed-only", metavar="DIR", help="create the demo data in DIR and stop")
    parser.add_argument("--out", default=str(OUT), help="output directory (default: %(default)s)")
    args = parser.parse_args(argv)
    try:
        if args.seed_only:
            seed(Path(args.seed_only).resolve())
            print(f"demo data (OFFLINE) written to {args.seed_only}")
            return 0
        with tempfile.TemporaryDirectory(prefix="af-shots-") as tmp:
            seed(Path(tmp))
            return capture(Path(tmp), Path(args.out).resolve())
    except RuntimeError as exc:
        print(f"screenshots failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
