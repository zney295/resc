"""Evidence semantics on synthetic regular images; no USB or raw-device access."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('evidence_audit', ROOT / 'scripts/evidence_audit.py')
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class ReadProxy:
    def __init__(self, stream, action):
        self.stream, self.action, self.calls = stream, action, 0

    def read(self, size):
        self.calls += 1
        return self.action(self.stream, size, self.calls)

    def seek(self, offset):
        return self.stream.seek(offset)

    def close(self):
        self.stream.close()


class EvidenceAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='resc-evidence-')
        self.root = Path(self.temp.name)
        self.source = self.root / 'original.img'
        self.payload = bytes(range(256)) * 8
        self.source.write_bytes(self.payload)

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(), self.payload)
        self.temp.cleanup()

    def image(self, name, payload):
        path = self.root / name
        path.write_bytes(payload)
        return path

    def inject_reads(self, action):
        original = audit.Image.__init__
        def initialize(instance, path):
            original(instance, path)
            instance.stream = ReadProxy(instance.stream, action)
        return patch.object(audit.Image, '__init__', initialize)

    def test_fill_counts_and_partial_sector_are_exact(self):
        path = self.image('fill.img', bytes(512) + bytes([255])*512 + b'\x00\xff'*256 + b'abc')
        report = audit.audit(path, chunk_size=512)
        self.assertEqual(report['byte_counts'], {'00': 768, 'ff': 768, 'other': 3})
        self.assertEqual(report['complete_sector_counts'], {
            'all_zero': 1, 'all_ff': 1, 'mixed_00_ff_only': 1, 'contains_other_bytes': 0})
        self.assertEqual(report['partial_sector_bytes'], 3)
        self.assertFalse(report['geometry_aligned'])
        self.assertEqual(report['non_fill_sector_runs']['examples'], [{'start': 3, 'length': 1}])
        self.assertEqual(report['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_nonfill_sector_run_merges_across_chunks(self):
        path = self.image('runs.img', bytes(512) + b'a'*1024 + bytes(512) + b'b'*512)
        report = audit.audit(path, chunk_size=512)
        self.assertEqual(report['non_fill_sector_runs']['examples'], [
            {'start': 1, 'length': 2}, {'start': 4, 'length': 1}])

    def test_truncated_run_examples_still_count_all_runs(self):
        path = self.image('many.img', (b'a'*512 + bytes(512))*10)
        report = audit.audit(path, chunk_size=512, run_limit=2)
        runs = report['non_fill_sector_runs']
        self.assertEqual(runs['runs_total'], 10)
        self.assertEqual(runs['omitted_runs'], 8)
        self.assertEqual(len(runs['examples']), 2)
        self.assertTrue(runs['truncated'])
        self.assertEqual(report['byte_counts']['other'], 5120)

    def test_expected_full_image_hash_matches_case_insensitively(self):
        digest = hashlib.sha256(self.payload).hexdigest()
        report = audit.audit(self.source, expected_sha256=digest.upper())
        self.assertTrue(report['expected_sha256_matches'])
        self.assertEqual(audit.exit_code(report), 0)

    def test_expected_hash_mismatch_is_not_success(self):
        report = audit.audit(self.source, expected_sha256='0'*64)
        self.assertFalse(report['expected_sha256_matches'])
        self.assertEqual(audit.exit_code(report), 2)

    def test_budgeted_prefix_does_not_claim_whole_image_hash(self):
        report = audit.audit(self.source, max_bytes=512,
                             expected_sha256=hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(report['status'], 'PARTIAL')
        self.assertEqual(report['coverage']['read_bytes'], 512)
        self.assertFalse(report['coverage']['whole_image_read'])
        self.assertIsNone(report['sha256'])
        self.assertIsNone(report['expected_sha256_matches'])
        self.assertEqual(report['read_range_sha256'], hashlib.sha256(self.payload[:512]).hexdigest())
        self.assertEqual(audit.exit_code(report), 2)

    def test_completed_sample_is_not_expected_whole_hash_verification(self):
        report = audit.audit(self.source, offset=512, length=512,
                             expected_sha256=hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(report['status'], 'COMPLETED')
        self.assertIsNone(report['sha256'])
        self.assertIsNone(report['expected_sha256_matches'])
        self.assertEqual(audit.exit_code(report), 2)

    def test_empty_image_is_not_acquisition_success(self):
        path = self.image('empty.img', b'')
        report = audit.audit(path)
        self.assertEqual(report['status'], 'EMPTY_IMAGE')
        self.assertIsNone(report['sha256'])
        self.assertIsNone(report['fill_fraction_of_read_bytes'])
        self.assertEqual(audit.exit_code(report), 2)

    def test_audit_io_error_keeps_only_real_prefix_without_zero_fill(self):
        def fail(stream, size, call):
            if call == 2:
                raise OSError('injected read failure')
            return stream.read(size)
        with self.inject_reads(fail):
            report = audit.audit(self.source, chunk_size=512)
        self.assertEqual(report['status'], 'READ_ERROR')
        self.assertEqual(report['coverage']['read_bytes'], 512)
        self.assertEqual(sum(report['byte_counts'].values()), 512)
        self.assertIsNone(report['sha256'])
        self.assertEqual(audit.exit_code(report), 1)

    def test_short_read_is_explicit_and_not_promoted_to_full_hash(self):
        with self.inject_reads(lambda stream, size, _: stream.read(size//2)):
            report = audit.audit(self.source, chunk_size=512)
        self.assertEqual(report['status'], 'READ_ERROR')
        self.assertEqual(report['coverage']['read_bytes'], 256)
        self.assertEqual(report['partial_sector_bytes'], 256)
        self.assertIsNone(report['sha256'])

    def test_path_replacement_detected_even_if_bytes_are_identical(self):
        replacement = self.image('replacement.img', self.payload)
        def replace(stream, size, call):
            data = stream.read(size)
            if call == 1:
                replacement.replace(self.source)
            return data
        if os.name == 'nt':
            self.skipTest('Windows shared-file rename semantics differ; metadata-change path covered separately')
        with self.inject_reads(replace):
            report = audit.audit(self.source, chunk_size=512)
        self.assertEqual(report['status'], 'SOURCE_CHANGED')
        self.assertFalse(report['source_metadata_unchanged'])
        self.assertIsNone(report['sha256'])

    def test_metadata_change_invalidates_full_verification(self):
        with patch.object(audit.Image, 'unchanged', return_value=False):
            report = audit.audit(self.source)
        self.assertEqual(report['status'], 'SOURCE_CHANGED')
        self.assertEqual(audit.exit_code(report), 1)

    def test_compare_whole_identical_images(self):
        other = self.image('copy.img', self.payload)
        report = audit.compare(self.source, other, chunk_size=513)
        self.assertTrue(report['whole_images_equal'])
        self.assertTrue(report['compared_range_equal'])
        self.assertEqual(report['differing_bytes_in_compared_range'], 0)

    def test_compare_byte_run_crosses_chunk_boundary(self):
        changed = bytearray(self.payload)
        for position in [511, 512, 513]:
            changed[position] ^= 0xff
        report = audit.compare(self.source, self.image('changed.img', changed), chunk_size=512)
        self.assertFalse(report['whole_images_equal'])
        self.assertEqual(report['differing_bytes_in_compared_range'], 3)
        self.assertEqual(report['differing_byte_runs']['examples'], [{'start': 511, 'length': 3}])
        self.assertEqual(audit.exit_code(report), 2)

    def test_compare_difference_examples_bounded_but_totals_exact(self):
        changed = bytearray(self.payload)
        for position in range(1, 32, 2):
            changed[position] ^= 0xff
        report = audit.compare(self.source, self.image('different.img', changed), run_limit=1)
        self.assertEqual(report['differing_bytes_in_compared_range'], 16)
        self.assertEqual(report['differing_byte_runs']['runs_total'], 16)
        self.assertEqual(report['differing_byte_runs']['omitted_runs'], 15)

    def test_compare_size_difference_kept_separate_from_compared_bytes(self):
        report = audit.compare(self.source, self.image('longer.img', self.payload + b'extra'))
        self.assertFalse(report['whole_images_equal'])
        self.assertTrue(report['compared_range_equal'])
        self.assertEqual(report['length_difference_bytes'], 5)
        self.assertEqual(report['differing_bytes_in_compared_range'], 0)
        self.assertEqual(audit.exit_code(report), 2)

    def test_equal_sample_does_not_hide_differences_outside_window(self):
        changed = bytearray(self.payload)
        changed[1024] ^= 0xff
        report = audit.compare(self.source, self.image('outside.img', changed), offset=1, length=511)
        self.assertTrue(report['compared_range_equal'])
        self.assertIsNone(report['whole_images_equal'])
        self.assertFalse(report['coverage']['both_whole_images_read'])

    def test_agreeing_budgeted_prefix_is_not_complete_comparison(self):
        report = audit.compare(self.source, self.source, max_bytes=512)
        self.assertEqual(report['status'], 'PARTIAL')
        self.assertIsNone(report['whole_images_equal'])
        self.assertIsNone(report['compared_range_equal'])
        self.assertEqual(audit.exit_code(report), 2)

    def test_compare_read_failure_does_not_claim_equality(self):
        def fail(stream, size, call):
            if call == 2:
                raise OSError('injected')
            return stream.read(size)
        with self.inject_reads(fail):
            report = audit.compare(self.source, self.source, chunk_size=512)
        self.assertEqual(report['status'], 'READ_ERROR')
        self.assertEqual(report['coverage']['compared_bytes'], 512)
        self.assertIsNone(report['whole_images_equal'])

    def test_sparse_image_offset_above_two_gibibytes(self):
        offset = 1 << 31
        a, b = self.root / 'large-a.img', self.root / 'large-b.img'
        for path in (a, b):
            with path.open('wb') as stream:
                stream.seek(offset)
                stream.write(b'a'*512)
        report = audit.audit(a, offset=offset, length=512, chunk_size=512)
        self.assertEqual(report['coverage']['read_bytes'], 512)
        self.assertEqual(report['non_fill_sector_runs']['examples'], [{'start': offset//512, 'length': 1}])
        self.assertIsNone(report['sha256'])
        compared = audit.compare(a, b, offset=offset+2, length=10)
        self.assertTrue(compared['compared_range_equal'])
        self.assertIsNone(compared['whole_images_equal'])

    def test_four_kn_geometry_and_end_window(self):
        path = self.image('4kn.img', bytes(4096) + b'x'*4096 + bytes([255])*4096)
        report = audit.audit(path, sector_size=4096, offset=8192, length=4096, chunk_size=4096)
        self.assertEqual(report['complete_sector_counts']['all_ff'], 1)
        self.assertEqual(report['coverage']['read_bytes'], 4096)

    def test_unsafe_device_paths_rejected_without_open(self):
        for path in [r'\\.\PhysicalDrive1', r'\\?\GLOBALROOT\Device\Harddisk0', r'\\.\D:']:
            with patch.object(audit.os, 'open', side_effect=AssertionError('opened device')):
                with self.assertRaises(ValueError):
                    audit.audit(path)
        if os.name != 'nt':
            with patch.object(audit.os, 'open', side_effect=AssertionError('opened device')):
                with self.assertRaises(ValueError):
                    audit.audit('/dev/null')

    def test_symlink_not_accepted_as_source(self):
        link = self.root / 'source-link.img'
        try:
            link.symlink_to(self.source)
        except OSError:
            self.skipTest('Symlinks unavailable')
        with self.assertRaises(ValueError):
            audit.audit(link)

    def test_bad_bounds_and_budgets_rejected(self):
        for options in [dict(offset=-512), dict(offset=1), dict(length=4096),
                        dict(max_bytes=0), dict(chunk_size=513), dict(run_limit=129),
                        dict(expected_sha256='not a hash'), dict(expected_sha256='')]:
            with self.assertRaises(ValueError):
                audit.audit(self.source, **options)
        with self.assertRaises(ValueError):
            audit.compare(self.source, self.source, length=4096)

    def test_cli_new_report_summary_and_no_overwrite(self):
        source = self.image('ảnh nguồn có dấu.img', self.payload)
        report_path = self.root / 'report.json'
        command = [sys.executable, str(ROOT/'scripts/evidence_audit.py'), 'audit', str(source), '--report', str(report_path)]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        self.assertLess(len(result.stdout.encode()), 4096)
        self.assertEqual(json.loads(result.stdout)['status'], 'COMPLETED')
        self.assertEqual(json.loads(report_path.read_text())['sha256'], hashlib.sha256(self.payload).hexdigest())
        saved = report_path.read_bytes()
        with patch.object(audit, 'audit', side_effect=AssertionError('read existing report')):
            with self.assertRaises(ValueError):
                audit.main(['audit', str(source), '--report', str(report_path)])
        self.assertEqual(report_path.read_bytes(), saved)

    def test_report_cannot_overwrite_source_or_source_hardlink(self):
        for destination in [self.source, self.image('existing.json', b'keep')]:
            with self.assertRaises(ValueError):
                audit.main(['audit', str(self.source), '--report', str(destination)])
        alias = self.root / 'hardlink.json'
        try:
            os.link(self.source, alias)
        except OSError:
            self.skipTest('Hardlinks unavailable')
        with self.assertRaises(ValueError):
            audit.main(['audit', str(self.source), '--report', str(alias)])


if __name__ == '__main__':
    unittest.main(verbosity=2)
