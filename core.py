"""Evidence triage for case research. A match is never a legal conclusion."""
import hashlib
import datetime
import itertools
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit

NOTICE = ('Candidates and quotations do not establish legal status. Read both complete opinions, '
          'including separate opinions, and check court authority, disposition and later law. '
          'Search coverage is incomplete; zero results never mean no adverse history.')
CUES = re.compile(r'\b(?:revers\w*|vacat\w*|affirm\w*|overrul\w*|abrogat\w*|'
                  r'disapprov\w*|distinguish\w*|limit\w*|question\w*|criticiz\w*)\b', re.I)
DISPOSITION = re.compile(r'\b(?:we\s+(?:therefore\s+|hereby\s+)?(?:reverse|affirm|vacate)|'
                         r'(?:judgments?|orders?|decisions?|convictions?|sentences?)\b[^.\n]{0,100}'
                         r'\b(?:reversed|affirmed|vacated)|(?:reversed|affirmed|vacated)\s+and\s+remanded)\b', re.I)
PRIVATE = {'.ssh', '.gnupg', '.aws', '.azure', '.codex', '.docker', '.kube', '.pki', '.config', '.hermes'}
PRIVATE_FILES = {'.env', '.netrc', '.npmrc', '.pypirc', '.git-credentials', 'credentials.json', 'secrets.json', 'token.json'}
PRIVATE_SUFFIXES = {'.pem', '.key', '.p12', '.pfx', '.keystore', '.jks'}


def private_file(path):
    return path.name.lower() in PRIVATE_FILES or path.name.lower().startswith('.env.') or path.suffix.lower() in PRIVATE_SUFFIXES


def read_opinion(path):
    if not isinstance(path, str): raise ValueError('Opinion path must be a string')
    original = Path(path).expanduser()
    if not original.is_absolute() or original.is_symlink() or private_file(original) or any(x in PRIVATE for x in original.parts):
        raise ValueError('Use an absolute opinion file outside private configuration')
    resolved = original.resolve(strict=True)
    if private_file(resolved) or any(x in PRIVATE for x in resolved.parts): raise ValueError('Private configuration is unsupported')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    fd = os.open(resolved, flags)
    with os.fdopen(fd, 'rb') as f:
        before = os.fstat(f.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > 2_000_000:
            raise ValueError('Opinion must be a regular UTF-8 file of at most 2 MB')
        raw = f.read(2_000_001)
        after = os.fstat(f.fileno())
    if len(raw) > 2_000_000 or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('Opinion changed or exceeded the size limit')
    current = resolved.lstat()
    if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino):
        raise ValueError('Opinion changed or was replaced during reading')
    return raw.decode('utf-8')


def valid_url(url):
    if not isinstance(url, str) or len(url) > 2000:
        return False
    try:
        u = urlsplit(url)
        return (u.scheme == 'https' and u.hostname in {'law.justia.com', 'supreme.justia.com'}
                and u.port in (None, 443) and not u.username and not u.password
                and not u.query and not u.fragment and u.path.startswith('/cases/'))
    except ValueError:
        return False


def may_be_index(url):
    return bool(re.search(r'/\d{4}/?$', urlsplit(url).path))


def terms(case, citation, docket):
    fields = [case, citation, docket]
    if any(not isinstance(x, str) or len(x) > 200 or '\n' in x or '\r' in x for x in fields):
        raise ValueError('Identifiers must be short single-line strings')
    if not case.strip() and not citation.strip() and not docket.strip():
        raise ValueError('Provide at least a case name, citation or docket')
    # Avoid allowing search operators supplied inside identifiers.
    safe = [re.sub(r"[^\w\s.,&\-'’]", ' ', x).strip() for x in fields]
    def quoted(s): return '"' + s + '"'
    identifiers = [quoted(x) for x in safe if x]
    searches = []
    if safe[0]:
        searches.append(('appeal history', quoted(safe[0]) + ' ' + ' '.join(quoted(x) for x in safe[1:] if x) + ' appeal reversed'))
        parties = re.split(r'\s+v(?:s)?\.?\s+', safe[0], maxsplit=1, flags=re.I)
        if len(parties) == 2 and all(x.strip() for x in parties):
            searches.append(('appeal parties', ' '.join(quoted(x.strip()) for x in parties) + ' appeal reversed'))
    if safe[1]:
        searches.append(('subsequent treatment', quoted(safe[1]) + ' overruled OR abrogated OR limited'))
        searches.append(('citing cases', quoted(safe[1])))
    if safe[2]:
        searches.append(('docket history', quoted(safe[2]) + ' appeal'))
    return [(kind, '(site:law.justia.com/cases/ OR site:supreme.justia.com/cases/) ' + query.strip())
            for kind, query in searches]


def examine(url, text, identifiers):
    if not valid_url(url):
        raise ValueError('Use an HTTPS Justia case-opinion URL without query or fragment')
    if not isinstance(text, str) or not text.strip() or len(text) > 2_000_000:
        raise ValueError('Supply up to 2 million characters of extracted opinion text')
    if not isinstance(identifiers, list) or not 1 <= len(identifiers) <= 8:
        raise ValueError('Supply 1 to 8 case identifiers')
    if any(not isinstance(x, str) or not x.strip() or len(x) > 200 for x in identifiers):
        raise ValueError('Invalid case identifier')
    hits, truncated = [], []
    for identifier in identifiers:
        # Reporter abbreviations appear as both "U.S." and "U. S." in extracted opinions.
        def reporter_word(word):
            # The final dot is followed by the inter-word separator already.
            stem, tail = (word[:-1], '.') if word.endswith('.') else (word, '')
            return re.escape(stem).replace(r'\.', r'\.\s*') + re.escape(tail)
        pattern = r'\s+'.join(reporter_word(word) for word in identifier.split())
        matches = list(itertools.islice(re.finditer(pattern, text, re.I), 21))
        if len(matches) > 20: truncated.append(identifier)
        for m in matches[:20]:
            start, end = max(0, m.start()-240), min(len(text), m.end()+240)
            excerpt = text[start:end]
            hits.append({'identifier': identifier, 'start': start, 'end': end,
                         'excerpt': excerpt, 'cues': sorted({x.group().lower() for x in CUES.finditer(excerpt)})})
    outcomes = list(itertools.islice(DISPOSITION.finditer(text), 21))
    outcome_cues = [{'start': max(0, m.start()-150), 'end': min(len(text), m.end()+150),
                     'excerpt': text[max(0, m.start()-150):min(len(text), m.end()+150)]} for m in outcomes[:20]]
    return {'url': url, 'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'text_characters': len(text), 'matches': hits[:100], 'truncated_identifiers': truncated,
            'total_match_output_truncated': len(hits) > 100, 'outcome_cues': outcome_cues,
            'outcome_cues_truncated': len(outcomes) > 20, 'status': 'unverified leads',
            'text_completeness': 'not established', 'notice': NOTICE}


def review(target, later, evidence, relation, treatment, extent, opinion_role, proposition,
           target_court, later_court, authority_analysis, identity_rationale, outcome, analysis, contrary, limitations,
           target_date=None, later_date=None, reviewer_kind='unspecified', read_scope='unspecified'):
    for source in (target, later):
        if not isinstance(source, dict) or not valid_url(source.get('url')) or not isinstance(source.get('text'), str) or not source['text'].strip() or len(source['text']) > 2_000_000:
            raise ValueError('Both source objects need a Justia case URL and extracted opinion text')
    if relation not in {'direct-history', 'later-treatment', 'uncertain'}:
        raise ValueError('Invalid relationship')
    if treatment not in {'reversed', 'affirmed', 'vacated', 'overruled', 'limited', 'distinguished', 'followed', 'uncertain'}:
        raise ValueError('Invalid treatment')
    if extent not in {'whole', 'part', 'uncertain'} or opinion_role not in {'majority', 'per-curiam', 'plurality', 'concurrence', 'dissent', 'mixed', 'unknown'}:
        raise ValueError('Invalid extent or opinion role')
    if treatment in {'reversed', 'affirmed', 'vacated'} and relation != 'direct-history':
        raise ValueError('Judgment disposition requires same-litigation direct history')
    if treatment in {'reversed', 'affirmed', 'vacated'} and opinion_role in {'dissent', 'concurrence', 'unknown'}:
        raise ValueError('A separate opinion or unknown opinion role does not establish the court disposition; use uncertain')
    if treatment == 'overruled' and (relation != 'later-treatment' or opinion_role not in {'majority', 'per-curiam'}):
        raise ValueError('Overruling requires later court holding; use uncertain if unresolved')
    if reviewer_kind not in {'assistant', 'human', 'unspecified'} or read_scope not in {'passages-only', 'full-opinions', 'unspecified'}:
        raise ValueError('Invalid reviewer kind or reading scope')
    dates = []
    for value in (target_date, later_date):
        if value is None:
            dates.append(None)
            continue
        if not isinstance(value, str): raise ValueError('Decision dates must be ISO dates')
        try: date = datetime.date.fromisoformat(value)
        except ValueError as exc: raise ValueError('Decision dates must be ISO dates') from exc
        if date.isoformat() != value or date > datetime.date.today(): raise ValueError('Decision dates must be valid nonfuture ISO dates')
        dates.append(date)
    if all(dates) and dates[1] < dates[0]: raise ValueError('Later decision predates the target decision')
    if not all(isinstance(x, str) and x.strip() and len(x) <= 3000 for x in
               (proposition, target_court, later_court, authority_analysis, identity_rationale, outcome, analysis, contrary)):
        raise ValueError('Provide the proposition, both courts and their authority relationship, identity rationale, outcome, supporting and contrary analysis')
    if not isinstance(limitations, list) or not 1 <= len(limitations) <= 20 or any(not isinstance(x, str) or not x.strip() or len(x) > 1000 for x in limitations):
        raise ValueError('Provide 1–20 specific coverage limitations of at most 1,000 characters each')
    if not isinstance(evidence, list) or not 2 <= len(evidence) <= 20:
        raise ValueError('Provide evidence from both sources')
    found = set()
    for e in evidence:
        if not isinstance(e, dict) or e.get('source') not in {'target', 'later'}:
            raise ValueError('Invalid evidence source')
        src = target if e['source'] == 'target' else later
        a, b, quote = e.get('start'), e.get('end'), e.get('quote')
        if type(a) is not int or type(b) is not int or not isinstance(quote, str) or not quote.strip() or len(quote) > 500 or not 0 <= a < b <= len(src['text']) or src['text'][a:b] != quote:
            raise ValueError('Evidence must be exact quoted text at the supplied offsets')
        found.add(e['source'])
    if found != {'target', 'later'}:
        raise ValueError('Evidence from both opinions is required')
    return {'status': 'proposed; not independently reviewed', 'relation': relation, 'treatment': treatment,
            'extent': extent, 'opinion_role': opinion_role, 'analysis': analysis, 'contrary': contrary,
            'proposition': proposition, 'target_court': target_court, 'later_court': later_court,
            'authority_analysis': authority_analysis, 'identity_rationale': identity_rationale, 'outcome': outcome,
            'target_date': target_date, 'later_date': later_date,
            'reviewer_kind': reviewer_kind, 'read_scope': read_scope,
            'chronology': 'provided dates checked for order, not authenticated' if all(dates) else 'unverified: decision date missing',
            'limitations': limitations, 'evidence': evidence,
            'sources': [{'url': s['url'], 'sha256': hashlib.sha256(s['text'].encode()).hexdigest()} for s in (target, later)],
            'notice': NOTICE + ' Matching quotes do not verify the legal analysis, URL provenance, decision dates or completeness of either text.'}
