"""Read-only Windows storage-driver inventory; never changes Registry/PnP state."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

PNP_CODES = {0: "No PnP error reported", 10: "Device cannot start",
             19: "Configuration error", 22: "Device disabled", 28: "Driver not installed",
             32: "Driver service disabled", 38: "Previous driver instance still loaded",
             43: "Device reported a problem", 45: "Device not connected"}

# Static script: no recovered names or user parameters interpolated into PowerShell.
INVENTORY = r"""
$ErrorActionPreference = 'Stop'
$disks = @(Get-CimInstance Win32_DiskDrive | Select-Object Index,DeviceID,Model,SerialNumber,Size,PNPDeviceID,ConfigManagerErrorCode)
$drivers = @(Get-CimInstance Win32_PnPSignedDriver | Where-Object { $_.DeviceClass -in @('DISKDRIVE','SCSIADAPTER','HDC','USB') } | Select-Object DeviceID,DriverVersion,DriverProviderName,InfName,IsSigned)
$services = @('USBSTOR','UASPSTOR','stornvme','storahci','disk','partmgr') | ForEach-Object {
  $p = "HKLM:\SYSTEM\CurrentControlSet\Services\$_"
  if (Test-Path -LiteralPath $p) {
    $s = Get-ItemProperty -LiteralPath $p
    [PSCustomObject]@{Name=$_;Start=$s.Start;ImagePath=$s.ImagePath;Present=$true}
  } else { [PSCustomObject]@{Name=$_;Present=$false} }
}
$p = 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e967-e325-11ce-bfc1-08002be10318}'
$filters = Get-ItemProperty -LiteralPath $p
[PSCustomObject]@{disks=$disks;drivers=$drivers;services=@($services);registry_filters=@{UpperFilters=@($filters.UpperFilters);LowerFilters=@($filters.LowerFilters)}} | ConvertTo-Json -Depth 6 -Compress
"""


def analyze_snapshot(snapshot, *, provenance):
    if not isinstance(snapshot, dict):
        raise ValueError("Snapshot must be an object")
    findings = []
    for disk in snapshot.get("disks", []):
        code = disk.get("ConfigManagerErrorCode")
        if code not in (None, 0):
            findings.append({"disk": disk.get("Index"), "code": code,
                             "meaning": PNP_CODES.get(code, "Unmapped PnP code")})
        if disk.get("Size") in (None, 0, "0"):
            findings.append({"disk": disk.get("Index"), "capacity": "zero_or_unknown",
                             "cause": "undetermined; does not establish NAND/FTL failure"})
    return {"operation": "inspect-drivers", "provenance": provenance,
            "status": "OBSERVED" if provenance == "live_windows" else "USER_REPORTED",
            "inventory": snapshot, "findings": findings,
            "limitations": ["Filter presence alone does not establish corruption.",
                            "No reset, write-protect removal, driver installation or Registry repair is executed.",
                            "PnP status does not establish media health or recoverability."]}


def inspect_storage_drivers(mock_snapshot_path=None):
    if mock_snapshot_path:
        path = Path(mock_snapshot_path)
        with path.open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("Snapshot exceeds 1 MiB")
        return analyze_snapshot(json.loads(raw), provenance="user_reported_snapshot")
    if os.name != "nt":
        raise NotImplementedError("Windows driver inventory only; use rescue.py inventory on Linux")
    proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", INVENTORY],
                          capture_output=True, text=True, timeout=30)
    if proc.returncode:
        raise RuntimeError(f"Driver inventory failed: {proc.stderr[-2000:]}")
    return analyze_snapshot(json.loads(proc.stdout), provenance="live_windows")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--snapshot", help="Analyze saved JSON as user-reported evidence")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(inspect_storage_drivers(args.snapshot), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, NotImplementedError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
