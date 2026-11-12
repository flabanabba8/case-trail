"""Maintainer review: read_opinion must not reach /proc, /sys, /dev, the Hermes home or key stores, and can be limited to folders the owner lists."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('case_trail_review', ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(spec); sys.modules[spec.name] = plugin; spec.loader.exec_module(plugin)
core = plugin.core


class Refusals(unittest.TestCase):
    def setUp(self):
        core.set_allowed_roots(())
        self.addCleanup(core.set_allowed_roots, ())

    def test_kernel_and_device_views_are_refused_including_through_proc_self(self):
        for path in ('/pro' + 'c/sel' + 'f/environ', '/pro' + 'c/sel' + 'f/cmdline', '/proc/cpuinfo', '/sys/kernel/hostname', '/dev/null'):
            if not os.path.exists(path): continue
            with self.assertRaises(ValueError, msg=path):
                core.read_opinion(path)

    def test_the_hermes_home_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / 'hermes-home'; home.mkdir(); f = home / 'opinion.txt'; f.write_text('text')
            fake = type(sys)('hermes_constants'); fake.get_hermes_home = lambda: str(home)
            with patch.dict(sys.modules, {'hermes_constants': fake}):
                with self.assertRaisesRegex(ValueError, 'Hermes home'):
                    core.read_opinion(str(f))

    def test_auth_json_and_the_extra_private_folders_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / 'auth.json').write_text('{}')
            for folder in ('.claude', '.gemini', '.mozilla'):
                (base / folder).mkdir(); (base / folder / 'op.txt').write_text('x')
            (base / '.local/share/keyrings').mkdir(parents=True); (base / '.local/share/keyrings/login.keyring').write_text('x')
            for rel in ('auth.json', '.claude/op.txt', '.gemini/op.txt', '.mozilla/op.txt', '.local/share/keyrings/login.keyring'):
                with self.assertRaises(ValueError, msg=rel):
                    core.read_opinion(str(base / rel))

    def test_an_ordinary_opinion_file_still_reads(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'opinion.txt'; f.write_text('The judgment is affirmed.')
            self.assertEqual(core.read_opinion(str(f)), 'The judgment is affirmed.')


class OwnerFolders(unittest.TestCase):
    def tearDown(self): core.set_allowed_roots(())

    def test_when_the_owner_lists_folders_only_those_are_readable(self):
        with tempfile.TemporaryDirectory() as d:
            ok = Path(d) / 'cases'; ok.mkdir(); other = Path(d) / 'elsewhere'; other.mkdir()
            (ok / 'a.txt').write_text('a'); (other / 'b.txt').write_text('b')
            core.set_allowed_roots([str(ok)])
            self.assertEqual(core.read_opinion(str(ok / 'a.txt')), 'a')
            with self.assertRaisesRegex(ValueError, 'opinion_folders'):
                core.read_opinion(str(other / 'b.txt'))

    def test_the_setting_comes_from_plugin_config_not_tool_arguments(self):
        class Ctx:
            def __init__(self, cfg): self.cfg = cfg
            def get_config(self, key, default=None): return self.cfg.get(key, default)
        with tempfile.TemporaryDirectory() as d:
            ok = Path(d) / 'cases'; ok.mkdir(); other = Path(d) / 'x'; other.mkdir(); (other / 'b.txt').write_text('b'); (ok / 'a.txt').write_text('a')
            out = json.loads(plugin.invoke('caselaw_examine_source_file', {'source_label': 'S', 'source_path': str(other / 'b.txt'), 'identifiers': ['1 U.S. 1']}, Ctx({'opinion_folders': json.dumps([str(ok)])})))
            self.assertIn('opinion_folders', out.get('error', ''))

    def test_the_manifest_declares_the_setting(self):
        self.assertIn('opinion_folders', (ROOT / 'plugin.yaml').read_text())


if __name__ == '__main__':
    unittest.main()
