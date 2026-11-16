"""USB execution guards tested with synthetic Windows storage inventory only."""
import json
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import usb_lab


class UsbLabTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows CLI")
    def test_preview_never_executes(self):
        with patch.object(sys, "argv", ["usb_format_verify.py", "format", "--drive", "D:"]), \
                patch.object(usb_lab, "worker", return_value={"serial": "fixture"}) as worker, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            usb_lab.main()
        self.assertFalse(json.loads(output.getvalue())["execute"])
        self.assertEqual(worker.call_count, 1)
        self.assertFalse(worker.call_args.args[0]["execute"])

    @unittest.skipUnless(os.name == "nt", "Windows CLI")
    def test_format_requires_matching_token_and_loss_acceptance(self):
        device = {"serial": "fixture"}
        token = usb_lab.confirmation(device, "format", "exfat")
        for given, acceptance in (("wrong", ["--data-loss-accepted"]), (token, [])):
            with self.subTest(token=given), \
                    patch.object(sys, "argv", ["usb_format_verify.py", "format", "--drive", "D:", "--confirm", given, *acceptance]), \
                    patch.object(usb_lab, "worker", return_value=device) as worker, \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                usb_lab.main()
            self.assertEqual(worker.call_count, 1)

    @unittest.skipUnless(os.name == "nt", "Windows canary generator")
    def test_canary_payloads_exclude_fill_bytes(self):
        import re
        code = (ROOT / "scripts/usb_lab.ps1").read_text(encoding="utf-8")
        csharp = re.search(r"Add-Type -TypeDefinition @'\n(.*?)\n'@", code, re.S).group(1)
        harness = "Add-Type -TypeDefinition @'\n" + csharp + "\n'@\n" + r'''
$ErrorActionPreference = 'Stop'
$hashes = @()
for ($i=0; $i -lt 4; $i++) {
    $data = [RescCanary]::Create(1MB)
    if ($data.Length -ne 1MB -or $data -contains 0 -or $data -contains 255) { throw 'Invalid payload' }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $hashes += [BitConverter]::ToString($sha.ComputeHash($data)) } finally { $sha.Dispose() }
}
if (@($hashes | Select-Object -Unique).Count -ne 4) { throw 'Repeated payloads' }
'''
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", harness], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_confirmation_binds_device_and_operation(self):
        device = {"serial": "test", "size": 1024, "number": 2}
        original = usb_lab.confirmation(device, "format", "exfat")
        self.assertNotEqual(original, usb_lab.confirmation(dict(device, number=3), "format", "exfat"))
        self.assertNotEqual(original, usb_lab.confirmation(device, "write-canary", "exfat"))
        self.assertNotEqual(original, usb_lab.confirmation(device, "format", "fat32"))

    @unittest.skipUnless(os.name == "nt", "Windows guard harness")
    def test_storage_guards(self):
        harness = r'''
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($env:RESC_TEST_SCRIPT, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$function = $ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-CheckedTarget'}, $true)
. ([scriptblock]::Create($function.Extent.Text))
$case = $env:RESC_TEST_CASE
$env:SystemDrive = 'C:'
$target = [pscustomobject]@{ Number=2; BusType='USB'; IsBoot=$false; IsSystem=$false; IsOffline=$false; IsReadOnly=$false; UniqueId='test-id'; SerialNumber='serial'; Size=1GB; LogicalSectorSize=512 }
switch ($case) {
    'disk0' { $target.Number=0 }
    'nonusb' { $target.BusType='SATA' }
    'boot' { $target.IsBoot=$true }
    'system' { $target.IsSystem=$true }
    'readonly' { $target.IsReadOnly=$true }
    'identity' { $target.SerialNumber='' }
}
function Get-Partition {
    param($DriveLetter, $DiskNumber)
    if ($DriveLetter -eq 'C') { return [pscustomobject]@{ DiskNumber=0 } }
    return [pscustomobject]@{ DiskNumber=$target.Number; DriveLetter='D'; IsBoot=($case -eq 'bootpartition'); IsSystem=$false }
}
function Get-Disk {
    param([Parameter(ValueFromPipeline=$true)]$InputObject)
    process {
        if ($null -ne $InputObject -and $InputObject.DiskNumber -eq 0) { return [pscustomobject]@{ Number=0 } }
        return $target
    }
}
function Get-CimInstance {
    param($ClassName)
    if ($case -eq 'pagefile') { return [pscustomobject]@{Name='D:\pagefile.sys'} }
    if ($case -eq 'unknownpagefile') { return [pscustomobject]@{Name='unknown'} }
    if ($case -eq 'queryfailure') { throw 'query failed' }
}
function Get-Volume {
    param([Parameter(ValueFromPipeline=$true)]$InputObject)
    process { return [pscustomobject]@{Path='\\?\Volume{12345678-1234-1234-1234-123456789abc}\'} }
}
try {
    $letter = if ($case -eq 'drivec') {'C'} else {'D'}
    $result = Get-CheckedTarget $letter
    if ($case -ne 'valid') { throw 'UNEXPECTED_ALLOW' }
    if ($result.serial -ne 'serial') { throw 'invalid result' }
    'ALLOWED'
} catch {
    if ($case -eq 'valid' -or $_.Exception.Message -eq 'UNEXPECTED_ALLOW') { throw }
    'BLOCKED'
}
'''
        for case in ("valid", "disk0", "drivec", "nonusb", "boot", "system", "bootpartition",
                     "pagefile", "unknownpagefile", "readonly", "identity", "queryfailure"):
            with self.subTest(case=case):
                environment = dict(os.environ, RESC_TEST_SCRIPT=str(ROOT / "scripts/usb_lab.ps1"), RESC_TEST_CASE=case)
                result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", harness],
                                        env=environment, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("ALLOWED" if case == "valid" else "BLOCKED", result.stdout)


if __name__ == "__main__":
    unittest.main()
