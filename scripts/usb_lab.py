"""Explicitly authorized Windows USB reuse, separate from read-only recovery."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


def confirmation(inventory, operation, filesystem):
    plan = {"device": inventory, "operation": operation, "filesystem": filesystem}
    return hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()


def worker(request):
    environment = dict(os.environ, RESC_USB_REQUEST=json.dumps(request))
    script = Path(__file__).with_name("usb_lab.ps1")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(script)],
        env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode:
        raise ValueError(result.stderr.strip() or "USB operation failed")
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("format", "write-canary"))
    parser.add_argument("--drive", required=True, help="USB drive letter, e.g. D:")
    parser.add_argument("--filesystem", choices=("exfat", "fat32"), default="exfat")
    parser.add_argument("--confirm", help="Exact SHA-256 token printed by the preview")
    parser.add_argument("--data-loss-accepted", action="store_true")
    args = parser.parse_args()
    try:
        if os.name != "nt":
            raise ValueError("USB execution requires Windows")
        if not re.fullmatch(r"[A-Za-z]:?", args.drive):
            raise ValueError("Expected a drive letter")
        drive = args.drive[0].upper()
        request = {"operation": args.operation, "drive": drive, "filesystem": args.filesystem}
        inventory = worker(dict(request, execute=False))
        token = confirmation(inventory, args.operation, args.filesystem)
        if args.confirm is None:
            print(json.dumps({"execute": False, "device": inventory,
                              "operation": args.operation, "filesystem": args.filesystem,
                              "confirmation": token,
                              "format_erases_entire_disk": args.operation == "format",
                              "canary_bytes": 4 * 1024**2}, indent=2))
            return
        if args.confirm != token:
            raise ValueError("Device or operation differs from the approved preview")
        if args.operation == "format" and not args.data_loss_accepted:
            raise ValueError("Formatting requires --data-loss-accepted")
        result = worker(dict(request, execute=True, expected=inventory))
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.exit(1, f"USB lab: {error}\n")


if __name__ == "__main__":
    main()
