"""Verify MBR and filesystem persistence from three read-only USB captures."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import struct


def require(condition, message):
    if not condition:
        raise ValueError(message)


def regular(path):
    require(path.is_file(), f"Expected a regular file: {path}")
    stream = path.open("rb")
    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
        stream.close()
        raise ValueError(f"Expected a regular file: {path}")
    return stream


def integer(data, offset, length):
    return int.from_bytes(data[offset:offset + length], "little")


def read_at(stream, offset, size):
    stream.seek(offset)
    data = stream.read(size)
    require(len(data) == size, "Capture is truncated")
    return data


def fat32(stream, boot, base, sector_size, partition_sectors):
    bps, spc, reserved, fats = struct.unpack_from("<HBHB", boot, 11)
    total, fat_size = struct.unpack_from("<II", boot, 32)
    backup = integer(boot, 50, 2)
    root = integer(boot, 44, 4)
    first_data = reserved + fats * fat_size
    require(bps == sector_size and spc in (1, 2, 4, 8, 16, 32, 64, 128)
            and 0 < reserved and fats in (1, 2) and fat_size > 0
            and first_data < total <= partition_sectors
            and integer(boot, 17, 2) == integer(boot, 19, 2) == integer(boot, 22, 2) == 0,
            "Invalid FAT32 BPB")
    clusters = (total - first_data) // spc
    require(65525 <= clusters <= 0x0FFFFFEE and 2 <= root < clusters + 2
            and fat_size * sector_size >= (clusters + 2) * 4,
            "Invalid FAT32 cluster geometry")
    require(0 < backup < reserved
            and read_at(stream, base + backup * sector_size, sector_size) == boot,
            "FAT32 backup boot sector differs")
    return hashlib.sha256(boot).hexdigest()


def exfat(stream, boot, base, sector_size, partition_start, partition_sectors):
    total = integer(boot, 72, 8)
    fat_offset, fat_length, heap, clusters, root = struct.unpack_from("<IIIII", boot, 80)
    sector_shift, cluster_shift, fats = boot[108:111]
    require(boot[3:11] == b"EXFAT   " and boot[11:64] == bytes(53)
            and integer(boot, 64, 8) == partition_start
            and 24 <= fat_offset and fat_length > 0 and fats in (1, 2)
            and fat_offset + fat_length * fats <= heap
            and sector_shift == sector_size.bit_length() - 1 and cluster_shift <= 25 - sector_shift
            and 0 < clusters <= 0xFFFFFFF5 and 2 <= root < clusters + 2
            and fat_length * sector_size >= (clusters + 2) * 4
            and 1024**2 // sector_size <= total <= partition_sectors
            and heap < total and clusters == min((total - heap) >> cluster_shift, 0xFFFFFFF5),
            "Invalid exFAT boot geometry")
    regions = []
    for index in (0, 12):
        region = bytearray(read_at(stream, base + index * sector_size, sector_size * 12))
        require(region[510:512] == b"\x55\xaa", "Invalid exFAT boot signature")
        for extended in range(1, 9):
            end = (extended + 1) * sector_size
            require(region[end - 4:end] == b"\0\0\x55\xaa", "Invalid exFAT extended boot signature")
        # VolumeFlags and PercentInUse are mutable and excluded from the checksum.
        checksum = 0
        for offset, byte in enumerate(region[:11 * sector_size]):
            if offset not in (106, 107, 112):
                checksum = (((checksum << 31) | (checksum >> 1)) + byte) & 0xFFFFFFFF
        require(region[11 * sector_size:] == struct.pack("<I", checksum) * (sector_size // 4),
                "Invalid exFAT boot checksum")
        for offset in (106, 107, 112):
            region[offset] = 0
        regions.append(region)
    require(regions[0] == regions[1], "exFAT main and backup boot regions differ")
    return hashlib.sha256(regions[0]).hexdigest()


def layout(stream, size, sector_size, filesystem):
    mbr = read_at(stream, 0, sector_size)
    require(mbr[510:512] == b"\x55\xaa", "Invalid MBR signature")
    entries = [mbr[i:i + 16] for i in range(446, 510, 16)]
    used = [entry for entry in entries if any(entry)]
    require(len(used) == 1, "Expected one primary MBR partition")
    entry = used[0]
    start, count = struct.unpack_from("<II", entry, 8)
    base = start * sector_size
    allowed = (0x07,) if filesystem == "exfat" else (0x0B, 0x0C)
    require(entry[0] in (0, 0x80) and entry[4] in allowed and base == 1024**2
            and count > 0 and (start + count) * sector_size <= size,
            "Unexpected MBR partition type, alignment or bounds")
    boot = read_at(stream, base, sector_size)
    require(boot[510:512] == b"\x55\xaa", "Invalid boot signature")
    if filesystem == "exfat":
        require(count >= 24, "Partition cannot contain both exFAT boot regions")
        boot_hash = exfat(stream, boot, base, sector_size, start, count)
    else:
        boot_hash = fat32(stream, boot, base, sector_size, count)
    return {"mbr_sha256": hashlib.sha256(mbr).hexdigest(), "boot_sha256": boot_hash,
            "partition_start_lba": start, "partition_sectors": count, "partition_type": entry[4]}


def canary_hash(stream):
    digest = hashlib.sha256()
    length = 0
    while block := stream.read(1024**2):
        require(0 not in block and 255 not in block, "Canary contains 00 or FF bytes")
        digest.update(block)
        length += len(block)
    require(length > 0, "Canary is empty")
    return digest.hexdigest()


def verify(images, canaries, expected_hash, sector_size, filesystem):
    from contextlib import ExitStack
    require(sector_size in (512, 4096) and filesystem in ("exfat", "fat32"), "Invalid geometry options")
    require(len(expected_hash) == 64 and all(c in "0123456789abcdef" for c in expected_hash),
            "Expected a SHA-256 hex digest")
    with ExitStack() as stack:
        t0, t1, t2, c1, c2 = [stack.enter_context(regular(path)) for path in (*images, *canaries)]
        stats = [os.fstat(stream.fileno()) for stream in (t0, t1, t2, c1, c2)]
        require(len({(info.st_dev, info.st_ino) for info in stats}) == len(stats),
                "Provide distinct capture and canary files")
        size = stats[0].st_size
        require(size >= sector_size and size % sector_size == 0 and
                all(info.st_size == size for info in stats[:3]), "Capture geometry differs")
        initial_mbr = read_at(t0, 0, sector_size)
        first = layout(t1, size, sector_size, filesystem)
        second = layout(t2, size, sector_size, filesystem)
        require(first == second, "T1 and T2 partition or boot metadata differ")
        require(canary_hash(c1) == expected_hash, "T1 canary hash differs")
        require(canary_hash(c2) == expected_hash, "T2 canary hash differs")
        for stream, before in zip((t0, t1, t2, c1, c2), stats):
            after = os.fstat(stream.fileno())
            require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
                    "Capture or canary changed during verification")
        return {"status": "PERSISTENCE_VERIFIED_FOR_CAPTURES", "filesystem": filesystem,
                "sector_size": sector_size, "size_bytes": size, "t0_mbr_sha256": hashlib.sha256(initial_mbr).hexdigest(),
                "t1_t2_layout": second, "canary_sha256": expected_hash,
                "limitations": ["Reconnect and capture provenance are operator-attested.",
                                "Separate canary observations are not bound to filesystem extents in the captures."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for stage in ("t0", "t1", "t2", "canary-t1", "canary-t2"):
        parser.add_argument(f"--{stage}", type=Path, required=True)
    parser.add_argument("--canary-sha256", required=True)
    parser.add_argument("--sector-size", type=int, choices=(512, 4096), default=512)
    parser.add_argument("--filesystem", choices=("exfat", "fat32"), required=True)
    args = parser.parse_args()
    try:
        result = verify((args.t0, args.t1, args.t2), (args.canary_t1, args.canary_t2),
                        args.canary_sha256.lower(), args.sector_size, args.filesystem)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Verification failed: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
