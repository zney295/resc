"""Native WAL-backed trial repairs and allocated NTFS/FAT extraction. No source writes."""
import argparse
import json
import os
from pathlib import Path
import sys

import recovery


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", default=os.environ.get("RESC_MCP_BIN") or os.environ.get("RECOVERYAI_MCP_BIN") or str(recovery.DEFAULT_BINARY))
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("reconstruct-format", "apply-overlay", "salvage-files"):
        cmd = sub.add_parser(command)
        cmd.add_argument("source")
        cmd.add_argument("--sector-size", type=int, choices=(512, 4096), default=512)
        cmd.add_argument("--partition-start-lba", type=int, required=command != "reconstruct-format")
        cmd.add_argument("--resume-session-id")
        if command == "apply-overlay":
            cmd.add_argument("--patch-plan", required=True, help="JSON arguments for virtual_patch_and_verify")
        if command == "salvage-files":
            cmd.add_argument("--output-dir", required=True)
            cmd.add_argument("--job-timeout", type=int, default=3600)
    args = parser.parse_args(argv)
    client = None
    try:
        source = Path(args.source).resolve(strict=True)
        if not source.is_file():
            raise ValueError("Use an acquired regular image; raw-device extraction is unsupported")
        if args.partition_start_lba is not None and args.partition_start_lba < 0:
            raise ValueError("partition-start-lba must be nonnegative")
        client = recovery.Client(args.binary)
        params = {"target_path": str(source), "sector_size": args.sector_size}
        if args.resume_session_id:
            params["resume_session_id"] = args.resume_session_id
        opened = client.call("open_recovery_session", params)
        params = {"session_id": opened["session_id"]}
        if args.partition_start_lba is not None:
            params["partition_start_lba"] = args.partition_start_lba
        if args.command == "reconstruct-format":
            result = client.call("analyze_partition_recovery", params)
        elif args.command == "apply-overlay":
            with Path(args.patch_plan).open("rb") as stream:
                raw = stream.read(3 * 1024 * 1024 + 1)
            if len(raw) > 3 * 1024 * 1024:
                raise ValueError("Patch plan exceeds 3 MiB")
            plan = json.loads(raw)
            allowed = {"patches", "copy_from_lba", "to_lba", "description"}
            if not isinstance(plan, dict) or set(plan) - allowed:
                raise ValueError("Plan may only contain patches, copy_from_lba, to_lba, description")
            result = client.call("virtual_patch_and_verify", dict(plan, **params))
        else:
            job = client.call("extract_recovered_data", {
                "session_id": opened["session_id"], "mode": "TSK_TREE_EXTRACT",
                "output_dir": str(Path(args.output_dir).resolve()),
                "params": {"partition_start_lba": args.partition_start_lba}})
            result = client.wait(job["job_id"], args.job_timeout)
        print(json.dumps({"session": opened, "result": result,
                          "source_modified": False}, ensure_ascii=False, indent=2))
        if args.command == "apply-overlay" and result.get("mount_status") != "SUCCESS":
            return 2
        return 0
    except (OSError, ValueError, RuntimeError, TimeoutError) as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}), file=sys.stderr)
        return 1
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    sys.exit(main())
