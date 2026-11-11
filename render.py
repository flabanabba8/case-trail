"""Readable renderings of a saved proposed review: the answer, each quoted passage with its source and place, and the limits."""
import html
import os
import re
import uuid
from pathlib import Path


def _label(review, index):
    sources = review.get('sources') or []
    if 0 <= index < len(sources) and isinstance(sources[index], dict):
        return str(sources[index].get('label') or sources[index].get('url') or ('Source %d' % (index + 1)))
    return 'Source %d' % (index + 1)


def _title(review, target):
    """'What happened to the Ninth Circuit ruling in Katz v. United States' when the case name is known."""
    court = str(review.get('target_court') or '').strip()
    short = re.sub(r'^(?:the )?(?:United States )?(?:U\.S\. )?Court of Appeals for the ', '', court, flags=re.I) or target.split(' (')[0]
    text = ' '.join([str(review.get('proposition', ''))] + [str(s.get('label', '')) for s in review.get('sources', []) if isinstance(s, dict)])
    case = re.search(r"([A-Z][\w.'’-]*(?: [A-Z][\w.'’-]*)* v\. [A-Z][\w.'’-]*(?: [A-Z][\w.'’-]*)*)", text)
    return 'What happened to the %s ruling%s' % (short, ' in ' + case.group(1) if case else '')


def sections(review):
    """Plain structure shared by the Markdown and HTML renderings."""
    target, later = _label(review, 0), _label(review, 1)
    evidence = []
    for item in review.get('evidence', []):
        which = 'target' if item.get('source') == 'target' else 'later'
        evidence.append({'quote': item.get('quote', ''), 'source_name': target if which == 'target' else later,
                         'role': 'the opinion under review' if which == 'target' else 'the later opinion',
                         'start': item.get('start'), 'end': item.get('end')})
    dates = [d for d in (review.get('target_date'), review.get('later_date')) if d]
    return {'title': _title(review, target),
            'answer': review.get('outcome', ''), 'proposition': review.get('proposition', ''),
            'kind': '%s, %s (%s of the judgment)' % (review.get('relation', ''), review.get('treatment', ''), review.get('extent', '')),
            'courts': '%s, then %s' % (review.get('target_court', ''), review.get('later_court', '')),
            'why': review.get('analysis', ''), 'against': review.get('contrary', ''), 'evidence': evidence,
            'limits': list(review.get('limitations', [])) + [review.get('notice', '')],
            'status': review.get('status', ''), 'dates': dates, 'sources': [target, later]}


def markdown(review):
    s = sections(review)
    out = ['# ' + s['title'], '', '**Status:** ' + s['status'], '', '## The answer', '', s['answer'], '',
           '*Question:* ' + s['proposition'], '', '*Kind of result:* ' + s['kind'], '', '*Courts:* ' + s['courts']]
    if s['dates']: out += ['', '*Dates (as recorded):* ' + ', '.join(s['dates'])]
    out += ['', '## The exact words relied on', '']
    for i, e in enumerate(s['evidence'], 1):
        out += ['%d. "%s"' % (i, ' '.join(str(e['quote']).split())), '   - From %s: %s' % (e['role'], e['source_name']),
                '   - Where: characters %s to %s of that text' % (e['start'], e['end']), '']
    out += ['## Why this reading', '', s['why'], '', '## What points the other way', '', s['against'], '', '## Limits', '']
    out += ['- ' + x for x in s['limits'] if x]
    out += ['', '## Sources', ''] + ['- ' + x for x in s['sources']]
    return '\n'.join(out) + '\n'


STYLE = """body{font:18px/1.55 Georgia,serif;max-width:900px;margin:40px auto;padding:0 28px;color:#1d2733;background:#fbfaf6}
h1{font-size:34px;margin:0 0 6px}h2{font-size:22px;margin:34px 0 8px;border-bottom:2px solid #d9d2c0;padding-bottom:4px}
.status{display:inline-block;background:#fff3cf;border:1px solid #e0c46a;padding:3px 10px;border-radius:12px;font:14px sans-serif}
.answer{font-size:21px;background:#eef5f1;border-left:6px solid #2d7a5a;padding:14px 18px;margin:14px 0}
blockquote{margin:14px 0;padding:10px 18px;background:#fff;border-left:5px solid #3b6ea5}blockquote p{margin:0 0 6px}
.where{font:14px sans-serif;color:#51606f}.meta{font:15px sans-serif;color:#3a4958}li{margin:5px 0}"""


def html_page(review):
    s = sections(review); e = html.escape
    rows = ''.join('<blockquote><p>&ldquo;%s&rdquo;</p><div class="where">From %s: <b>%s</b><br>Place: characters %s to %s of that text</div></blockquote>'
                   % (e(' '.join(str(x['quote']).split())), e(x['role']), e(x['source_name']), e(str(x['start'])), e(str(x['end']))) for x in s['evidence'])
    dates = ('<p class="meta">Dates (as recorded): %s</p>' % e(', '.join(s['dates']))) if s['dates'] else ''
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>%s</title><style>%s</style></head><body>'
            '<h1>%s</h1><span class="status">%s</span><h2>The answer</h2><div class="answer">%s</div>'
            '<p class="meta"><b>Question:</b> %s<br><b>Kind of result:</b> %s<br><b>Courts:</b> %s</p>%s'
            '<h2>The exact words relied on</h2>%s<h2>Why this reading</h2><p>%s</p><h2>What points the other way</h2><p>%s</p>'
            '<h2>Limits</h2><ul>%s</ul><h2>Sources</h2><ul>%s</ul></body></html>'
            % (e(s['title']), STYLE, e(s['title']), e(s['status']), e(s['answer']), e(s['proposition']), e(s['kind']), e(s['courts']), dates,
               rows, e(s['why']), e(s['against']), ''.join('<li>%s</li>' % e(x) for x in s['limits'] if x), ''.join('<li>%s</li>' % e(x) for x in s['sources'])))


def write(root, review_id, review, fmt='html'):
    if fmt not in ('html', 'markdown'): raise ValueError('format must be html or markdown')
    folder = Path(root) / 'rendered'; folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = review_id + ('.html' if fmt == 'html' else '.md')
    path = folder / name
    if path.is_symlink(): raise ValueError('Invalid output path')
    tmp = folder / (uuid.uuid4().hex + '.tmp')
    tmp.write_text(html_page(review) if fmt == 'html' else markdown(review), encoding='utf-8'); tmp.chmod(0o600); os.replace(tmp, path)
    return str(path)
