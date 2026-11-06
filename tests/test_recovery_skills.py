"""Local skill contracts: metadata, reference paths and executable MCP examples.

This is a repository check, not an official third-party skill certification.
"""
import json
from pathlib import Path
import re
import unittest
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / '.agents/skills'


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


if __name__ == '__main__':
    unittest.main(verbosity=2)
