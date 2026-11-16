"""Unified resc CLI; Python diagnostics and native recovery have explicit capabilities."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

COMMANDS = {"header": "disk_header_inspector", "driver": "driver_and_device_manager",
            "format-recover": "format_recovery_engine", "usb-verify": "usb_format_verify",
            "audit": "evidence_audit", "recover": "recovery", "rescue": "rescue"}
ROOT = Path(__file__).resolve().parents[1]


def run_doctor():
    name = "mcp-server.exe" if os.name == "nt" else "mcp-server"
    configured = os.environ.get("RESC_MCP_BIN") or os.environ.get("RECOVERYAI_MCP_BIN")
    candidates = [Path(configured)] if configured else [ROOT / "target" / kind / name for kind in ("release", "debug")]
    binary = next((str(p.resolve()) for p in candidates if p.is_file()), None)
    supported = sys.version_info >= (3, 11)
    print(json.dumps({"status": ("NATIVE_BINARY_PRESENT" if binary else "LIMITED_PYTHON_DIAGNOSTICS") if supported else "UNSUPPORTED_PYTHON",
                      "python": sys.version.split()[0], "native_binary": binary,
                      "native_binary_execution_verified": False,
                      "python_tools": ["header", "driver inspect (Windows)", "audit"],
                      "native_required": ["sessions", "overlay repairs", "recovery jobs", "file extraction"],
                      "tools": {n: shutil.which(n) for n in ("node", "cargo", "ffmpeg", "ffprobe", "ddrescue")}}, indent=2))
    return 0 if supported else 1


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print("resc: doctor | " + " | ".join(COMMANDS) + "\nUse <command> --help for options.")
        return 0
    if args == ["doctor"]:
        return run_doctor()
    module = COMMANDS.get(args[0])
    if module:
        return subprocess.call([sys.executable, "-X", "utf8", str(ROOT / "scripts" / (module + ".py")), *args[1:]])
    print("Unknown command or invalid arguments", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
