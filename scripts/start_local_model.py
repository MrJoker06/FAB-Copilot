"""Start the local llama.cpp server used by Fab Insight Agent on Windows or Linux.

One launcher for both platforms: it resolves the deployment workspace, picks the
platform's ``llama-server`` binary, applies the context/parallel profile that
fits an A10 (23 GB), starts the server with logs under ``runtime/local-model``
and waits until ``/v1/models`` answers.

Defaults match the hybrid-attention layout of qwen35 (65 blocks,
full_attention_interval=4, 4 KV heads, key/value length 256): only ~17 layers
hold KV, so 81920 tokens with q8_0 KV cache costs roughly 2.8 GB on top of the
15.66 GB Q4_K_M weights.

Examples::

    python scripts/start_local_model.py
    python scripts/start_local_model.py --model ridge --profile 32k --port 8081
    python scripts/start_local_model.py --vision --alias deepseek-v4-flash
    python scripts/start_local_model.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
POLL_SECONDS = 2.0
PROBE_TIMEOUT_SECONDS = 3.0


class LauncherError(RuntimeError):
    """A launch precondition or readiness check failed."""


@dataclass(frozen=True)
class ModelSpec:
    file: Path
    mmproj: Path
    default_alias: str


@dataclass(frozen=True)
class ProfileSpec:
    ctx: int
    parallel: int


MODELS: dict[str, ModelSpec] = {
    "q4km": ModelSpec(
        Path("Qwen3.8-27B-Q4_K_M-GGUF", "Qwen3.8-27B-Q4_K_M.gguf"),
        Path("Qwen3.8-27B-Q4_K_M-GGUF", "mmproj-F16.gguf"),
        "Qwen3.8-27B-Q4_K_M",
    ),
    "ridge": ModelSpec(
        Path("Qwen3.8-27B-Ridge-3.7bpw", "Qwen3.8-27B-Ridge-3.7bpw.gguf"),
        Path("Qwen3.8-27B-Ridge-3.7bpw", "mmproj-Qwen3.8-27B-BF16.gguf"),
        "Qwen3.8-27B-Ridge-3.7bpw",
    ),
}

PROFILES: dict[str, ProfileSpec] = {
    "32k": ProfileSpec(ctx=32768, parallel=1),
    "80k": ProfileSpec(ctx=81920, parallel=2),
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the local llama.cpp server for Fab Insight Agent."
    )
    parser.add_argument("--model", choices=sorted(MODELS), default="q4km")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="80k")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="127.0.0.1", help="bind address")
    parser.add_argument(
        "--vision",
        action="store_true",
        help="also load the multimodal projector (needed for image input)",
    )
    parser.add_argument("--alias", help="model id advertised on /v1/models")
    parser.add_argument(
        "--no-mtp",
        action="store_true",
        help="disable MTP speculative decoding",
    )
    parser.add_argument(
        "--thinking",
        action="store_true",
        help="keep the Qwen thinking pass (about 3x latency on an A10)",
    )
    parser.add_argument(
        "--deployment-root",
        type=Path,
        help="workspace containing models/ and runtimes/ (default: this repo, or its parent)",
    )
    parser.add_argument(
        "--server",
        type=Path,
        help="explicit llama-server binary (default: runtimes/llama-cpp, then PATH)",
    )
    parser.add_argument("--ready-timeout", type=float, default=180.0)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate paths and print the resolved command without starting",
    )
    args = parser.parse_args(argv)
    if not 0 < args.port < 65536:
        parser.error("--port must be between 1 and 65535")
    if args.ready_timeout <= 0:
        parser.error("--ready-timeout must be positive")
    return args


def deployment_root(explicit: Path | None, repo: Path = PROJECT_DIR) -> Path:
    if explicit is not None:
        root = explicit.expanduser().resolve()
        if not root.is_dir():
            raise LauncherError(f"deployment root not found: {root}")
        return root
    # A nested checkout inside the deployment workspace keeps models/ one level up.
    return repo if (repo / "models").is_dir() else repo.parent


def server_binary_name(os_name: str = os.name) -> str:
    return "llama-server.exe" if os_name == "nt" else "llama-server"


def resolve_server(root: Path, explicit: Path | None, os_name: str = os.name) -> Path:
    if explicit is not None:
        candidate = explicit.expanduser().resolve()
        if not candidate.is_file():
            raise LauncherError(f"llama-server not found: {candidate}")
    else:
        name = server_binary_name(os_name)
        bundled = root / "runtimes" / "llama-cpp" / name
        if bundled.is_file():
            candidate = bundled
        else:
            found = shutil.which(name)
            if found is None:
                raise LauncherError(
                    f"llama-server not found: {bundled} (not on PATH either; pass --server)"
                )
            candidate = Path(found).resolve()
    if os_name != "nt" and not os.access(candidate, os.X_OK):
        raise LauncherError(f"llama-server is not executable: {candidate} (chmod +x)")
    return candidate


def build_command(
    server: Path,
    args: argparse.Namespace,
    model_path: Path,
    mmproj_path: Path,
    model_id: str,
) -> list[str]:
    profile = PROFILES[args.profile]
    command = [
        str(server),
        "--model",
        str(model_path),
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--alias",
        model_id,
        "--gpu-layers",
        "all",
        "--ctx-size",
        str(profile.ctx),
        "--parallel",
        str(profile.parallel),
        "--batch-size",
        "1024",
        "--ubatch-size",
        "256",
        "--cache-type-k",
        "q8_0",
        "--cache-type-v",
        "q8_0",
        "--flash-attn",
        "on",
        "--jinja",
        "--no-context-shift",
        "--fit",
        "off",
    ]
    if args.vision:
        command += ["--mmproj", str(mmproj_path)]
    if not args.no_mtp:
        command += ["--spec-type", "draft-mtp", "--spec-draft-n-max", "2"]
    if not args.thinking:
        command += ["--reasoning", "off"]
    return command


def client_host(bind_host: str) -> str:
    """Address the launcher (and the app) should connect to for a bind address."""
    if bind_host in {"", "0.0.0.0"}:
        return "127.0.0.1"
    if bind_host == "::":
        return "[::1]"
    return (
        f"[{bind_host}]"
        if ":" in bind_host and not bind_host.startswith("[")
        else bind_host
    )


def server_environment(server: Path, os_name: str = os.name) -> dict[str, str]:
    environment = os.environ.copy()
    if os_name != "nt":
        # Linux llama.cpp release archives ship their shared libraries next to the binary.
        existing = environment.get("LD_LIBRARY_PATH")
        environment["LD_LIBRARY_PATH"] = (
            f"{server.parent}{os.pathsep}{existing}" if existing else str(server.parent)
        )
    return environment


def launch(
    command: Sequence[str],
    stdout_path: Path,
    stderr_path: Path,
    environment: dict[str, str],
) -> subprocess.Popen:
    """Start the server detached from this launcher so it keeps running after exit."""
    options: dict = {"env": environment, "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    with open(stdout_path, "wb") as stdout, open(stderr_path, "wb") as stderr:
        return subprocess.Popen(list(command), stdout=stdout, stderr=stderr, **options)


def served_model_id(url: str, timeout: float = PROBE_TIMEOUT_SECONDS) -> str | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return None
    model_id = data[0].get("id")
    return str(model_id) if model_id else None


def wait_until_ready(
    process: subprocess.Popen,
    url: str,
    timeout: float,
    stderr_path: Path,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    deadline = clock() + timeout
    while clock() < deadline:
        code = process.poll()
        if code is not None:
            raise LauncherError(
                f"llama-server exited with code {code}. See {stderr_path}"
            )
        model_id = served_model_id(url)
        if model_id is not None:
            return model_id
        sleep(POLL_SECONDS)
    raise LauncherError(
        f"llama-server did not become ready within {timeout:g} seconds. See {stderr_path}"
    )


def stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def run(args: argparse.Namespace, repo: Path = PROJECT_DIR) -> int:
    root = deployment_root(args.deployment_root, repo)
    server = resolve_server(root, args.server)
    spec = MODELS[args.model]
    model_path = root / "models" / spec.file
    mmproj_path = root / "models" / spec.mmproj
    if not model_path.is_file():
        raise LauncherError(f"model file not found: {model_path}")
    if args.vision and not mmproj_path.is_file():
        raise LauncherError(f"mmproj not found: {mmproj_path}")
    model_id = args.alias or spec.default_alias
    command = build_command(server, args, model_path, mmproj_path, model_id)
    profile = PROFILES[args.profile]
    base_url = f"http://{client_host(args.host)}:{args.port}/v1"

    if args.dry_run:
        print(
            json.dumps(
                {"server": str(server), "command": command, "endpoint": base_url},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    log_dir = repo / "runtime" / "local-model"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = f"server-{args.model}-{args.profile}-{args.port}-{stamp}"
    stdout_path = log_dir / f"{stem}.out.log"
    stderr_path = log_dir / f"{stem}.err.log"

    print(f"llama-server: {server}")
    print(f"model       : {model_path}")
    print(f"context     : {profile.ctx} (parallel {profile.parallel})")
    print(f"endpoint    : {base_url}")
    print(f"logs        : {stderr_path}")
    if not args.vision:
        print(
            "note: starting text-only; models declaring native_multimodal=true "
            "will fail image compatibility (use --vision)."
        )
    sys.stdout.flush()

    process = launch(command, stdout_path, stderr_path, server_environment(server))
    try:
        served = wait_until_ready(
            process, f"{base_url}/models", args.ready_timeout, stderr_path
        )
    except BaseException:
        # A half-started server would keep holding GPU memory and the port.
        stop(process)
        raise

    print()
    print(f"ready: pid={process.pid}  model_id={served}")
    print("point Fab Insight Agent at it:")
    print("  FAB_MODEL_PROVIDER=openai-compatible")
    print(f"  FAB_MODEL_BASE_URL={base_url}")
    print(f"  FAB_MODEL_NAME={served}")
    print("  FAB_MODEL_API_KEY=local   # any non-empty value")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except LauncherError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted; llama-server stopped", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
