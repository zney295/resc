"""Limited Python MCP diagnostics. No native-session/WAL/job compatibility is claimed."""
import argparse
import json
import sys

import disk_header_inspector as headers

TOOL = {
    "name": "inspect_disk_headers",
    "description": "Limited Python backend: read-only regular-image header evidence. No repair/extraction. Returns at most eight volume samples.",
    "inputSchema": {"type": "object", "additionalProperties": False,
                    "properties": {"target_path": {"type": "string"},
                                   "sector_size": {"type": "integer", "enum": [512, 4096]}},
                    "required": ["target_path"]},
}


def compact(report):
    def gpt(key):
        obj = report[key]
        return {k: obj[k] for k in ("present", "header_crc32_valid", "entry_array_crc32_valid", "geometry_valid") if k in obj}
    return {"backend": "python-diagnostics", "scope": "header evidence only; no mount/content verification",
            "disk_size_bytes": report["disk_size_bytes"], "sector_size": report["sector_size"],
            "primary_gpt": gpt("primary_gpt"), "backup_gpt": gpt("backup_gpt"),
            "mbr_signature_present": report["mbr"].get("valid_signature", False),
            "volumes": [{k: v[k] for k in ("start_lba", "filesystem", "valid") if k in v}
                        for v in report["volume_boot_records"][:8]],
            "volume_count": len(report["volume_boot_records"]),
            "limitations": report["recommendations"]}


def dispatch(request):
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    if "id" not in request:
        return None
    response = {"jsonrpc": "2.0", "id": request["id"]}
    method = request["method"]
    params = request.get("params", {})
    if not isinstance(params, dict):
        response["error"] = {"code": -32602, "message": "params must be an object"}
        return response
    if method == "initialize":
        response["result"] = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                              "serverInfo": {"name": "resc-python-diagnostics", "version": "1.0.0"},
                              "instructions": "Limited read-only diagnostics. Native Rust required for sessions, overlay repairs and extraction."}
    elif method == "ping":
        response["result"] = {}
    elif method == "tools/list":
        response["result"] = {"tools": [TOOL]}
    elif method == "tools/call":
        try:
            if params.get("name") != TOOL["name"]:
                raise NotImplementedError("Tool unavailable in Python diagnostics; use native Rust backend")
            args = params.get("arguments", {})
            if not isinstance(args, dict) or set(args) - {"target_path", "sector_size"}:
                raise ValueError("Invalid tool arguments")
            from pathlib import Path
            path = args.get("target_path")
            if not isinstance(path, str) or not Path(path).is_file():
                raise ValueError("Python MCP accepts acquired regular images only")
            result = compact(headers.inspect_disk_headers(path, args.get("sector_size", 512)))
            response["result"] = {"content": [{"type": "text", "text": json.dumps(result)}]}
        except (OSError, ValueError, TypeError, NotImplementedError) as error:
            response["result"] = {"isError": True, "content": [{"type": "text", "text": str(error)[:1000]}]}
    else:
        response["error"] = {"code": -32601, "message": "Method not found"}
    return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--read-only-enforced", action="store_true")
    args = parser.parse_args()
    if args.version:
        print("resc-python-diagnostics 1.0.0 (limited; no recovery engine)")
        return 0
    while True:
        line = sys.stdin.buffer.readline(65537)
        if not line:
            break
        if len(line) > 65536:
            return 1
        try:
            response = dispatch(json.loads(line))
        except (ValueError, UnicodeError):
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        if response is not None:
            print(json.dumps(response), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
