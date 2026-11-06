import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('justia_case_research', ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)


class Context:
    def __init__(self): self.calls = []
    def dispatch_tool(self, name, args, **kwargs):
        self.calls.append((name, args, kwargs))
        return json.dumps({'success': True, 'data': {'web': [
            {'url': 'https://law.justia.com/cases/test/appeal.html'},
            {'url': 'https://law.justia.com.evil.invalid/cases/test'},
        ]}})


class ResearchTests(unittest.TestCase):
    def test_search_filters_domains_and_forwards_context(self):
        ctx = Context()
        result = json.loads(plugin.invoke('justia_search', {'case': 'Smith v Jones', 'citation': '100 U.S. 1', 'jurisdiction_hint': 'Georgia', 'issue_hint': 'evidence', 'query_type': 'appeal history'}, ctx, session_id='s'))
        self.assertEqual(len(result['results']), 1)
        self.assertEqual(ctx.calls[0][2]['session_id'], 's')
        self.assertIn('citing cases', result['query_types_available'])
        self.assertIn('appeal parties', result['query_types_available'])
        self.assertIn('"Georgia"', result['query'])
        self.assertIn('"evidence"', result['query'])
        self.assertEqual(result['query_type_executed'], 'appeal history')
        self.assertIn('not checked', result['coverage'])
        self.assertIn('incomplete', result['notice'])

    def test_examine_is_not_a_disposition(self):
        result = plugin.core.examine('https://law.justia.com/cases/test/', 'Smith, 100 U.S. 1 was cited. In another case the court reversed.', ['100 U.S. 1'])
        self.assertEqual(result['status'], 'unverified leads')
        self.assertIn('reversed', result['matches'][0]['cues'])
        self.assertFalse(plugin.core.valid_url('https://law.justia.com@evil.invalid/cases/test'))

    def test_outcome_passage_can_be_far_from_citation(self):
        text = 'Smith, 100 U.S. 1. ' + ('Unrelated discussion. ' * 100) + 'The judgment is reversed in part.'
        result = plugin.core.examine('https://law.justia.com/cases/test/', text, ['100 U.S. 1'])
        self.assertFalse(result['matches'][0]['cues'])
        self.assertEqual(len(result['outcome_cues']), 1)
        self.assertIn('reversed in part', result['outcome_cues'][0]['excerpt'])
        self.assertEqual(result['status'], 'unverified leads')

    def test_repeated_mentions_report_truncated_results(self):
        result = plugin.core.examine('https://law.justia.com/cases/test/', 'Smith ' * 30, ['Smith'])
        self.assertEqual(len(result['matches']), 20)
        self.assertEqual(result['truncated_identifiers'], ['Smith'])

    def test_reporter_abbreviation_spacing(self):
        result = plugin.core.examine('https://law.justia.com/cases/test/', 'Cites 410 U. S. 113.', ['410 U.S. 113'])
        self.assertEqual(len(result['matches']), 1)

    def test_party_query_preserves_apostrophes(self):
        plans = dict(plugin.core.terms("Jackson Women's Health Organization v Dobbs", '', ''))
        self.assertIn('"Jackson Women\'s Health Organization"', plans['appeal parties'])
        self.assertIn('"Dobbs"', plans['appeal parties'])
        self.assertTrue(plugin.core.may_be_index('https://law.justia.com/cases/georgia/supreme-court/2019/'))

    def test_extract_failure_is_not_a_success(self):
        class Failed:
            def dispatch_tool(self, *args, **kwargs): return json.dumps({'success': False, 'error': 'unavailable'})
        result = json.loads(plugin.invoke('justia_fetch', {'url': 'https://law.justia.com/cases/test/'}, Failed()))
        self.assertEqual(result['error'], 'Extraction provider failed')

    def test_malformed_search_is_not_reported_as_zero_hits(self):
        class Malformed:
            def dispatch_tool(self, *args, **kwargs): return json.dumps({'success': True, 'data': {}})
        result = json.loads(plugin.invoke('justia_search', {'case': 'Smith', 'query_type': 'appeal history'}, Malformed()))
        self.assertIn('error', result)
        class Raised:
            def dispatch_tool(self, *args, **kwargs): raise RuntimeError('private provider details')
        result = json.loads(plugin.invoke('justia_search', {'case': 'Smith', 'query_type': 'appeal history'}, Raised()))
        self.assertIn('incomplete', result['error'])
        self.assertNotIn('private provider details', str(result))

    def test_extract_reports_different_returned_case_url(self):
        class Extracted:
            def dispatch_tool(self, *args, **kwargs):
                return json.dumps({'results': [{'url': 'https://law.justia.com/cases/other', 'content': 'opinion'}]})
        result = json.loads(plugin.invoke('justia_fetch', {'url': 'https://law.justia.com/cases/requested'}, Extracted()))
        self.assertTrue(result['returned_url_differs'])

    def test_examine_local_file_and_reject_symlink(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
            path = Path(tmp) / 'opinion.txt'
            path.write_text('The opinion cites 100 U.S. 1 and discusses a reversal.')
            args = {'url': 'https://law.justia.com/cases/test/', 'source_path': str(path), 'identifiers': ['100 U.S. 1']}
            result = json.loads(plugin.invoke('justia_examine_file', args, Context()))
            self.assertEqual(len(result['matches']), 1)
            symlink = Path(tmp) / 'alias.txt'
            symlink.symlink_to(path)
            result = json.loads(plugin.invoke('justia_examine_file', {**args, 'source_path': str(symlink)}, Context()))
            self.assertIn('error', result)
            env_file = Path(tmp) / '.env'
            env_file.write_text('fixture')
            result = json.loads(plugin.invoke('justia_examine_file', {**args, 'source_path': str(env_file)}, Context()))
            self.assertIn('error', result)
            key_file = Path(tmp) / 'signing.p12'
            key_file.write_text('fixture')
            self.assertIn('error', json.loads(plugin.invoke('justia_examine_file', {**args, 'source_path': str(key_file)}, Context())))

    def test_replaced_opinion_during_read_is_rejected(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
            source, replacement = Path(tmp)/'opinion.txt', Path(tmp)/'replacement.txt'
            source.write_text('Original opinion'); replacement.write_text('Replacement opinion')
            fstat = plugin.core.os.fstat
            calls = 0
            def replace_during_read(fd):
                nonlocal calls
                calls += 1
                result = fstat(fd)
                if calls == 2: plugin.core.os.replace(replacement, source)
                return result
            with patch.object(plugin.core.os, 'fstat', side_effect=replace_during_read):
                with self.assertRaisesRegex(ValueError, 'replaced during reading'):
                    plugin.core.read_opinion(str(source))

    def test_review_requires_exact_both_sides_and_direct_history(self):
        target = {'url': 'https://law.justia.com/cases/test/a', 'text': 'Original court decision.'}
        later = {'url': 'https://law.justia.com/cases/test/b', 'text': 'The judgment is reversed in part.'}
        evidence = [{'source': 'target', 'start': 0, 'end': 8, 'quote': 'Original'}, {'source': 'later', 'start': 0, 'end': 12, 'quote': 'The judgment'}]
        args = dict(target=target, later=later, evidence=evidence, relation='direct-history', treatment='reversed', extent='part', opinion_role='majority', proposition='A disputed legal rule', target_court='Trial court', later_court='Appeals court', authority_analysis='Appeals court reviews the trial judgment.', identity_rationale='Same parties and docket.', outcome='Partly reversed.', analysis='Same case on appeal.', contrary='Other grounds remain.', limitations=['Search coverage incomplete.'])
        result = plugin.core.review(**args)
        self.assertIn('proposed', result['status'])
        with self.assertRaises(ValueError): plugin.core.review(**{**args, 'relation': 'later-treatment'})
        with self.assertRaises(ValueError): plugin.core.review(**{**args, 'opinion_role': 'dissent'})
        with self.assertRaises(ValueError): plugin.core.review(**{**args, 'opinion_role': 'unknown'})
        with self.assertRaises(ValueError): plugin.core.review(**{**args, 'evidence': [evidence[0], {**evidence[1], 'quote': 'invented'}]})
        with self.assertRaises(ValueError): plugin.core.review(**{**args, 'limitations': ['x' * 1001]})
        with self.assertRaises(ValueError): plugin.core.review(**{**args, 'relation': 'later-treatment', 'treatment': 'overruled', 'opinion_role': 'dissent'})
        with self.assertRaisesRegex(ValueError, 'predates'):
            plugin.core.review(**args, target_date='2020-01-02', later_date='2019-01-02')
        self.assertIn('unverified', result['chronology'])
        self.assertEqual(result['reviewer_kind'], 'unspecified')
        self.assertEqual(result['read_scope'], 'unspecified')

    def test_review_of_local_files_validates_offsets(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
            target = Path(tmp) / 'target.txt'
            later = Path(tmp) / 'later.txt'
            target.write_text('Original court decision.')
            later.write_text('The judgment is reversed in part.')
            args = dict(target={'url': 'https://law.justia.com/cases/test/a', 'source_path': str(target)}, later={'url': 'https://law.justia.com/cases/test/b', 'source_path': str(later)}, evidence=[{'source': 'target', 'start': 0, 'end': 8, 'quote': 'Original'}, {'source': 'later', 'start': 0, 'end': 12, 'quote': 'The judgment'}], relation='direct-history', treatment='reversed', extent='part', opinion_role='majority', proposition='A legal rule', target_court='Trial court', later_court='Appeals court', authority_analysis='Appeals court reviews trial judgment', identity_rationale='Same case on appeal', outcome='Partly reversed', analysis='Matching appeal.', contrary='Other grounds remain.', limitations=['Search incomplete'])
            result = json.loads(plugin.invoke('justia_review', args, Context()))
            self.assertIn('proposed', result['status'])
            later.write_text('Changed opinion text.')
            self.assertIn('error', json.loads(plugin.invoke('justia_review', args, Context())))

    def test_private_review_receipts_detect_changes(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
            store = plugin.Reviews(Path(tmp) / 'receipts')
            review = {'relation': 'direct-history', 'treatment': 'reversed', 'status': 'proposed', 'analysis': 'private analysis'}
            ident = store.save(review)
            path = store.path(ident)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(store.get(ident)['review'], review)
            self.assertNotIn('private analysis', str(store.list()))
            path.write_text(path.read_text().replace('private analysis', 'modified analysis'))
            with self.assertRaisesRegex(ValueError, 'fingerprint mismatch'): store.get(ident)
            self.assertEqual(store.list()['unreadable_records'], 1)
            path.write_text('x' * (128 * 1024 + 1))
            with self.assertRaisesRegex(ValueError, 'too large'): store.get(ident)


if __name__ == '__main__': unittest.main()
