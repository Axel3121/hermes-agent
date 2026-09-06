"""Drive the real ``hermes subagent model`` picker under a Linux PTY and check route isolation.

No provider requests: the picked target is a saved custom provider with ``discover_models: false``.
Invariant: the primary ``model`` (and auth ``active_provider``) in the temp HERMES_HOME are byte-equal
before and after; ``delegation.model/provider`` carry the picked child route.
"""
import argparse
import errno
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import fcntl

CONFIG = (
    "model:\n  provider: openrouter\n  default: primary/model-a\n"
    "  base_url: https://openrouter.ai/api/v1\n  api_mode: chat_completions\n"
    "custom_providers:\n  - name: LocalLab\n    base_url: http://127.0.0.1:9/v1\n"
    "    model: lab-model\n    discover_models: false\n    models:\n      - lab-model\n"
    "memory:\n  provider: ''\n")


def _persisted(root: Path, env: dict) -> dict:
    """``config.yaml`` as the CLI itself reads it (owner module, same env)."""
    out = subprocess.run(
        [sys.executable, "-c", "import json; from hermes_cli.config import load_config; "
         "print(json.dumps(load_config()))"],
        cwd=root, env=env, capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def run(root: Path, output: Path, cancel: bool) -> dict:
    with tempfile.TemporaryDirectory(prefix="hermes_test_subagent_") as home:
        hh = Path(home) / ".hermes"
        hh.mkdir()
        (hh / "config.yaml").write_text(CONFIG, encoding="utf-8")
        (hh / ".env").write_text("OPENROUTER_API_KEY=local-not-used\n", encoding="utf-8")
        auth = hh / "auth.json"
        auth.write_text(json.dumps({"version": 1, "providers": {}, "active_provider": "nous"}))
        shim = Path(home) / "shim" / "curses"
        shim.mkdir(parents=True)
        (shim / "__init__.py").write_text("raise ImportError('curses disabled for PTY harness')\n")
        env = {"PATH": os.environ["PATH"], "HOME": home, "HERMES_HOME": str(hh),
               "PYTHONPATH": f"{shim.parent}{os.pathsep}{root}", "PYTHONUNBUFFERED": "1",
               "TERM": "dumb", "LANG": "C.UTF-8"}
        model_before = _persisted(root, env)["model"]
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 120, 0, 0))
        proc = subprocess.Popen([sys.executable, "-m", "hermes_cli.main", "subagent", "model"],
                                cwd=root, env=env, stdin=slave, stdout=slave, stderr=slave,
                                start_new_session=True)
        os.close(slave)
        data = bytearray()

        def pump_until(predicate, timeout=60):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if predicate(bytes(data)):
                    return True
                if select.select([master], [], [], 0.1)[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError as exc:
                        if exc.errno == errno.EIO:
                            return predicate(bytes(data))
                        raise
                    if not chunk:
                        return predicate(bytes(data))
                    data.extend(chunk)
            return predicate(bytes(data))

        name = "cancel" if cancel else "pick"
        try:
            assert pump_until(lambda b: b"Choice [default" in b), data[-2000:]
            text = bytes(data).decode(errors="replace")
            if cancel:
                # EOF at the numbered prompt (no controlling tty here, so ^C is not a SIGINT).
                os.write(master, b"\x04")
                # main's _prompt_provider_choice re-asks with a plain numbered prompt after the
                # curses-fallback cancel; EOF that one too.
                offset = len(data)
                if pump_until(lambda b: b"Choice [1-" in b[offset:], 10):
                    os.write(master, b"\x04")
            else:
                row = re.search(r"(\d+)\. LocalLab", text)
                assert row, text[-3000:]
                os.write(master, f"{row.group(1)}\r".encode())
                offset = len(data)
                assert pump_until(lambda b: b"Choice [" in b[offset:]), data[-2000:]
                os.write(master, b"1\r")
            exited = pump_until(lambda b: proc.poll() is not None, 90)
            proc.wait(timeout=30)
            cfg = _persisted(root, env)
            text = bytes(data).decode(errors="replace")
            return {"case": name, "exited": exited, "returncode": proc.returncode,
                    "model_after": cfg["model"], "primary_unchanged": cfg["model"] == model_before,
                    # load_config() merges defaults; only the override pair is under test.
                    "delegation": {k: (cfg.get("delegation") or {}).get(k) or None
                                   for k in ("model", "provider")},
                    "auth_active_provider": json.loads(auth.read_text()).get("active_provider"),
                    "reported": [ln.strip() for ln in text.splitlines()
                                 if "subagent model" in ln.lower()],
                    "raw_path": str(output / f"subagent-model-{name}.pty")}
        finally:
            output.mkdir(parents=True, exist_ok=True)
            (output / f"subagent-model-{name}.pty").write_bytes(data)
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=30)
            os.close(master)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    results = [run(root, args.output, cancel=False), run(root, args.output, cancel=True)]
    (args.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))
    pick, cancel = results
    assert pick["primary_unchanged"] and cancel["primary_unchanged"], results
    assert pick["auth_active_provider"] == "nous" == cancel["auth_active_provider"], results
    assert pick["delegation"] == {"model": "lab-model", "provider": "custom:locallab"}, results
    assert cancel["delegation"] == {"model": None, "provider": None}, results


if __name__ == "__main__":
    main()
