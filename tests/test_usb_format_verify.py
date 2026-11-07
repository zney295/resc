"""Test T0/T1/T2 verification on disposable 512-byte and 4Kn captures."""
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from usb_format_verify import verify


def capture(path, sector, filesystem):
    start = 1024**2 // sector
    count = 131072 if filesystem == "fat32" else 8192
    mbr = bytearray(sector)
    mbr[450] = 0x0C if filesystem == "fat32" else 0x07
    struct.pack_into("<II", mbr, 454, start, count)
    mbr[510:512] = b"\x55\xaa"
    boot = bytearray(sector)
    boot[510:512] = b"\x55\xaa"
    with path.open("wb") as stream:
        stream.truncate((start + count) * sector)
        stream.write(mbr)
        stream.seek(start * sector)
        if filesystem == "fat32":
            struct.pack_into("<HBHB", boot, 11, sector, 1, 32, 2)
            struct.pack_into("<II", boot, 32, count, 1024)
            struct.pack_into("<IHH", boot, 44, 2, 1, 6)
            stream.write(boot)
            stream.seek((start + 6) * sector)
            stream.write(boot)
        else:
            boot[3:11] = b"EXFAT   "
            fat_length = (count * 4 + sector - 1) // sector
            heap = 24 + fat_length
            struct.pack_into("<QQIIIII", boot, 64, start, count, 24, fat_length, heap, count - heap, 2)
            boot[108:111] = bytes([sector.bit_length() - 1, 0, 1])
            extended = bytes(sector - 4) + b"\0\0\x55\xaa"
            region = boot + extended * 8 + bytes(sector * 2)
            checksum = 0
            for i, byte in enumerate(region):
                if i not in (106, 107, 112):
                    checksum = (((checksum << 31) | (checksum >> 1)) + byte) & 0xFFFFFFFF
            region += struct.pack("<I", checksum) * (sector // 4)
            stream.write(region * 2)


class UsbVerifyTest(unittest.TestCase):
    def test_layout_and_canary(self):
        for sector, filesystem in ((512, "fat32"), (512, "exfat"), (4096, "exfat")):
            with self.subTest(sector=sector, filesystem=filesystem), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                images = tuple(root / f"t{i}.img" for i in range(3))
                canaries = tuple(root / f"canary{i}" for i in (1, 2))
                for image in images:
                    capture(image, sector, filesystem)
                with images[0].open("r+b") as stream:
                    stream.write(bytes(sector))
                expected = bytes(range(1, 255)) * 9
                digest = hashlib.sha256(expected).hexdigest()
                for canary in canaries:
                    canary.write_bytes(expected)
                result = verify(images, canaries, digest, sector, filesystem)
                self.assertEqual(result["status"], "PERSISTENCE_VERIFIED_FOR_CAPTURES")
                canaries[1].write_bytes(expected[:-1] + b"\x01")
                with self.assertRaisesRegex(ValueError, "T2 canary hash differs"):
                    verify(images, canaries, digest, sector, filesystem)
                canaries[1].write_bytes(expected)
                with images[2].open("r+b") as stream:
                    stream.seek(1024**2 + (12 if filesystem == "exfat" else 6) * sector + 500)
                    stream.write(b"\xff")
                with self.assertRaisesRegex(ValueError, "checksum|backup boot sector"):
                    verify(images, canaries, digest, sector, filesystem)


if __name__ == "__main__":
    unittest.main()
