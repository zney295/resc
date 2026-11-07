"""Install resc MCP configuration and bundled skills for Codex and Antigravity."""
import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import tomllib
from urllib.parse import unquote, urlsplit
import uuid

PROJECT = Path(__file__).resolve().parents[1]
SKILLS = ("recovery-triage", "disk-forensics", "filesystem-repair",
          "file-carving-and-defrag", "mcp-disk-automation")
BEGIN = "# BEGIN resc managed MCP"
END = "# END resc managed MCP"


def safe_stat(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError(f"Linked path component: {path}")
    return info


def directory(path, create=False):
    for current in (*reversed(path.parents), path):
        info = safe_stat(current)
        if info is None and create:
            current.mkdir(exist_ok=True)
            info = safe_stat(current)
        if info is not None and not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"Expected directory: {current}")


@dataclass(frozen=True)
class Snapshot:
    data: bytes
    mode: int
    identity: tuple
    mtime: int


def snapshot(path):
    directory(path.parent)
    before = safe_stat(path)
    if before is None:
        return None
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > 8 * 1024**2:
        raise ValueError(f"Expected a bounded, unlinked regular file: {path}")
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) |
                           getattr(os, "O_BINARY", 0)), "rb") as stream:
        opened = os.fstat(stream.fileno())
        data = stream.read(8 * 1024**2 + 1)
        after = safe_stat(path)
        if not after or not (os.path.samestat(before, opened) and os.path.samestat(opened, after)) or (
            (len(data), opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
        ):
            raise ValueError(f"File changed during read: {path}")
    return Snapshot(data, stat.S_IMODE(after.st_mode), (after.st_dev, after.st_ino), after.st_mtime_ns)


def skill_files(directory_path):
    directory(directory_path)
    for path in sorted(directory_path.iterdir()):
        if stat.S_ISDIR(safe_stat(path).st_mode):
            yield from skill_files(path)
        elif path.suffix == ".md":
            yield path, snapshot(path).data


def installed_skill_content(path, data):
    """Keep repository documentation links usable from an installed skill."""
    def documentation_link(match):
        link = urlsplit(match[1])
        if link.scheme or link.netloc or not link.path:
            return match[0]
        target = (path.parent / unquote(link.path)).resolve()
        if not target.is_relative_to(PROJECT / "docs"):
            return match[0]
        if target.is_file():
            destination = target.as_uri()
        else:
            relative = target.relative_to(PROJECT).as_posix()
            destination = f"https://github.com/psy-zney/resc/blob/main/{relative}"
        fragment = f"#{link.fragment}" if link.fragment else ""
        return f"]({destination}{fragment})"

    return re.sub(r"\]\(([^\s)]+)\)", documentation_link, data.decode("utf-8")).encode("utf-8")


def antigravity_config(original, server):
    config = json.loads(original.decode("utf-8-sig")) if original else {}
    if not isinstance(config, dict) or not isinstance(config.setdefault("mcpServers", {}), dict):
        raise ValueError("Antigravity config must contain an mcpServers object")
    if config["mcpServers"].get("resc") == server:
        return original
    config["mcpServers"]["resc"] = server
    return (json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def codex_config(original, server):
    text = original.decode("utf-8")
    old = tomllib.loads(text)
    servers = old.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise ValueError("Codex mcp_servers must be a TOML table")
    wanted = dict(server, startup_timeout_sec=30, tool_timeout_sec=120)
    if servers.get("resc") == wanted:
        return original
    lines = text.splitlines(keepends=True)
    begins = [i for i, line in enumerate(lines) if line.rstrip() == BEGIN]
    ends = [i for i, line in enumerate(lines) if line.rstrip() == END]
    if begins or ends:
        if len(begins) != 1 or len(ends) != 1 or begins[0] >= ends[0]:
            raise ValueError("Invalid resc managed section in Codex config")
        first, last = begins[0], ends[0]
        existing_block = tomllib.loads("".join(lines[first + 1:last]))
        if set(existing_block) != {"mcp_servers"} or set(existing_block["mcp_servers"]) != {"resc"}:
            raise ValueError("The managed Codex section contains unmanaged settings")
        prefix, suffix = "".join(lines[:first]), "".join(lines[last + 1:])
    else:
        if "resc" in servers:
            raise ValueError("Existing Codex resc entry is managed manually")
        prefix, suffix = text.rstrip("\r\n") + "\n\n" if text else "", ""
    newline = "\r\n" if "\r\n" in text else "\n"
    block = newline.join([BEGIN, "[mcp_servers.resc]",
                          "command = " + json.dumps(server["command"], ensure_ascii=False),
                          "args = " + json.dumps(server["args"], ensure_ascii=False),
                          "startup_timeout_sec = 30", "tool_timeout_sec = 120", END, ""])
    merged = prefix + block + suffix
    servers["resc"] = wanted
    old["mcp_servers"] = servers
    if tomllib.loads(merged) != old:
        raise ValueError("The Codex merge changes unmanaged configuration")
    return merged.encode("utf-8")


@dataclass
class Change:
    path: Path
    before: Snapshot | None
    data: bytes


def plan(root, client, server, codex_dir=None):
    changes = []
    for name in ("codex", "antigravity") if client == "both" else (client,):
        if name == "codex":
            config = (codex_dir or root / ".codex") / "config.toml"
            skills, merge = root / ".agents/skills", codex_config
        else:
            base = root / ".gemini/config"
            config, skills, merge = base / "mcp_config.json", base / "skills", antigravity_config
        before = snapshot(config)
        changes.append(Change(config, before, merge(before.data if before else b"", server)))
        for skill in SKILLS:
            source = PROJECT / ".agents/skills" / skill
            for path, data in skill_files(source):
                destination = skills / skill / path.relative_to(source)
                changes.append(Change(destination, snapshot(destination), installed_skill_content(path, data)))
    return [change for change in changes if not change.before or change.before.data != change.data]


def stage(path, data, mode=None):
    directory(path.parent, create=True)
    fd, temporary = tempfile.mkstemp(prefix=".resc-", dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            if mode is not None:
                os.chmod(temporary, mode)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def publish(changes):
    transaction = uuid.uuid4().hex
    staged, applied = [], []
    try:
        for change in changes:
            original = change.before
            temporary = stage(change.path, change.data, original.mode if original else None)
            staged.append((change, temporary, snapshot(temporary)))
        for change, _, _ in staged:
            if change.before:
                backup = change.path.with_name(f"{change.path.name}.backup.{transaction}")
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
                with os.fdopen(os.open(backup, flags, 0o600), "wb") as stream:
                    stream.write(change.before.data)
                    stream.flush()
                    os.fsync(stream.fileno())
        for change, temporary, intended in staged:
            if snapshot(change.path) != change.before:
                raise ValueError(f"Destination changed since staging: {change.path}")
            os.replace(temporary, change.path)
            applied.append((change, intended))
        for change, intended in applied:
            if snapshot(change.path) != intended:
                raise ValueError(f"Readback failed: {change.path}")
    except BaseException as error:
        failures = []
        for change, intended in reversed(applied):
            try:
                current = snapshot(change.path)
                if not current or current.identity != intended.identity:
                    raise ValueError("destination replaced externally")
                if change.before:
                    restoration = stage(change.path, change.before.data, change.before.mode)
                    try:
                        os.replace(restoration, change.path)
                    finally:
                        restoration.unlink(missing_ok=True)
                else:
                    change.path.unlink()
            except (OSError, ValueError) as rollback_error:
                failures.append(f"{change.path}: {rollback_error}")
        if failures:
            raise RuntimeError(f"{error}. Incomplete rollback ({'; '.join(failures)}). Backup ID {transaction}") from error
        raise
    finally:
        for _, temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", choices=("codex", "antigravity", "both"), default="both")
    parser.add_argument("--root", type=Path, help="Client configuration home (default: user home)")
    parser.add_argument("--apply", action="store_true", help="Publish changes instead of previewing them")
    args = parser.parse_args()
    root = Path(os.path.abspath(args.root or Path.home()))
    codex_home = os.environ.get("CODEX_HOME") if args.root is None else None
    codex_dir = Path(os.path.abspath(codex_home)) if codex_home else None
    lock = root / ".resc-setup.lock"
    try:
        directory(root)
        if not root.is_dir():
            raise ValueError(f"Client root must already exist: {root}")
        node = shutil.which("node")
        if node is None:
            raise ValueError("Node.js was not found on PATH")
        server = {"command": str(Path(node).resolve()), "args": [str(PROJECT / "bin/resc-mcp.js")]}
        if args.apply:
            with lock.open("xb") as lock_file:
                try:
                    changes = plan(root, args.client, server, codex_dir)
                    publish(changes)
                finally:
                    lock_file.close()
                    lock.unlink()
        else:
            changes = plan(root, args.client, server, codex_dir)
        print(json.dumps({"applied": args.apply, "files": [str(c.path) for c in changes]}, ensure_ascii=True))
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"resc setup: {error}\n")


if __name__ == "__main__":
    main()
