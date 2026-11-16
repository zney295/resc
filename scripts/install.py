"""Install client configuration, five skills and a resc wrapper; preview by default."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import setup_clients as setup


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", choices=("codex", "antigravity", "both"), default="both")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--bin-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--try-rust-build", action="store_true")
    args = parser.parse_args(argv)
    root = Path(os.path.abspath(args.root or Path.home()))
    bindir = Path(os.path.abspath(args.bin_dir or root / ".local/bin"))
    codex_home = os.environ.get("CODEX_HOME") if args.root is None else None
    codex_dir = Path(os.path.abspath(codex_home)) if codex_home else None
    name = "mcp-server.exe" if os.name == "nt" else "mcp-server"
    binary = setup.PROJECT / "target/release" / name
    try:
        if args.try_rust_build and args.apply:
            subprocess.run(["cargo", "build", "--release", "--workspace", "--locked"], cwd=setup.PROJECT, check=True)
        server = ({"command": str(binary), "args": ["--read-only-enforced"]} if binary.is_file() else
                  {"command": sys.executable, "args": [str(setup.PROJECT / "scripts/mcp_server_engine.py")]})
        changes = setup.plan(root, args.client, server, codex_dir)
        cli = str(setup.PROJECT / "scripts/resc_cli.py")
        if os.name == "nt":
            if any(c in sys.executable + cli for c in ('%', '\n', '\r', '"')):
                raise ValueError("Paths cannot be safely represented in a CMD wrapper")
            wrapper = bindir / "resc.cmd"
            data = f'@echo off\r\n"{sys.executable}" "{cli}" %*\r\n'.encode()
        else:
            wrapper = bindir / "resc"
            data = f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(cli)} "$@"\n'.encode()
        before = setup.snapshot(wrapper)
        if not before or before.data != data:
            changes.append(setup.Change(wrapper, before, data))
        if args.apply:
            setup.directory(root, create=True)
            lock = root / ".resc-setup.lock"
            lock_stream = lock.open("x")
            try:
                with lock_stream:
                    setup.publish(changes)
                    if os.name != "nt":
                        wrapper.chmod(0o755)
            finally:
                lock.unlink()
        print(json.dumps({"applied": args.apply, "files": [str(c.path) for c in changes],
                          "server": server, "backend": "native" if binary.is_file() else "limited-python-diagnostics",
                          "wrapper": str(wrapper), "path_note": "Add wrapper directory to PATH; repository must remain in place."}, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"resc install: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
