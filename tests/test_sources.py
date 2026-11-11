import hashlib,json,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
import test_research as fixture
plugin=fixture.plugin;core=plugin.core

def proposal():
    a='Fictional original opinion: the parties must receive written notice before the hearing.'
    b='Fictional later opinion: We reverse the order because the required written notice was not given.'
    quotes=[('target',a,'must receive written notice'),('later',b,'We reverse the order')]
    return {'target':{'label':'Original fictional opinion','text':a},'later':{'label':'Later fictional opinion','text':b},
        'evidence':[{'source':role,'quote':q,'start':text.index(q),'end':text.index(q)+len(q)}for role,text,q in quotes],
        'relation':'direct-history','treatment':'reversed','extent':'part','opinion_role':'majority',
        'proposition':'The fictional hearing requires notice.','target_court':'Fictional trial court','later_court':'Fictional review court',
        'authority_analysis':'Explicit synthetic review relationship; no actual court authority claimed.',
        'identity_rationale':'The supplied fictional texts describe the same fictional order.',
        'outcome':'The supplied fictional later text says the order was reversed.',
        'analysis':'Review the complete example texts and exact passages; this is a fixture.',
        'contrary':'No actual legal status or wider search has been established.',
        'limitations':['Synthetic opinions, not legal advice or a current case-status conclusion.'],
        'reviewer_kind':'assistant','read_scope':'full-opinions'}

class SuppliedSourceTests(unittest.TestCase):
    def test_any_supplied_source_without_fabricating_a_justia_url(self):
        result=core.examine_source('Local fictional opinion','Harbour Club v Oak Council. The order is reversed.',['Harbour Club v Oak Council'])
        self.assertIsNone(result['url']);self.assertEqual(result['source_label'],'Local fictional opinion');self.assertTrue(result['matches']);self.assertEqual(result['status'],'unverified leads')
        remote=core.examine_source('Selected public source','Harbour Club v Oak Council.',['Harbour Club'],source_url='https://example.org/opinion')
        self.assertEqual(remote['url'],'https://example.org/opinion');self.assertIn('not authenticated',remote['text_origin_verification'])
        with self.assertRaises(ValueError):core.examine('https://example.org/opinion','Harbour Club.',['Harbour Club'])
        for url in ['file:///tmp/opinion.txt','https://reader:test-only@example.org/opinion','https://example.org/opinion?private=x']:
            with self.assertRaises(ValueError):core.examine_source('Source','Opinion.',['Opinion'],source_url=url)
    def test_provider_neutral_review_keeps_exact_evidence_and_authority_rules(self):
        args=proposal();result=core.review_sources(**args);self.assertEqual(result['sources'][0]['label'],args['target']['label']);self.assertIsNone(result['sources'][0]['url']);self.assertIn('not independently reviewed',result['status'])
        args['relation']='later-treatment'
        with self.assertRaisesRegex(ValueError,'same-litigation'):core.review_sources(**args)
        args=proposal();args['evidence'][0]['quote']='Invented quotation'
        with self.assertRaisesRegex(ValueError,'exact quoted'):core.review_sources(**args)
    def test_decision_dates_must_appear_in_their_own_source_file(self):
        args=proposal()
        args['target']['text']+=' Decided December 18, 1967.';args['target_date']='1967-12-18'
        self.assertEqual(core.review_sources(**args)['target_date'],'1967-12-18')       # stated in the file: accepted
        args=proposal();args['later_date']='1966-10-11'
        with self.assertRaisesRegex(ValueError,'does not appear in that source file'):core.review_sources(**args)   # not in the file: refused
        args=proposal();self.assertIsNone(core.review_sources(**args)['target_date'])    # omitted: fine
    def test_saved_review_renders_readably_with_quotes_places_limits_and_escaping(self):
        from case_trail import render
        args=proposal();args['evidence']=[{'source':'target','anchor':'must receive written notice'},{'source':'later','anchor':'We reverse the order'}]
        review=core.review_sources(**args);review['analysis']='It <b>reads</b> & decides.'
        text=render.markdown(review);page=render.html_page(review)
        for needle in ('The answer','The exact words relied on','must receive written notice','We reverse the order','Limits','characters '):self.assertIn(needle,text)
        review2={**review,'target_court':'United States Court of Appeals for the Ninth Circuit','proposition':'Disposition in Katz v. United States, 369 F.2d 130.'}
        self.assertEqual(render.sections(review2)['title'],'What happened to the Ninth Circuit ruling in Katz v. United States')
        self.assertIn('&lt;b&gt;reads&lt;/b&gt; &amp; decides.',page);self.assertNotIn('<b>reads</b>',page);self.assertIn('<blockquote>',page)
        with tempfile.TemporaryDirectory()as tmp:
            path=Path(render.write(tmp,'a'*32,review,'html'));self.assertTrue(path.is_file());self.assertEqual(oct(path.stat().st_mode)[-3:],'600')
            with self.assertRaises(ValueError):render.write(tmp,'a'*32,review,'pdf')
    def test_cite_by_anchor_or_location_without_retyping_and_guards_stay(self):
        args=proposal();args['evidence']=[{'source':'target','anchor':'must receive written notice'},{'source':'later','start':args['later']['text'].index('We reverse'),'end':args['later']['text'].index('We reverse')+len('We reverse the order')}]
        result=core.review_sources(**args)
        self.assertEqual([e['quote'] for e in result['evidence']],['must receive written notice','We reverse the order'])
        self.assertEqual(result['evidence'][0]['start'],args['target']['text'].index('must receive'))
        for bad,pattern in [({'source':'target','anchor':'text that is absent'},'not found'),({'source':'target','anchor':'the'*3},'not found'),({'source':'later','anchor':'order'+' '*0},'8-500'),({'source':'later','start':0,'end':9999},'location citation')]:
            args=proposal();args['evidence'][0]=bad
            with self.assertRaisesRegex(ValueError,pattern):core.review_sources(**args)
        args=proposal();args['target']['text']+=' '+args['target']['text'];args['evidence'][0]={'source':'target','anchor':'must receive written notice'}
        with self.assertRaisesRegex(ValueError,'more than once'):core.review_sources(**args)
    def test_anchor_matches_across_line_breaks_and_source_label_alias(self):
        args=proposal();args['later']['text']=args['later']['text'].replace('We reverse the order','We reverse\nthe  order')
        args['evidence']=[{'source':'target','anchor':'must receive written notice'},{'source':'later','anchor':'We reverse the order'}]
        result=core.review_sources(**args);self.assertEqual(result['evidence'][1]['quote'],'We reverse\nthe  order')
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);args=proposal();args['evidence']=[{'source':'target','anchor':'must receive written notice'},{'source':'later','anchor':'We reverse the order'}]
            for role in ['target','later']:
                path=root/(role+'.txt');path.write_text(args[role].pop('text'));args[role]={'source_label':args[role]['label'],'source_path':str(path)}
            storage=types.ModuleType('plugins.plugin_storage');storage.plugin_data_dir=lambda name:root/'private-reviews'
            with patch.dict(sys.modules,{'plugins':types.ModuleType('plugins'),'plugins.plugin_storage':storage}):
                result=json.loads(plugin.invoke('caselaw_review_sources',{**args,'save':True},fixture.Context()))
            self.assertNotIn('error',result,result);self.assertTrue(result['review_id'])
    def test_missing_anchor_error_shows_closest_exact_passage(self):
        args=proposal();args['evidence'][0]={'source':'target','anchor':'the parties shall receive written notice before hearing'}
        with self.assertRaisesRegex(ValueError,'Closest passage.*must receive written notice before the hearing'):core.review_sources(**args)
    def test_native_file_interface_and_saved_source_continuity(self):
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);args=proposal();paths={}
            for role in ['target','later']:
                path=root/(role+'.txt');path.write_text(args[role].pop('text'));args[role]['source_path']=str(path);paths[role]=path
            storage=types.ModuleType('plugins.plugin_storage');storage.plugin_data_dir=lambda name:root/'private-reviews'
            with patch.dict(sys.modules,{'plugins':types.ModuleType('plugins'),'plugins.plugin_storage':storage}):
                examined=json.loads(plugin.invoke('caselaw_examine_source_file',{'source_label':'Original fixture','source_path':str(paths['target']),'identifiers':['written notice']},fixture.Context()));self.assertTrue(examined['matches'])
                saved=json.loads(plugin.invoke('caselaw_review_sources',{**args,'save':True},fixture.Context()));self.assertNotIn('error',saved,saved)
                report=json.loads(plugin.invoke('caselaw_review_check_sources',{'review_id':saved['review_id'],'target_path':str(paths['target']),'later_path':str(paths['later'])},fixture.Context()));self.assertEqual(report['source_check'],'source_texts_match')
                paths['later'].write_text('Changed source')
                report=json.loads(plugin.invoke('caselaw_review_check_sources',{'review_id':saved['review_id'],'target_path':str(paths['target']),'later_path':str(paths['later'])},fixture.Context()));self.assertEqual(report['source_check'],'changed')
if __name__=='__main__':unittest.main()
