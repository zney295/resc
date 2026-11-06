#!/usr/bin/env python3
"""Read-only audits of regular image files, never physical/volume device paths.

Streaming SHA-256, 00/FF counts, bounded sector maps and byte-exact comparisons.
An image hash confirms the read image view, not the USB's original contents.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

MAX_CHUNK = 16 * 1024 * 1024
MAX_RUNS = 128


def identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class Image:
    def __init__(self, path):
        raw = os.fspath(path)
        if raw.startswith(("\\\\.\\", "\\\\?\\")):
            raise ValueError("Raw/volume device paths are not accepted; acquire an image first")
        self.path = Path(raw).absolute()
        before = self.path.lstat()
        if not stat.S_ISREG(before.st_mode) or getattr(before, 'st_file_attributes', 0) & 0x400:
            raise ValueError("Expected a regular image, not a device, symlink or reparse point")
        descriptor = os.open(self.path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
        self.stream = os.fdopen(descriptor, 'rb', buffering=0)
        self.before = self.stream.fileno()
        info = os.fstat(self.before)
        if not stat.S_ISREG(info.st_mode) or identity(before) != identity(info):
            self.stream.close()
            raise ValueError("Image identity changed while opening")
        self.snapshot = identity(info)
        self.size = info.st_size

    def unchanged(self):
        try:
            return self.snapshot == identity(os.fstat(self.before)) == identity(self.path.lstat())
        except OSError:
            return False

    def close(self):
        self.stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class Runs:
    """Exact total run count, bounded examples; omitted runs are explicit."""
    def __init__(self, limit):
        if not 1 <= limit <= MAX_RUNS:
            raise ValueError(f"run-limit must be 1..{MAX_RUNS}")
        self.limit, self.total, self.last_end, self.examples = limit, 0, None, []

    def add(self, start, length):
        if start == self.last_end:
            if self.total <= self.limit:
                self.examples[-1]['length'] += length
        else:
            self.total += 1
            if self.total <= self.limit:
                self.examples.append({'start': start, 'length': length})
        self.last_end = start + length

    def report(self, unit):
        return {'unit': unit, 'runs_total': self.total, 'examples': self.examples,
                'omitted_runs': self.total - len(self.examples), 'truncated': self.total > self.limit}


def window(size, offset, length, max_bytes):
    if offset < 0 or offset > size or (length is not None and length <= 0):
        raise ValueError("Invalid offset/length")
    requested = size - offset if length is None else length
    if offset + requested > size:
        raise ValueError("Requested window exceeds image capacity")
    if max_bytes is not None and max_bytes <= 0:
        raise ValueError("max-bytes must be positive")
    return requested, min(requested, max_bytes) if max_bytes is not None else requested


def validate_chunk(chunk_size, sector_size=1):
    if not sector_size <= chunk_size <= MAX_CHUNK or chunk_size % sector_size:
        raise ValueError("chunk-size must be a sector multiple, at least one sector, at most 16 MiB")


def audit(path, sector_size=512, chunk_size=1024 * 1024, offset=0,
          length=None, max_bytes=None, run_limit=64, expected_sha256=None):
    if sector_size not in (512, 4096) or offset % sector_size:
        raise ValueError("Use 512/4096-byte sectors and a sector-aligned offset")
    validate_chunk(chunk_size, sector_size)
    runs = Runs(run_limit)
    if expected_sha256 is not None and not re.fullmatch(r'[0-9a-fA-F]{64}', expected_sha256):
        raise ValueError("Expected SHA-256 must be 64 hex digits")
    with Image(path) as image:
        requested, budget = window(image.size, offset, length, max_bytes)
        image.stream.seek(offset)
        sha = hashlib.sha256()
        read = zero = ff = 0
        sectors = {'all_zero': 0, 'all_ff': 0, 'mixed_00_ff_only': 0, 'contains_other_bytes': 0}
        partial_sector = 0
        error = None
        while read < budget:
            count = min(chunk_size, budget - read)
            try:
                block = image.stream.read(count)
            except OSError as failure:
                error = str(failure)
                break
            sha.update(block)
            zero += block.count(0)
            ff += block.count(255)
            for at in range(0, len(block), sector_size):
                sector = block[at:at + sector_size]
                zeros, ones = sector.count(0), sector.count(255)
                has_other = zeros + ones < len(sector)
                if has_other:
                    runs.add((offset + read + at) // sector_size, 1)
                if len(sector) != sector_size:
                    partial_sector = len(sector)
                else:
                    key = ('contains_other_bytes' if has_other else 'all_zero' if zeros == len(sector)
                           else 'all_ff' if ones == len(sector) else 'mixed_00_ff_only')
                    sectors[key] += 1
            read += len(block)
            if len(block) != count:
                error = 'Unexpected EOF before recorded image capacity'
                break
        stable = image.unchanged()
        complete = read == requested and stable and error is None
        full = complete and offset == 0 and requested == image.size
        status = ('SOURCE_CHANGED' if not stable else 'READ_ERROR' if error else
                  'EMPTY_IMAGE' if image.size == 0 else 'COMPLETED' if complete else 'PARTIAL')
        digest = sha.hexdigest()
        return {'schema_version': 1, 'operation': 'audit', 'status': status,
                'source': str(image.path), 'image_size_bytes': image.size,
                'source_metadata_unchanged': stable, 'sector_size': sector_size,
                'geometry_aligned': image.size % sector_size == 0,
                'coverage': {'offset_bytes': offset, 'requested_bytes': requested,
                             'read_bytes': read, 'whole_image_read': full},
                'sha256': digest if full and image.size > 0 else None,
                'read_range_sha256': digest,
                'expected_sha256': expected_sha256,
                'expected_sha256_matches': digest.lower() == expected_sha256.lower()
                    if expected_sha256 and full and image.size > 0 else None,
                'byte_counts': {'00': zero, 'ff': ff, 'other': read - zero - ff},
                'fill_fraction_of_read_bytes': (zero + ff) / read if read else None,
                'complete_sector_counts': sectors, 'partial_sector_bytes': partial_sector,
                'non_fill_sector_runs': runs.report('source LBA containing observed non-00/FF bytes'),
                'read_error': error,
                'limitations': ['Image bytes only; not a physical-device reader or persistence test',
                    '00/FF does not establish TRIM, overwrite, empty media or NAND/controller failure',
                    'Unresolved acquisition-map regions remain unknown, including zero-filled ones',
                    'No original file payload, format validity or recoverability is established']}


def compare(left_path, right_path, chunk_size=1024 * 1024, offset=0,
            length=None, max_bytes=None, run_limit=64):
    validate_chunk(chunk_size)
    runs = Runs(run_limit)
    with Image(left_path) as left, Image(right_path) as right:
        requested, budget = window(min(left.size, right.size), offset, length, max_bytes)
        left.stream.seek(offset)
        right.stream.seek(offset)
        read = different = 0
        left_hash, right_hash = hashlib.sha256(), hashlib.sha256()
        error = None
        while read < budget:
            count = min(chunk_size, budget - read)
            try:
                a, b = left.stream.read(count), right.stream.read(count)
            except OSError as failure:
                error = str(failure)
                break
            if len(a) != count or len(b) != count:
                error = 'Unexpected EOF before recorded image capacity'
                break
            left_hash.update(a)
            right_hash.update(b)
            if a != b:
                for position, (one, two) in enumerate(zip(a, b)):
                    if one != two:
                        different += 1
                        runs.add(offset + read + position, 1)
            read += count
        stable = left.unchanged() and right.unchanged()
        complete = read == requested and stable and error is None
        same_window = different == 0 if complete else None
        whole = complete and offset == 0 and requested == left.size == right.size
        files_equal = same_window if whole else False if left.size != right.size else None
        return {'schema_version': 1, 'operation': 'compare',
                'status': 'SOURCE_CHANGED' if not stable else 'READ_ERROR' if error else
                          'COMPLETED' if complete else 'PARTIAL',
                'left': str(left.path), 'right': str(right.path),
                'left_size_bytes': left.size, 'right_size_bytes': right.size,
                'length_difference_bytes': abs(left.size - right.size),
                'source_metadata_unchanged': stable,
                'coverage': {'offset_bytes': offset, 'requested_bytes': requested,
                             'compared_bytes': read, 'both_whole_images_read': whole},
                'compared_range_equal': same_window, 'whole_images_equal': files_equal,
                'differing_bytes_in_compared_range': different,
                'left_read_range_sha256': left_hash.hexdigest(),
                'right_read_range_sha256': right_hash.hexdigest(),
                'differing_byte_runs': runs.report('absolute source byte'), 'read_error': error,
                'limitations': ['Compares stored images; no direct physical re-read or cache bypass',
                    'Agreement does not identify the correct reader or prove persistence after reconnect',
                    'A sampled window is not a whole-image comparison']}


def exit_code(report):
    if report['status'] in ('READ_ERROR', 'SOURCE_CHANGED'):
        return 1
    if (report['status'] != 'COMPLETED' or report.get('expected_sha256_matches') is False
            or (report.get('expected_sha256') and report.get('expected_sha256_matches') is not True)):
        return 2
    if report.get('operation') == 'compare' and (
            report['compared_range_equal'] is False or report['whole_images_equal'] is False):
        return 2
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('audit', 'compare'):
        p = commands.add_parser(command)
        if command == 'audit':
            p.add_argument('path')
            p.add_argument('--sector-size', type=int, choices=(512, 4096), default=512)
            p.add_argument('--expected-sha256')
        else:
            p.add_argument('left_path')
            p.add_argument('right_path')
        p.add_argument('--offset', type=int, default=0)
        p.add_argument('--length', type=int)
        p.add_argument('--max-bytes', type=int)
        p.add_argument('--chunk-size', type=int, default=1024 * 1024)
        p.add_argument('--run-limit', type=int, default=64)
        p.add_argument('--report', required=True, help='New JSON file; never overwritten')
    args = vars(parser.parse_args(argv))
    command, destination = args.pop('command'), Path(args.pop('report'))
    # Refuse an existing destination before a costly image read. Exclusive create
    # below also covers a link/path race, without ever truncating source evidence.
    if os.path.lexists(destination):
        raise ValueError('Report already exists; choose a new path')
    report = audit(**args) if command == 'audit' else compare(**args)
    with destination.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'operation': command, 'status': report['status'],
        'report': str(destination.resolve()), 'coverage': report['coverage'],
        'whole_images_equal': report.get('whole_images_equal'),
        'expected_sha256_matches': report.get('expected_sha256_matches')}, ensure_ascii=False))
    return exit_code(report)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
