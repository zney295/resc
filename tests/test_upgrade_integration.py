"""Synthetic regression tests for the reviewed v5 integration; no user devices."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import disk_header_inspector as headers
import driver_and_device_manager as drivers
import mcp_server_engine as server
import setup_clients
from synthetic_filesystems import create_gpt, create_ntfs, create_fat32


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "image.img"

    def tearDown(self):
        self.temp.cleanup()

    def command(self, script, *args, **kwargs):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / script), *map(str, args)],
                              capture_output=True, text=True, encoding="utf-8", timeout=45, **kwargs)

    def test_gpt_crc_geometry_and_source_preserved(self):
        create_gpt(self.source)
        before = hashlib.sha256(self.source.read_bytes()).digest()
        report = headers.inspect_disk_headers(str(self.source))
        for key in ("primary_gpt", "backup_gpt"):
            self.assertTrue(report[key]["header_crc32_valid"])
            self.assertTrue(report[key]["entry_array_crc32_valid"])
            self.assertTrue(report[key]["geometry_valid"])
        self.assertEqual(before, hashlib.sha256(self.source.read_bytes()).digest())
        create_gpt(self.source, out_of_bounds=True)
        self.assertFalse(headers.inspect_disk_headers(str(self.source))["primary_gpt"]["geometry_valid"])
        mbr = bytearray(512)
        mbr[510:512] = b"\x55\xaa"
        mbr[450] = 0x06
        struct.pack_into("<II", mbr, 454, 2048, 1024)
        result = headers.decode_mbr(mbr, 512, 64 * 1024**3)
        self.assertFalse(result["anomalies"], "Small FAT16 partition on a large disk is not fake")

    def test_corrupt_gpt_array(self):
        create_gpt(self.source, bad_array=True)
        self.assertFalse(headers.inspect_disk_headers(str(self.source))["primary_gpt"]["entry_array_crc32_valid"])

    def test_ntfs_usa_torn_sector(self):
        create_ntfs(self.source)
        def record():
            return next(v for v in headers.inspect_disk_headers(str(self.source))["volume_boot_records"]
                        if v["filesystem"] == "NTFS")["mft_record_0"]
        self.assertTrue(record()["usa_fixup_valid"])
        with self.source.open("r+b") as stream:
            stream.seek(2048 * 512 + 4 * 4096 + 510)
            stream.write(b"XX")
        self.assertFalse(record()["usa_fixup_valid"])
        self.assertEqual(record()["attributes_found"], [])

    def test_fat32_fsinfo_trailer(self):
        create_fat32(self.source)
        with headers.AlignedDiskReader(str(self.source)) as reader:
            self.assertTrue(headers.decode_vbr(reader, 0)["fsinfo_valid"])
        with self.source.open("r+b") as stream:
            stream.seek(512 + 508)
            stream.write(bytes(4))
        with headers.AlignedDiskReader(str(self.source)) as reader:
            self.assertFalse(headers.decode_vbr(reader, 0)["fsinfo_valid"])

    def test_read_failures_not_reported_as_blank(self):
        self.source.write_bytes(bytes(4096))
        with headers.AlignedDiskReader(str(self.source)) as reader:
            with patch.object(headers.os, "read", side_effect=OSError("I/O error")):
                with self.assertRaises(OSError):
                    reader.read_at(0, 512)
            with patch.object(headers.os, "read", return_value=b""):
                with self.assertRaises(OSError):
                    reader.read_at(0, 512)

    def test_empty_source_rejected(self):
        self.source.touch()
        with self.assertRaises(OSError):
            headers.inspect_disk_headers(str(self.source))

    def test_dump_exclusive_and_bounded(self):
        self.source.write_bytes(bytes(4096))
        out = self.root / "dump.bin"
        result = headers.dump_disk_headers(str(self.source), str(out))
        self.assertEqual(result["bytes_dumped"], 4096)
        with self.assertRaises(FileExistsError):
            headers.dump_disk_headers(str(self.source), str(out))
        with self.assertRaises(ValueError):
            headers.dump_disk_headers(str(self.source), str(self.root / "new.bin"), head_mib=1000)

    def test_ext_signature_does_not_prove_ext4(self):
        raw = bytearray(4096)
        struct.pack_into("<H", raw, 1024 + 56, 0xef53)
        self.source.write_bytes(raw)
        with headers.AlignedDiskReader(str(self.source)) as reader:
            result = headers.decode_vbr(reader, 0)
        self.assertEqual(result["filesystem"], "EXT_FAMILY")
        self.assertFalse(result["valid"])

    def test_snapshot_is_not_live_or_hardware_diagnosis(self):
        result = drivers.analyze_snapshot({"disks": [{"Size": 0, "ConfigManagerErrorCode": 43}]}, provenance="user_reported_snapshot")
        self.assertEqual(result["status"], "USER_REPORTED")
        self.assertIn("undetermined", result["findings"][1]["cause"])

    def test_mcp_errors_notifications_and_budget(self):
        self.assertIsNone(server.dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(server.dispatch([])["error"]["code"], -32600)
        create_gpt(self.source)
        response = server.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                    "params": {"name": "inspect_disk_headers", "arguments": {"target_path": str(self.source)}}})
        self.assertNotIn("isError", response["result"])
        self.assertLess(len(json.dumps(response).encode()), 5000)
        response = server.dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "virtual_patch_and_verify"}})
        self.assertTrue(response["result"]["isError"])

    def test_python_stdio_and_launcher(self):
        requests = '\n'.join(json.dumps({"jsonrpc": "2.0", "id": i, "method": m}) for i, m in enumerate(["initialize", "tools/list"])) + '\n'
        proc = self.command("mcp_server_engine.py", input=requests)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout.splitlines()[1])["result"]["tools"][0]["name"], "inspect_disk_headers")
        import shutil
        if shutil.which("node"):
            proc = subprocess.run(["node", str(ROOT / "bin/resc-mcp.js"), "--version"], capture_output=True,
                                  text=True, env=dict(os.environ, RESC_BACKEND="python"), timeout=15)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("limited", proc.stdout)

    def test_installer_preview_apply_idempotent_runtime(self):
        home = self.root / "home"
        proc = self.command("install.py", "--root", home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(home.exists())
        proc = self.command("install.py", "--root", home, "--apply")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for filename in setup_clients.RUNTIME_FILES:
            self.assertEqual((home / ".agents/skills/recovery-triage/scripts" / filename).read_bytes(),
                             (ROOT / "scripts" / filename).read_bytes())
        proc = self.command("install.py", "--root", home, "--apply")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["files"], [])

    def test_cli_help_routes(self):
        for command in ("header", "driver", "format-recover", "usb-verify", "audit", "recover", "rescue"):
            proc = self.command("resc_cli.py", command, "--help")
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_format_rejects_in_place(self):
        proc = self.command("format_recovery_engine.py", "reconstruct-format", self.source, "--in-place")
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(self.source.exists())

    def test_triage_without_rust_is_explicitly_partial(self):
        create_gpt(self.source)
        proc = self.command("recovery.py", "--binary", self.root / "missing.exe", "triage", self.source)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["status"], "LIMITED_PYTHON_DIAGNOSTICS")

    def test_native_overlay_and_salvage_preserve_source(self):
        binary = ROOT / "target/release" / ("mcp-server.exe" if os.name == "nt" else "mcp-server")
        if not binary.is_file():
            self.skipTest("Native binary not built")
        fixture = create_ntfs(self.source, corrupt_boot=True)
        original = hashlib.sha256(self.source.read_bytes()).hexdigest()
        env = dict(os.environ, RESC_SESSION_ROOT=str(self.root / "sessions"))
        plan = self.root / "patch.json"
        plan.write_text(json.dumps({"copy_from_lba": fixture["backup"], "to_lba": fixture["start"]}))
        proc = self.command("format_recovery_engine.py", "--binary", binary, "apply-overlay", self.source,
                            "--partition-start-lba", fixture["start"], "--patch-plan", plan, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        session_id = json.loads(proc.stdout)["session"]["session_id"]
        proc = self.command("format_recovery_engine.py", "--binary", binary, "salvage-files", self.source,
                            "--partition-start-lba", fixture["start"], "--resume-session-id", session_id,
                            "--output-dir", self.root / "recovered", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        recovered = list((self.root / "recovered").rglob(fixture["name"]))
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].read_bytes(), fixture["payload"])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), original)


if __name__ == "__main__":
    unittest.main()
