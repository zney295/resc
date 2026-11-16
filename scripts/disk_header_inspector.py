#!/usr/bin/env python3
"""Binary Disk Header Reader & Structural Analyzer for USB / SSD / HDD and Disk Images.

Supports reading both raw physical devices (e.g. \\\\.\\PhysicalDrive1, \\\\.\\D:, /dev/sdb,
/dev/nvme0n1 using buffered reads with aligned offsets; no unbuffered/aligned-memory guarantee) and disk image files (.img, .dd, .raw, .bin).
Decodes and validates:
  - LBA 0 Classical MBR & GPT Protective MBR (bootstrap fingerprint, disk signature, 4 partition entries)
  - LBA 1 Primary GPT & End-of-Disk Backup GPT (header CRC32, entry array CRC32, UTF-16LE names, GUIDs)
  - Volume Boot Records (VBR) & Superblocks:
      * FAT16 / FAT32 BPB + FSInfo (RRaA/rrAa) + Backup VBR (+6) comparison
      * exFAT Main Boot Region (12 sectors) & Backup Boot Region (+12) with 32-bit rolling checksum
      * NTFS VBR + Backup VBR + $MFT Record 0 (FILE0 header, Update Sequence Array fixup, attributes)
      * EXT4 Superblock (offset +1024 bytes, magic 0xEF53, block/inode geometry, UUID)
  - Storage media byte-pattern triage (All-00, All-FF, Stuck Buffer, BitLocker/LUKS/VeraCrypt high entropy)
  - Annotated Hex + ASCII dump of key header sectors and safe raw header extraction (`dump-headers`).
"""
from __future__ import annotations

import argparse
import binascii
import ctypes
import hashlib
import json
import math
import os
import stat
from pathlib import Path
import struct
import sys
from typing import Any

MBR_PARTITION_TYPES = {
    0x00: "Empty",
    0x01: "FAT12",
    0x04: "FAT16 (<32M)",
    0x05: "Extended (CHS)",
    0x06: "FAT16 (>=32M)",
    0x07: "NTFS / exFAT / HPFS",
    0x0B: "FAT32 (CHS)",
    0x0C: "FAT32 (LBA)",
    0x0E: "FAT16 (LBA)",
    0x0F: "Extended (LBA)",
    0x11: "Hidden FAT12",
    0x14: "Hidden FAT16 (<32M)",
    0x16: "Hidden FAT16 (>=32M)",
    0x17: "Hidden NTFS / exFAT",
    0x1B: "Hidden FAT32 (CHS)",
    0x1C: "Hidden FAT32 (LBA)",
    0x1E: "Hidden FAT16 (LBA)",
    0x27: "Windows Recovery Environment (Hidden NTFS)",
    0x82: "Linux Swap",
    0x83: "Linux Filesystem (EXT2/3/4)",
    0x8E: "Linux LVM",
    0xA5: "FreeBSD",
    0xAF: "macOS HFS+ / APFS",
    0xEE: "GPT Protective MBR",
    0xEF: "EFI System Partition (ESP)",
    0xFD: "Linux RAID Auto",
}

GPT_TYPE_GUIDS = {
    "00000000-0000-0000-0000-000000000000": "Unused Entry",
    "c12a7328-f81f-11d2-ba4b-00a0c93ec93b": "EFI System Partition (ESP)",
    "e3c9e316-0b5c-4db8-817d-f92df00215ae": "Microsoft Reserved Partition (MSR)",
    "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7": "Microsoft Basic Data (NTFS/exFAT/FAT32)",
    "de94bba4-06d1-4d40-a16a-bfd50179d6ac": "Windows Recovery Environment (WinRE)",
    "af9b60a0-1431-4f62-bc68-3311714a69ad": "Logical Disk Manager (LDM) Data",
    "0fc63daf-8483-4772-8e79-3d69d8477de4": "Linux Filesystem Data (EXT4/XFS/Btrfs)",
    "0657fd6d-a4ab-43c4-84e5-0933c84b4f4f": "Linux Swap",
    "e6d6d379-f507-44c2-a23c-238f2a3df928": "Linux Logical Volume Manager (LVM)",
    "48465300-0000-11aa-aa11-00306543ecac": "Apple HFS+",
    "7c3457ef-0000-11aa-aa11-00306543ecac": "Apple APFS Container",
}


def shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    length = len(data)
    entropy = 0.0
    for count in counts:
        if count:
            p = count / length
            entropy -= p * math.log2(p)
    return round(entropy, 4)


def format_guid_le(raw_16: bytes) -> str:
    if len(raw_16) != 16:
        return ""
    d1, d2, d3 = struct.unpack_from("<IHH", raw_16, 0)
    d4 = raw_16[8:10].hex()
    d5 = raw_16[10:16].hex()
    return f"{d1:08x}-{d2:04x}-{d3:04x}-{d4}-{d5}"


def format_hex_dump(data: bytes, base_offset: int = 0, max_lines: int = 32) -> list[str]:
    lines = []
    limit = min(len(data), max_lines * 16)
    for offset in range(0, limit, 16):
        chunk = data[offset:offset + 16]
        hex_left = " ".join(f"{b:02X}" for b in chunk[:8])
        hex_right = " ".join(f"{b:02X}" for b in chunk[8:])
        hex_part = f"{hex_left:<23}  {hex_right:<23}"
        ascii_part = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
        lines.append(f"0x{base_offset + offset:08X}  {hex_part}  |{ascii_part}|")
    return lines


def compute_exfat_boot_checksum(eleven_sectors: bytes) -> int:
    checksum = 0
    for idx, b in enumerate(eleven_sectors):
        if idx in (106, 107, 112):
            continue
        checksum = (((checksum << 31) | (checksum >> 1)) + b) & 0xFFFFFFFF
    return checksum


class AlignedDiskReader:
    """Read-only sector-aligned reader supporting raw physical drives and image files."""

    def __init__(self, target_path: str, sector_size: int = 512):
        if sector_size not in (512, 4096):
            raise ValueError("sector_size must be 512 or 4096")
        self.raw_path = str(target_path)
        self.sector_size = sector_size
        self.is_raw_device = (
            self.raw_path.startswith(("\\\\.\\", "\\\\?\\"))
            or self.raw_path.startswith("/dev/")
            or (len(self.raw_path) == 2 and self.raw_path[1] == ":" and self.raw_path[0].isalpha())
        )
        if len(self.raw_path) == 2 and self.raw_path[1] == ":" and self.raw_path[0].isalpha():
            self.open_target = f"\\\\.\\{self.raw_path}"
            self.is_raw_device = True
        else:
            self.open_target = self.raw_path

        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        self.fd = os.open(self.open_target, flags)
        self.stream = os.fdopen(self.fd, "rb", buffering=0)
        self.is_raw_device = self.is_raw_device or not stat.S_ISREG(os.fstat(self.fd).st_mode)
        try:
            self.size_bytes, self.detected_sector_size = self._probe_geometry()
            if self.size_bytes <= 0:
                raise OSError("Unknown/zero capacity; cannot inspect media")
        except BaseException:
            self.stream.close()
            raise
        if self.detected_sector_size in (512, 4096):
            self.sector_size = self.detected_sector_size

    def _probe_geometry(self) -> tuple[int, int]:
        if sys.platform.startswith("linux") and stat.S_ISBLK(os.fstat(self.fd).st_mode):
            import fcntl
            size = struct.unpack("Q", fcntl.ioctl(self.fd, 0x80081272, bytes(8)))[0]
            sector = struct.unpack("I", fcntl.ioctl(self.fd, 0x1268, bytes(4)))[0]
            if sector not in (512, 4096):
                raise OSError(f"Unsupported device sector size: {sector}")
            return size, sector
        try:
            st = os.fstat(self.fd)
            if st.st_size > 0:
                return st.st_size, self.sector_size
        except OSError:
            pass

        if os.name == "nt":
            try:
                import msvcrt
                handle = msvcrt.get_osfhandle(self.fd)
                kernel32 = ctypes.windll.kernel32
                bytes_returned = ctypes.c_ulong(0)

                # IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C
                length_buf = ctypes.c_ulonglong(0)
                ok_len = kernel32.DeviceIoControl(
                    ctypes.c_void_p(handle),
                    0x0007405C,
                    None,
                    0,
                    ctypes.byref(length_buf),
                    ctypes.sizeof(length_buf),
                    ctypes.byref(bytes_returned),
                    None,
                )
                # IOCTL_DISK_GET_DRIVE_GEOMETRY_EX = 0x000700A0
                geom_buf = ctypes.create_string_buffer(288)
                ok_geom = kernel32.DeviceIoControl(
                    ctypes.c_void_p(handle),
                    0x000700A0,
                    None,
                    0,
                    geom_buf,
                    288,
                    ctypes.byref(bytes_returned),
                    None,
                )
                det_sector = self.sector_size
                det_size = length_buf.value if ok_len else 0
                if ok_geom and bytes_returned.value >= 32:
                    raw = geom_buf.raw
                    bps = struct.unpack_from("<I", raw, 20)[0]
                    if bps in (512, 4096):
                        det_sector = bps
                    if det_size == 0:
                        det_size = struct.unpack_from("<Q", raw, 24)[0]
                if det_size > 0:
                    return det_size, det_sector
            except Exception:
                pass

        try:
            end_pos = os.lseek(self.fd, 0, os.SEEK_END)
            os.lseek(self.fd, 0, os.SEEK_SET)
            if end_pos > 0:
                return end_pos, self.sector_size
        except OSError:
            pass
        return 0, self.sector_size

    def read_at(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0 or length > 16 * 1024 * 1024:
            raise ValueError("Invalid or oversized read (maximum 16 MiB)")
        if offset >= self.size_bytes or length == 0:
            return b""
        length = min(length, self.size_bytes - offset)
        align = max(self.sector_size, 4096) if self.is_raw_device else self.sector_size
        aligned_start = (offset // align) * align
        prefix = offset - aligned_start
        aligned_len = ((prefix + length + align - 1) // align) * align
        try:
            os.lseek(self.fd, aligned_start, os.SEEK_SET)
            buf = os.read(self.fd, aligned_len)
        except OSError as error:
            raise OSError(f"Source read failed at byte {offset}: {error}") from error
        result = buf[prefix:prefix + length]
        if len(result) != length:
            raise OSError(f"Short read at byte {offset}: {len(result)}/{length}")
        return result

    def close(self) -> None:
        try:
            self.stream.close()
        except Exception:
            pass

    def __enter__(self) -> "AlignedDiskReader":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def classify_sector_pattern(data: bytes) -> dict[str, Any]:
    if not data:
        return {"pattern": "UNREADABLE_OR_EMPTY", "entropy": 0.0}
    total = len(data)
    z = data.count(0x00)
    f = data.count(0xFF)
    ent = shannon_entropy(data)
    if z == total:
        pattern = "ALL_ZERO_00"
    elif f == total:
        pattern = "ALL_FF"
    elif z + f == total:
        pattern = "MIXED_00_FF_ONLY"
    elif data[3:11] == b"-FVE-FS-":
        pattern = "BITLOCKER_ENCRYPTED_HEADER"
    elif data[:6] == b"LUKS\xba\xbe":
        pattern = "LUKS_ENCRYPTED_HEADER"
    elif ent >= 7.92 and data[510:512] != b"\x55\xaa":
        pattern = "HIGH_ENTROPY_ENCRYPTED_OR_COMPRESSED"
    else:
        pattern = "STRUCTURED_BINARY_DATA"
    return {
        "pattern": pattern,
        "entropy": ent,
        "zero_bytes": z,
        "ff_bytes": f,
        "non_fill_bytes": total - z - f,
    }


def decode_mbr(sector0: bytes, sector_size: int, disk_size_bytes: int) -> dict[str, Any]:
    if len(sector0) < 512:
        return {"valid": False, "error": "Sector 0 shorter than 512 bytes"}
    sig = struct.unpack_from("<H", sector0, 510)[0]
    valid_sig = sig == 0xAA55
    disk_sig = struct.unpack_from("<I", sector0, 0x1B8)[0]
    copy_prot = struct.unpack_from("<H", sector0, 0x1BC)[0]
    bootstrap = sector0[:446]

    if bootstrap == bytes(446):
        boot_code_kind = "EMPTY_BOOTSTRAP_CODE"
    elif b"Invalid partition table" in bootstrap or b"BOOTMGR" in bootstrap:
        boot_code_kind = "WINDOWS_STANDARD_MBR_BOOTCODE"
    elif b"GRUB" in bootstrap:
        boot_code_kind = "GRUB_BOOTLOADER_MBR"
    else:
        boot_code_kind = "CUSTOM_OR_OEM_BOOTCODE"

    partitions = []
    anomalies = []
    total_disk_sectors = disk_size_bytes // sector_size if disk_size_bytes > 0 else 0

    if not valid_sig:
        anomalies.append(f"INVALID_MBR_SIGNATURE: Expected 0xAA55 at offset 0x1FE, found 0x{sig:04X}")

    for idx in range(4):
        off = 446 + idx * 16
        entry = sector0[off:off + 16]
        status, chs_s0, chs_s1, chs_s2, ptype, chs_e0, chs_e1, chs_e2, lba_start, sector_count = struct.unpack(
            "<BBBBBBBBII", entry
        )
        if ptype == 0 and lba_start == 0 and sector_count == 0:
            continue
        p_bytes = sector_count * sector_size
        type_name = MBR_PARTITION_TYPES.get(ptype, f"Unknown/OEM (0x{ptype:02X})")
        part_info = {
            "slot": idx + 1,
            "entry_offset_hex": f"0x{off:03X}",
            "status_hex": f"0x{status:02X}",
            "bootable": status == 0x80,
            "partition_type_id": ptype,
            "partition_type_hex": f"0x{ptype:02X}",
            "partition_type_name": type_name,
            "lba_start": lba_start,
            "sector_count": sector_count,
            "end_lba_inclusive": lba_start + sector_count - 1 if sector_count > 0 else lba_start,
            "start_byte_offset": lba_start * sector_size,
            "size_bytes": p_bytes,
            "size_mib": round(p_bytes / (1024 * 1024), 2),
        }
        if status not in (0x00, 0x80):
            anomalies.append(f"SLOT_{idx+1}_INVALID_STATUS: Status byte is 0x{status:02X} (expected 0x00 or 0x80)")
        if ptype in (0x04, 0x06, 0x0E) and p_bytes > 4 * 1024**3:
            anomalies.append(
                f"SLOT_{idx+1}_FAT16_SIZE_MISMATCH_CANDIDATE: Type 0x{ptype:02X} ({type_name}) with "
                f"partition size {p_bytes:,} bytes; inspect BPB/cluster count before inferring filesystem or corruption."
            )
        if total_disk_sectors > 0 and ptype != 0xEE and (lba_start + sector_count > total_disk_sectors):
            anomalies.append(
                f"SLOT_{idx+1}_EXCEEDS_DISK_CAPACITY: Partition ends at LBA {lba_start + sector_count}, "
                f"exceeding disk total {total_disk_sectors} sectors."
            )
        partitions.append(part_info)

    is_gpt_protective = any(p["partition_type_id"] == 0xEE for p in partitions)
    return {
        "valid_signature": valid_sig,
        "signature_hex": f"0x{sig:04X}",
        "disk_signature_hex": f"0x{disk_sig:08X}",
        "copy_protected_field_hex": f"0x{copy_prot:04X}",
        "bootstrap_code_type": boot_code_kind,
        "bootstrap_entropy": shannon_entropy(bootstrap),
        "is_gpt_protective": is_gpt_protective,
        "partitions": partitions,
        "anomalies": anomalies,
    }


def decode_gpt_header_and_entries(
    reader: AlignedDiskReader, header_lba: int, label: str
) -> dict[str, Any]:
    ss = reader.sector_size
    raw_sector = reader.read_at(header_lba * ss, ss)
    if len(raw_sector) < 92:
        return {"present": False, "label": label, "lba": header_lba, "error": "Unreadable LBA"}
    sig = raw_sector[:8]
    if sig != b"EFI PART":
        return {"present": False, "label": label, "lba": header_lba, "signature_ascii": sig.decode("latin1", "replace")}

    rev, hdr_size, hdr_crc_stored, reserved, my_lba, alt_lba, first_usable, last_usable = struct.unpack_from(
        "<IIIIQQQQ", raw_sector, 8
    )
    disk_guid = format_guid_le(raw_sector[56:72])
    part_entry_lba, num_entries, entry_size, array_crc_stored = struct.unpack_from("<QIII", raw_sector, 72)

    bounded_hdr_size = min(max(hdr_size, 92), ss)
    hdr_for_crc = bytearray(raw_sector[:bounded_hdr_size])
    hdr_for_crc[16:20] = b"\x00\x00\x00\x00"
    hdr_crc_calc = binascii.crc32(hdr_for_crc) & 0xFFFFFFFF

    entries_info = []
    array_crc_calc = None
    array_crc_valid = False
    if 0 < num_entries <= 1024 and 128 <= entry_size <= 512 and ( entry_size % 8 == 0 ):
        total_array_bytes = num_entries * entry_size
        raw_array = reader.read_at(part_entry_lba * ss, total_array_bytes)
        if len(raw_array) == total_array_bytes:
            array_crc_calc = binascii.crc32(raw_array) & 0xFFFFFFFF
            array_crc_valid = array_crc_calc == array_crc_stored
            for idx in range(num_entries):
                ent = raw_array[idx * entry_size:(idx + 1) * entry_size]
                type_guid = format_guid_le(ent[0:16])
                if type_guid == "00000000-0000-0000-0000-000000000000":
                    continue
                uniq_guid = format_guid_le(ent[16:32])
                first_lba, last_lba, attrs = struct.unpack_from("<QQQ", ent, 32)
                name_utf16 = ent[56:128].decode("utf-16le", errors="replace").split("\x00", 1)[0]
                sec_cnt = (last_lba - first_lba + 1) if last_lba >= first_lba else 0
                entries_info.append(
                    {
                        "index": idx,
                        "type_guid": type_guid,
                        "type_name": GPT_TYPE_GUIDS.get(type_guid, "Custom / Vendor Partition Type"),
                        "unique_guid": uniq_guid,
                        "first_lba": first_lba,
                        "last_lba": last_lba,
                        "sector_count": sec_cnt,
                        "size_bytes": sec_cnt * ss,
                        "size_mib": round((sec_cnt * ss) / (1024 * 1024), 2),
                        "attributes_hex": f"0x{attrs:016X}",
                        "name": name_utf16,
                    }
                )

    return {
        "present": True,
        "label": label,
        "lba": header_lba,
        "revision_hex": f"0x{rev:08X}",
        "header_size": hdr_size,
        "header_crc32_stored_hex": f"0x{hdr_crc_stored:08X}",
        "header_crc32_calculated_hex": f"0x{hdr_crc_calc:08X}",
        "header_crc32_valid": 92 <= hdr_size <= ss and hdr_crc_stored == hdr_crc_calc,
        "geometry_valid": (0 < num_entries <= 1024 and entry_size in (128, 256, 512)
                           and my_lba == header_lba and 0 < alt_lba < reader.size_bytes // ss
                           and alt_lba != my_lba and 2 <= first_usable <= last_usable < reader.size_bytes // ss
                           and 0 < part_entry_lba and part_entry_lba * ss + num_entries * entry_size <= reader.size_bytes
                           and all(first_usable <= p["first_lba"] <= p["last_lba"] <= last_usable for p in entries_info)),
        "my_lba": my_lba,
        "alternate_lba": alt_lba,
        "first_usable_lba": first_usable,
        "last_usable_lba": last_usable,
        "disk_guid": disk_guid,
        "partition_entry_lba": part_entry_lba,
        "number_of_entries": num_entries,
        "size_of_entry": entry_size,
        "entry_array_crc32_stored_hex": f"0x{array_crc_stored:08X}",
        "entry_array_crc32_calculated_hex": f"0x{array_crc_calc:08X}" if array_crc_calc is not None else None,
        "entry_array_crc32_valid": array_crc_valid,
        "active_partitions": entries_info,
    }


def decode_vbr(reader: AlignedDiskReader, start_lba: int, partition_sectors: int | None = None) -> dict[str, Any]:
    ss = reader.sector_size
    base = start_lba * ss
    end = min(reader.size_bytes, base + partition_sectors * ss) if partition_sectors is not None else reader.size_bytes

    def read_region(offset, length):
        if offset < base or offset >= end or length > end - offset:
            return b""
        return reader.read_at(offset, length)

    sector0 = read_region(base, ss)
    if len(sector0) < 512:
        return {"start_lba": start_lba, "filesystem": "UNREADABLE", "valid": False}

    pattern_info = classify_sector_pattern(sector0)
    boot_sig = struct.unpack_from("<H", sector0, 510)[0]
    oem = sector0[3:11].decode("latin1", errors="replace")

    # 1. Check exFAT
    if sector0[3:11] == b"EXFAT   ":
        part_off, vol_len, fat_off, fat_len, heap_off, clust_cnt, root_dir, serial, fs_rev, vol_flags = struct.unpack_from(
            "<QQIIIIIIHH", sector0, 64
        )
        bps_shift, spc_shift, num_fats = struct.unpack_from("<BBB", sector0, 108)
        bps = 1 << bps_shift if 9 <= bps_shift <= 12 else 0
        spc = 1 << spc_shift if spc_shift <= 25 else 0
        main_12 = read_region(base, 12 * ss)
        backup_12 = read_region(base + 12 * ss, 12 * ss)
        main_checksum_valid = False
        calc_csum = None
        stored_csum = None
        if len(main_12) == 12 * ss:
            calc_csum = compute_exfat_boot_checksum(main_12[:11 * ss])
            stored_csum = struct.unpack_from("<I", main_12, 11 * ss)[0]
            main_checksum_valid = main_12[11 * ss:] == struct.pack("<I", calc_csum) * (ss // 4)
        backup_checksum_valid = False
        if len(backup_12) == 12 * ss:
            b_csum = compute_exfat_boot_checksum(backup_12[:11 * ss])
            backup_checksum_valid = (backup_12[3:11] == b"EXFAT   " and backup_12[510:512] == b"\x55\xaa"
                                     and backup_12[11 * ss:] == struct.pack("<I", b_csum) * (ss // 4))
        return {
            "start_lba": start_lba,
            "filesystem": "exFAT",
            "oem_id": oem,
            "boot_signature_hex": f"0x{boot_sig:04X}",
            "valid": (boot_sig == 0xAA55 and bps == ss and main_checksum_valid
                      and num_fats in (1, 2) and 0 < spc <= 65536 and fat_off >= 24 and fat_len > 0
                      and fat_off + fat_len * num_fats <= heap_off and 2 <= root_dir < clust_cnt + 2
                      and heap_off + clust_cnt * spc <= vol_len
                      and vol_len <= (partition_sectors or (reader.size_bytes - base) // ss)),
            "bytes_per_sector": bps,
            "sectors_per_cluster": spc,
            "cluster_size_bytes": bps * spc,
            "partition_offset_lba": part_off,
            "volume_length_sectors": vol_len,
            "fat_offset_sectors": fat_off,
            "fat_length_sectors": fat_len,
            "cluster_heap_offset_sectors": heap_off,
            "cluster_count": clust_cnt,
            "root_dir_first_cluster": root_dir,
            "volume_serial_hex": f"0x{serial:08X}",
            "number_of_fats": num_fats,
            "main_boot_checksum_calculated_hex": f"0x{calc_csum:08X}" if calc_csum is not None else None,
            "main_boot_checksum_stored_hex": f"0x{stored_csum:08X}" if stored_csum is not None else None,
            "main_boot_checksum_valid": main_checksum_valid,
            "backup_boot_region_valid": backup_checksum_valid,
            "pattern_info": pattern_info,
            "hex_preview": format_hex_dump(sector0, base, max_lines=8),
        }

    # 2. Check NTFS
    if sector0[3:11] == b"NTFS    ":
        bps, spc, reserved = struct.unpack_from("<HBH", sector0, 11)
        total_sectors64, mft_lcn, mftmirr_lcn = struct.unpack_from("<QQQ", sector0, 40)
        raw_c_per_mft = struct.unpack_from("<b", sector0, 64)[0]
        raw_c_per_idx = struct.unpack_from("<b", sector0, 68)[0]
        serial64 = struct.unpack_from("<Q", sector0, 72)[0]
        mft_record_size = (1 << (-raw_c_per_mft)) if raw_c_per_mft < 0 else (raw_c_per_mft * spc * bps)
        index_block_size = (1 << (-raw_c_per_idx)) if raw_c_per_idx < 0 else (raw_c_per_idx * spc * bps)

        # Inspect $MFT Record 0
        mft_info = {"present": False}
        if bps == ss and spc in (1, 2, 4, 8, 16, 32, 64, 128) and 512 <= mft_record_size <= 65536:
            mft_byte_off = base + mft_lcn * spc * bps
            mft0 = read_region(mft_byte_off, mft_record_size)
            if len(mft0) >= 48 and mft0[:4] in (b"FILE", b"BAAD"):
                usa_off, usa_count, lsn, seq_num, link_cnt, attr_off, flags, used_sz, alloc_sz = struct.unpack_from(
                    "<HHQHHHHII", mft0, 4
                )
                attrs = []
                usa_valid = (len(mft0) == mft_record_size and len(mft0) % ss == 0
                             and usa_count == len(mft0) // ss + 1 and usa_off >= 8
                             and usa_off + usa_count * 2 <= len(mft0))
                if usa_valid:
                    fixed = bytearray(mft0)
                    tag = mft0[usa_off:usa_off + 2]
                    for i in range(1, usa_count):
                        tail = i * ss - 2
                        if mft0[tail:tail + 2] != tag:
                            usa_valid = False
                            break
                        fixed[tail:tail + 2] = mft0[usa_off + i * 2:usa_off + i * 2 + 2]
                    if usa_valid:
                        mft0 = bytes(fixed)
                cur = attr_off
                while usa_valid and 48 <= cur <= min(used_sz, len(mft0)) - 8:
                    atype, alen = struct.unpack_from("<II", mft0, cur)
                    if atype == 0xFFFFFFFF or alen == 0 or cur + alen > len(mft0):
                        break
                    attrs.append(f"0x{atype:02X}")
                    cur += alen
                mft_info = {
                    "present": True,
                    "usa_fixup_valid": usa_valid,
                    "byte_offset": mft_byte_off,
                    "signature": mft0[:4].decode("latin1"),
                    "usa_offset": usa_off,
                    "usa_count": usa_count,
                    "sequence_number": seq_num,
                    "flags_hex": f"0x{flags:04X}",
                    "in_use": bool(flags & 0x01),
                    "is_directory": bool(flags & 0x02),
                    "attributes_found": attrs,
                }

        # Check NTFS Backup VBR
        backup_vbr_valid = False
        if total_sectors64 > 0:
            for cand_lba in (start_lba + total_sectors64, start_lba + total_sectors64 - 1):
                b_sec = read_region(cand_lba * ss, ss)
                if len(b_sec) >= 512 and b_sec[3:11] == b"NTFS    " and b_sec[510:512] == b"\x55\xaa":
                    backup_vbr_valid = True
                    break

        return {
            "start_lba": start_lba,
            "filesystem": "NTFS",
            "oem_id": oem,
            "boot_signature_hex": f"0x{boot_sig:04X}",
            "valid": (boot_sig == 0xAA55 and bps == ss and spc in (1, 2, 4, 8, 16, 32, 64, 128)
                      and 0 < total_sectors64 <= (partition_sectors or (reader.size_bytes - base) // ss)
                      and mft_lcn * spc < total_sectors64 and mftmirr_lcn * spc < total_sectors64),
            "bytes_per_sector": bps,
            "sectors_per_cluster": spc,
            "cluster_size_bytes": bps * spc,
            "total_sectors_64": total_sectors64,
            "mft_start_lcn": mft_lcn,
            "mftmirr_start_lcn": mftmirr_lcn,
            "mft_record_size_bytes": mft_record_size,
            "index_block_size_bytes": index_block_size,
            "volume_serial_hex": f"0x{serial64:016X}",
            "mft_record_0": mft_info,
            "backup_vbr_valid": backup_vbr_valid,
            "pattern_info": pattern_info,
            "hex_preview": format_hex_dump(sector0, base, max_lines=8),
        }

    # 3. Check FAT32 / FAT16
    bps, spc, reserved, fats, root_entries, total16, media, fat16_sz = struct.unpack_from("<HBHBHHBH", sector0, 11)
    total32 = struct.unpack_from("<I", sector0, 32)[0]
    fs_type_fat16 = sector0[54:62]
    fs_type_fat32 = sector0[82:90]
    if bps in (512, 4096) and spc in (1, 2, 4, 8, 16, 32, 64, 128) and fats in (1, 2) and reserved > 0:
        if fat16_sz == 0 and (fs_type_fat32.startswith(b"FAT32") or total32 > 0):
            fat32_sz, ext_flags, fs_ver, root_clus, fsinfo_sec, backup_boot_sec = struct.unpack_from(
                "<IHHIHH", sector0, 36
            )
            serial = struct.unpack_from("<I", sector0, 67)[0]
            label = sector0[71:82].decode("latin1", errors="replace").strip()
            backup_sec_data = read_region((start_lba + backup_boot_sec) * ss, ss) if backup_boot_sec > 0 else b""
            backup_matches = len(backup_sec_data) == ss and backup_sec_data == sector0
            fsinfo_data = read_region((start_lba + fsinfo_sec) * ss, ss) if fsinfo_sec > 0 else b""
            fsinfo_valid = (
                len(fsinfo_data) >= 512
                and fsinfo_data[0:4] == b"RRaA"
                and fsinfo_data[484:488] == b"rrAa"
                and fsinfo_data[508:512] == b"\x00\x00\x55\xaa"
            )
            free_clusters = struct.unpack_from("<I", fsinfo_data, 488)[0] if fsinfo_valid else None
            next_free = struct.unpack_from("<I", fsinfo_data, 492)[0] if fsinfo_valid else None
            return {
                "start_lba": start_lba,
                "filesystem": "FAT32",
                "oem_id": oem,
                "boot_signature_hex": f"0x{boot_sig:04X}",
                "valid": (boot_sig == 0xAA55 and bps == ss and fat32_sz > 0 and root_clus >= 2
                          and reserved + fats * fat32_sz < total32
                          and (root_clus - 2) * spc < total32 - reserved - fats * fat32_sz
                          and total32 <= (partition_sectors or (reader.size_bytes - base) // ss)),
                "bytes_per_sector": bps,
                "sectors_per_cluster": spc,
                "cluster_size_bytes": bps * spc,
                "reserved_sectors": reserved,
                "number_of_fats": fats,
                "total_sectors": total32,
                "sectors_per_fat": fat32_sz,
                "root_cluster": root_clus,
                "fsinfo_sector_offset": fsinfo_sec,
                "fsinfo_valid": fsinfo_valid,
                "fsinfo_free_clusters": free_clusters,
                "fsinfo_next_free_cluster": next_free,
                "backup_boot_sector_offset": backup_boot_sec,
                "backup_vbr_matches_primary": backup_matches,
                "volume_serial_hex": f"0x{serial:08X}",
                "volume_label": label,
                "pattern_info": pattern_info,
                "hex_preview": format_hex_dump(sector0, base, max_lines=8),
            }
        elif fat16_sz > 0 and root_entries > 0:
            total_sec = total16 if total16 > 0 else total32
            serial = struct.unpack_from("<I", sector0, 39)[0]
            label = sector0[43:54].decode("latin1", errors="replace").strip()
            return {
                "start_lba": start_lba,
                "filesystem": "FAT16",
                "oem_id": oem,
                "boot_signature_hex": f"0x{boot_sig:04X}",
                "valid": boot_sig == 0xAA55,
                "bytes_per_sector": bps,
                "sectors_per_cluster": spc,
                "reserved_sectors": reserved,
                "number_of_fats": fats,
                "root_entries": root_entries,
                "total_sectors": total_sec,
                "sectors_per_fat": fat16_sz,
                "volume_serial_hex": f"0x{serial:08X}",
                "volume_label": label,
                "pattern_info": pattern_info,
                "hex_preview": format_hex_dump(sector0, base, max_lines=8),
            }

    # 4. Check EXT4 Superblock at +1024 bytes from partition start
    ext_sb = read_region(base + 1024, 1024)
    if len(ext_sb) >= 264 and struct.unpack_from("<H", ext_sb, 56)[0] == 0xEF53:
        inodes_cnt, blocks_cnt_lo, r_blocks, free_blocks, free_inodes, first_data_blk, log_blk_sz = struct.unpack_from(
            "<IIIIIII", ext_sb, 0
        )
        block_size = 1024 << log_blk_sz if log_blk_sz <= 16 else 4096
        vol_name = ext_sb[120:136].decode("utf-8", errors="replace").split("\x00", 1)[0]
        uuid_hex = ext_sb[104:120].hex()
        return {
            "start_lba": start_lba,
            "filesystem": "EXT_FAMILY",
            "valid": False,
            "signature_present": True,
            "limitation": "0xEF53 is shared by ext2/3/4; checksum/features not validated",
            "superblock_magic_hex": "0xEF53",
            "inodes_count": inodes_cnt,
            "blocks_count_lo": blocks_cnt_lo,
            "block_size_bytes": block_size,
            "volume_name": vol_name,
            "uuid": uuid_hex,
            "pattern_info": classify_sector_pattern(ext_sb),
            "hex_preview": format_hex_dump(ext_sb[:256], base + 1024, max_lines=8),
        }

    # 5. Check Backup VBRs at +6 (FAT32) or +12 (exFAT) when Primary VBR at start_lba is wiped!
    backup_candidates = []
    sec_plus6 = read_region(base + 6 * ss, ss)
    if len(sec_plus6) >= 512 and sec_plus6[510:512] == b"\x55\xaa" and sec_plus6[82:87] == b"FAT32":
        backup_candidates.append(
            {
                "backup_type": "FAT32_BACKUP_VBR_AT_PLUS_6",
                "backup_lba": start_lba + 6,
                "candidate_only": f"Validate in native overlay before considering copy LBA {start_lba + 6} -> LBA {start_lba} to restore wiped FAT32 Primary VBR",
            }
        )
    sec_plus12 = read_region(base + 12 * ss, ss)
    if len(sec_plus12) >= 512 and sec_plus12[3:11] == b"EXFAT   " and sec_plus12[510:512] == b"\x55\xaa":
        backup_candidates.append(
            {
                "backup_type": "EXFAT_BACKUP_VBR_AT_PLUS_12",
                "backup_lba": start_lba + 12,
                "candidate_only": f"Validate in native overlay before considering copy 12 sectors from LBA {start_lba + 12} -> LBA {start_lba} to restore wiped exFAT Main Boot Region",
            }
        )
    if partition_sectors and partition_sectors > 16:
        for back_lba in (start_lba + partition_sectors - 1,):
            b_ntfs = read_region(back_lba * ss, ss)
            if len(b_ntfs) >= 512 and b_ntfs[3:11] == b"NTFS    " and b_ntfs[510:512] == b"\x55\xaa":
                backup_candidates.append(
                    {
                        "backup_type": "NTFS_BACKUP_VBR_AT_PARTITION_END",
                        "backup_lba": back_lba,
                        "candidate_only": f"Validate in native overlay before considering copy LBA {back_lba} -> LBA {start_lba} to restore wiped NTFS Primary VBR",
                    }
                )
                break

    return {
        "start_lba": start_lba,
        "filesystem": "RAW_OR_CORRUPTED_VBR",
        "oem_id": oem,
        "boot_signature_hex": f"0x{boot_sig:04X}",
        "valid": False,
        "backup_vbr_candidates": backup_candidates,
        "pattern_info": pattern_info,
        "hex_preview": format_hex_dump(sector0, base, max_lines=8),
    }


def inspect_disk_headers(target_path: str, sector_size: int = 512, extra_lbas: list[int] | None = None) -> dict[str, Any]:
    with AlignedDiskReader(target_path, sector_size=sector_size) as reader:
        ss = reader.sector_size
        total_bytes = reader.size_bytes
        total_sectors = total_bytes // ss if total_bytes > 0 else 0

        lba0 = reader.read_at(0, ss)
        lba0_pattern = classify_sector_pattern(lba0)
        mbr_info = decode_mbr(lba0, ss, total_bytes)

        primary_gpt = decode_gpt_header_and_entries(reader, 1, "PRIMARY_GPT")
        backup_gpt_lba = None
        if total_sectors > 34:
            backup_gpt_lba = total_sectors - 1

        backup_gpt = (
            decode_gpt_header_and_entries(reader, backup_gpt_lba, "BACKUP_GPT")
            if backup_gpt_lba is not None
            else {"present": False}
        )

        # Collect candidate partition LBAs to inspect for VBRs
        candidate_vbrs: dict[int, int | None] = {}
        for p in mbr_info.get("partitions", []):
            if p["partition_type_id"] != 0xEE and p["lba_start"] > 0:
                candidate_vbrs[p["lba_start"]] = p["sector_count"]
        for gpt_obj in (primary_gpt, backup_gpt):
            for gp in gpt_obj.get("active_partitions", []):
                if gp["first_lba"] > 0:
                    candidate_vbrs.setdefault(gp["first_lba"], gp["sector_count"])

        # Also check standard USB/SSD/HDD partition offsets (LBA 0 superfloppy, LBA 63 legacy, LBA 2048 1MiB aligned)
        for std_lba in (0, 63, 2048):
            if total_sectors == 0 or std_lba < total_sectors:
                candidate_vbrs.setdefault(std_lba, (total_sectors - std_lba) if total_sectors > std_lba else None)
        for custom_lba in extra_lbas or []:
            if custom_lba >= 0:
                candidate_vbrs.setdefault(custom_lba, None)

        vbr_reports = []
        for lba in sorted(candidate_vbrs):
            vbr = decode_vbr(reader, lba, candidate_vbrs[lba])
            # Keep LBA 0 only if it's actually a superfloppy VBR or if no partitions exist
            if lba == 0 and vbr["filesystem"] == "RAW_OR_CORRUPTED_VBR" and mbr_info.get("partitions"):
                continue
            vbr_reports.append(vbr)

        # Check for stuck buffer / controller readback anomalies across sampled LBAs
        sample_lbas = [lba for lba in (0, 1, 6, 12, 63, 2048, 4096) if total_sectors == 0 or lba < total_sectors]
        zero_samples = 0
        ff_samples = 0
        for slba in sample_lbas:
            sdata = reader.read_at(slba * ss, ss)
            pat = classify_sector_pattern(sdata)["pattern"]
            if pat == "ALL_ZERO_00":
                zero_samples += 1
            elif pat == "ALL_FF":
                ff_samples += 1

        recommendations = [
            "Header signatures/checksums are evidence only, not mountability or recovered content.",
            "Use native analyze_partition_recovery for validated overlay proposals; never patch source.",
        ]
        if sample_lbas and (zero_samples == len(sample_lbas) or ff_samples == len(sample_lbas)):
            recommendations.append("Sampled sectors contain only 00/FF; unsampled content and hardware cause remain unknown.")

        return {
            "operation": "inspect-headers",
            "validation_scope": "bounded header evidence; filesystem completeness not verified",
            "target_path": target_path,
            "is_raw_device": reader.is_raw_device,
            "sector_size": ss,
            "disk_size_bytes": total_bytes,
            "total_sectors": total_sectors,
            "lba0_pattern": lba0_pattern,
            "lba0_hex_dump": format_hex_dump(lba0, 0, max_lines=32),
            "mbr": mbr_info,
            "primary_gpt": primary_gpt,
            "backup_gpt": backup_gpt,
            "volume_boot_records": vbr_reports,
            "recommendations": recommendations,
        }


def dump_disk_headers(target_path: str, output_file: str, sector_size: int = 512, head_mib: int = 16) -> dict[str, Any]:
    """Safely captures the first N MiB of a raw disk or image into a binary dump file + SHA-256."""
    out_path = Path(output_file).resolve()
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing dump file: {out_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not 1 <= head_mib <= 16:
        raise ValueError("head_mib must be 1..16")
    max_bytes = head_mib * 1024 * 1024
    hasher = hashlib.sha256()
    written = 0

    with AlignedDiskReader(target_path, sector_size=sector_size) as reader:
        if reader.is_raw_device:
            raise ValueError("Raw-device dump destination isolation is not implemented; acquire an image first")
        to_read = min(max_bytes, reader.size_bytes) if reader.size_bytes > 0 else max_bytes
        chunk_sz = 1024 * 1024
        with out_path.open("xb") as out_stream:
            while written < to_read:
                step = min(chunk_sz, to_read - written)
                data = reader.read_at(written, step)
                if len(data) != step:
                    raise OSError("Incomplete header dump; partial output retained")
                out_stream.write(data)
                hasher.update(data)
                written += len(data)
            out_stream.flush()
            os.fsync(out_stream.fileno())

    return {
        "operation": "dump-headers",
        "source": target_path,
        "output_file": str(out_path),
        "bytes_dumped": written,
        "sha256": hasher.hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    insp = sub.add_parser("inspect", help="Read and decode binary MBR, GPT, and VBR headers from a disk or image")
    insp.add_argument("target", help="Path to disk image (.img/.bin) or raw device (\\\\.\\PhysicalDrive1, D:, /dev/sdX)")
    insp.add_argument("--sector-size", type=int, choices=(512, 4096), default=512)
    insp.add_argument("--lba", type=int, action="append", default=[], help="Additional LBA(s) to inspect for VBR/Superblock")
    insp.add_argument("--report", help="Optional path to save full JSON report")

    dmp = sub.add_parser("dump-headers", help="Extract the first N MiB of binary disk headers to an offline file")
    dmp.add_argument("target", help="Source raw device or image")
    dmp.add_argument("--output", required=True, help="Destination .img/.bin file")
    dmp.add_argument("--sector-size", type=int, choices=(512, 4096), default=512)
    dmp.add_argument("--head-mib", type=int, default=16, help="MiB from start of disk to capture (default: 16)")

    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect_disk_headers(args.target, sector_size=args.sector_size, extra_lbas=args.lba)
            if args.report:
                rep_path = Path(args.report).resolve()
                if rep_path.exists():
                    raise FileExistsError(f"Report already exists: {rep_path}")
                rep_path.parent.mkdir(parents=True, exist_ok=True)
                with rep_path.open("x", encoding="utf-8") as report:
                    report.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        else:
            result = dump_disk_headers(args.target, args.output, sector_size=args.sector_size, head_mib=args.head_mib)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
