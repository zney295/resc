"""Local skill contracts: metadata, reference paths and executable MCP examples.

This is a repository check, not an official third-party skill certification.
"""
import json
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / '.agents/skills'
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'scripts'))
import setup_clients as setup


def validate_example(value, schema, path='arguments'):
    expected = schema.get('type')
    types = {'object': dict, 'array': list, 'string': str, 'boolean': bool,
             'integer': int, 'number': (int, float)}
    if expected:
        if not isinstance(value, types[expected]) or (expected in ('integer', 'number') and isinstance(value, bool)):
            raise AssertionError(f'{path}: expected {expected}')
    if 'enum' in schema and value not in schema['enum']:
        raise AssertionError(f'{path}: unexpected enum {value}')
    if isinstance(value, dict):
        properties = schema.get('properties', {})
        missing = set(schema.get('required', [])) - value.keys()
        if missing:
            raise AssertionError(f'{path}: missing {missing}')
        if schema.get('additionalProperties') is False and value.keys() - properties.keys():
            raise AssertionError(f'{path}: unknown arguments {value.keys() - properties.keys()}')
        for key, item in value.items():
            if key in properties:
                validate_example(item, properties[key], path+'.'+key)
    elif isinstance(value, list):
        if len(value) < schema.get('minItems', 0) or len(value) > schema.get('maxItems', float('inf')):
            raise AssertionError(f'{path}: array size out of bounds')
        for item in value:
            validate_example(item, schema.get('items', {}), path+'[]')
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get('minimum', float('-inf')) or value > schema.get('maximum', float('inf')):
            raise AssertionError(f'{path}: numeric bounds')


class RecoverySkillContracts(unittest.TestCase):
    def test_skill_entry_metadata(self):
        entries = sorted(SKILLS.glob('*/SKILL.md'))
        self.assertGreaterEqual(len(entries), 5)
        for path in entries:
            with self.subTest(skill=path.parent.name):
                text = path.read_text(encoding='utf-8')
                self.assertTrue(text.startswith('---\n'))
                header = text.split('---', 2)[1]
                self.assertRegex(header, r'\nname: [a-z][a-z0-9-]{0,63}\n')
                self.assertRegex(header, r'\ndescription: \S[^\n]+\n')

    def test_local_markdown_links_resolve_inside_repository(self):
        checked = 0
        for path in SKILLS.rglob('*.md'):
            for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
                uri = urlsplit(target)
                if uri.scheme or uri.netloc or not uri.path:
                    continue
                resolved = (path.parent / unquote(uri.path)).resolve()
                with self.subTest(file=str(path.relative_to(ROOT)), target=target):
                    self.assertTrue(resolved.is_relative_to(ROOT), 'Link escapes repository')
                    self.assertTrue(resolved.is_file(), 'Missing local reference')
                checked += 1
        self.assertGreater(checked, 40)

    def test_mcp_examples_match_catalog(self):
        tools = {t['name']: t['inputSchema'] for t in json.loads(
            (ROOT/'ai-context/tool-catalog.json').read_text(encoding='utf-8'))['tools']}
        decoder = json.JSONDecoder()
        checked = 0
        for path in SKILLS.rglob('*.md'):
            blocks = re.findall(r'```json\s*\n(.*?)\n```', path.read_text(encoding='utf-8'), re.S)
            for block in blocks:
                remaining = block.strip()
                while remaining:
                    example, end = decoder.raw_decode(remaining)
                    remaining = remaining[end:].lstrip()
                    if isinstance(example, dict) and 'name' in example and 'arguments' in example:
                        with self.subTest(file=str(path.relative_to(ROOT)), tool=example['name']):
                            self.assertIn(example['name'], tools)
                            validate_example(example['arguments'], tools[example['name']])
                        checked += 1
        self.assertGreaterEqual(checked, 4)


class RecoverySkillsTest(unittest.TestCase):
    def test_versioned_skills_and_links(self):
        for name in setup.SKILLS:
            folder = setup.PROJECT / ".agents/skills" / name
            text = (folder / "SKILL.md").read_text(encoding="utf-8")
            skill_name = "disk-forensics-and-recovery" if name == "disk-forensics" else name
            self.assertIn(f"\nname: {skill_name}\n", text)
            self.assertIn('version: "4.1"', text)

    def test_install_preserves_other_config_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = root / ".codex/config.toml"
            antigravity = root / ".gemini/config/mcp_config.json"
            codex.parent.mkdir()
            antigravity.parent.mkdir(parents=True)
            original = '# user comment\n[mcp_servers.other]\ncommand = "other"\n'
            codex.write_bytes(original.encode())
            antigravity.write_text('{"keep":true,"mcpServers":{"other":{"command":"other"}}}', encoding="utf-8")
            server = {"command": "node", "args": ["resc-mcp.js"]}
            changes = setup.plan(root, "both", server)
            self.assertFalse((root / ".agents").exists())
            setup.publish(changes)
            self.assertTrue(codex.read_text(encoding="utf-8").startswith(original))
            self.assertEqual(tomllib.loads(codex.read_text())["mcp_servers"]["resc"]["tool_timeout_sec"], 120)
            config = json.loads(antigravity.read_text(encoding="utf-8"))
            self.assertTrue(config["keep"])
            self.assertEqual(config["mcpServers"]["other"], {"command": "other"})
            self.assertEqual(config["mcpServers"]["resc"], server)
            self.assertEqual(setup.plan(root, "both", server), [])
            self.assertEqual(len(list(codex.parent.glob("config.toml.backup.*"))), 1)
            self.assertTrue((root / ".gemini/config/skills/recovery-triage/references"
                             / "rea-binary-and-ioctl-analysis.md").is_file())
            installed = root / ".gemini/config/skills/recovery-triage/SKILL.md"
            self.assertIn((ROOT / "docs/engine-capabilities.md").as_uri(),
                          installed.read_text(encoding="utf-8"))
            new_server = {"command": "other-node", "args": ["resc-mcp.js"]}
            setup.publish(setup.plan(root, "both", new_server))
            self.assertEqual(setup.plan(root, "both", new_server), [])

    def test_rollback_and_concurrent_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "first", root / "second"
            first.write_bytes(b"old")
            second.write_bytes(b"original")
            changes = [setup.Change(first, setup.snapshot(first), b"updated"),
                       setup.Change(second, setup.snapshot(second), b"replacement")]
            second.write_bytes(b"edited concurrently")
            with self.assertRaisesRegex(ValueError, "Destination changed"):
                setup.publish(changes)
            self.assertEqual(first.read_bytes(), b"old")
            self.assertEqual(second.read_bytes(), b"edited concurrently")
            self.assertEqual(list(root.glob(".resc-*")), [])
            self.assertEqual(next(root.glob("first.backup.*")).read_bytes(), b"old")

    def test_readback_failure_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "new"
            original = setup.snapshot
            calls = 0

            def snapshot(target):
                nonlocal calls
                result = original(target)
                if target == path and result:
                    calls += 1
                    if calls == 1:
                        return setup.Snapshot(b"bad readback", result.mode, result.identity, result.mtime)
                return result

            with patch.object(setup, "snapshot", side_effect=snapshot):
                with self.assertRaisesRegex(ValueError, "Readback failed"):
                    setup.publish([setup.Change(path, None, b"new")])
            self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
