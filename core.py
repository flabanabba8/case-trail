"""Evidence triage for case research. A match is never a legal conclusion."""
import hashlib
import datetime
import ipaddress
import itertools
from collections import deque
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
DISPOSITION = re.compile(r'(?<![^\W_])(?:we\s+(?:therefore\s+|hereby\s+)?(?:reverse|affirm|vacate)|'
                         r'(?:judgments?|orders?|decisions?|convictions?|sentences?)\b[^.\n]{0,100}'
                         r'\b(?:reversed|affirmed|vacated)|(?:reversed|affirmed|vacated)\s+and\s+remanded)(?=$|[^\w]|_)'
                         r'|(?<![A-Za-z0-9])\d{1,4}[ \t]+(?:[A-Za-z][A-Za-z0-9.]{0,20}[ \t]+){1,4}'
                         r'\d{1,5},[ \t]*(?:reversed|affirmed|vacated)(?:[ \t]+in[ \t]+part)?(?=[.;]|$)'
                         r'|^[ \t]*[_*]{0,2}(?:reversed|affirmed|vacated)(?:[ \t]+in[ \t]+part)?'
                         r'(?:[ \t]+and[ \t]+(?:reversed|affirmed|vacated)(?:[ \t]+in[ \t]+part)?)?'
                         r'(?=[_*]{0,2}[.!](?:[ \t]*$|[ \t]+))', re.I | re.M)
MONTHS = {name.lower(): index for index, name in enumerate(
    ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'), 1)}
DATE_TEXT = r'(?P<month>' + '|'.join(MONTHS) + r')[ \t]+(?P<day>\d{1,2}),[ \t]+(?P<year>\d{4})'
LABELED_DATE = re.compile(r'^[ \t]*(?P<label>Date[ \t]+Decided|Decided|Certiorari[ \t]+Granted)[ \t]*:?[ \t]*' + DATE_TEXT + r'[ \t]*\.?[ \t]*\r?$', re.I | re.M)
STANDALONE_DATE = re.compile(r'^[ \t]*' + DATE_TEXT + r'[ \t]*\.?[ \t]*\r?$', re.I | re.M)
PRIVATE = {'.ssh', '.gnupg', '.aws', '.azure', '.codex', '.docker', '.kube', '.pki', '.config', '.hermes', '.claude', '.gemini', '.mozilla'}
PRIVATE_SUBPATHS = (('.local', 'share', 'keyrings'),)
SYSTEM_PREFIXES = ('/proc', '/sys', '/dev')          # kernel views of a running process can expose provider keys as "excerpts"
ALLOWED_ROOTS = ()                                   # folders the OWNER lists in the plugin setting opinion_folders; empty = any readable folder outside the denylist
PRIVATE_FILES = {'.env', '.netrc', '.npmrc', '.pypirc', '.git-credentials', 'credentials.json', 'secrets.json', 'token.json', 'auth.json'}
PRIVATE_SUFFIXES = {'.pem', '.key', '.p12', '.pfx', '.keystore', '.jks'}


def private_file(path):
    return path.name.lower() in PRIVATE_FILES or path.name.lower().startswith('.env.') or path.suffix.lower() in PRIVATE_SUFFIXES


def set_allowed_roots(roots):
    """Owner-set folders (plugin setting opinion_folders) that opinion files must live under. Empty = no extra restriction."""
    global ALLOWED_ROOTS
    out = []
    for r in roots or ():
        try: out.append(Path(str(r)).expanduser().resolve(strict=True))
        except (OSError, ValueError): pass
    ALLOWED_ROOTS = tuple(out)


def hermes_home():
    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home()).resolve()
    except Exception:
        return None


def refused_location(resolved):
    """Why a resolved path must never be read, or None: kernel/device views, the Hermes home, key stores, the owner's folder list."""
    text = resolved.as_posix()
    if any(text == p or text.startswith(p + '/') for p in SYSTEM_PREFIXES): return 'kernel and device files are unsupported'
    home = hermes_home()
    if home is not None and (resolved == home or home in resolved.parents): return 'the Hermes home folder is unsupported'
    parts = tuple(x.casefold() for x in resolved.parts)
    if any(any(parts[i:i + len(sub)] == sub for i in range(len(parts))) for sub in PRIVATE_SUBPATHS): return 'key stores are unsupported'
    if ALLOWED_ROOTS and not any(r == resolved or r in resolved.parents for r in ALLOWED_ROOTS): return 'the file is outside the folders listed in the plugin setting opinion_folders'
    return None


def read_opinion(path):
    if not isinstance(path, str): raise ValueError('Opinion path must be a string')
    original = Path(path).expanduser()
    if not original.is_absolute() or original.is_symlink() or private_file(original) or any(x.casefold() in PRIVATE for x in original.parts):
        raise ValueError('Use an absolute opinion file outside private configuration')
    resolved = original.resolve(strict=True)
    if private_file(resolved) or any(x.casefold() in PRIVATE for x in resolved.parts): raise ValueError('Private configuration is unsupported')
    why = refused_location(resolved)
    if why: raise ValueError('Opinion file refused: ' + why)
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
                and u.port in (None, 443) and u.username is None and u.password is None
                and not u.query and not u.fragment and u.path.startswith('/cases/'))
    except ValueError:
        return False


def valid_origin_url(url):
    if not isinstance(url, str) or len(url) > 2000:
        return False
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').rstrip('.')
        if (parsed.scheme != 'https' or not host or '.' not in host or parsed.port not in (None, 443)
                or parsed.username is not None or parsed.password is not None or parsed.fragment
                or not any(c.isalpha() for c in host)
                or host.endswith(('.local', '.lan', '.internal', '.localdomain', '.localhost', '.home.arpa', '.ts.net'))):
            return False
        if parsed.query:
            return False
        try: ipaddress.ip_address(host)
        except ValueError: return True
        return False
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
        searches.append(('supreme citing', quoted(safe[1])))
    if safe[2]:
        searches.append(('docket history', quoted(safe[2]) + ' appeal'))
    return [(kind, ('site:supreme.justia.com/cases/ ' if kind == 'supreme citing' else
                    '(site:law.justia.com/cases/ OR site:supreme.justia.com/cases/) ') + query.strip())
            for kind, query in searches]


def date_cues(text):
    """Flag possible metadata conflicts, without deciding what an unlabeled date means."""
    head = text[:4000]
    matches = []
    for pattern, default in ((LABELED_DATE, None), (STANDALONE_DATE, 'unlabeled')):
        for match in itertools.islice(pattern.finditer(head), 31):
            label = default or ('certiorari_granted' if match.group('label').lower().startswith('certiorari') else 'decision_label')
            try:
                date = datetime.date(int(match.group('year')), MONTHS[match.group('month').lower()], int(match.group('day'))).isoformat()
            except ValueError:
                date = None
            matches.append({'event': label, 'date': date, 'start': match.start(), 'end': match.end(), 'excerpt': match.group()})
    matches.sort(key=lambda item: item['start'])
    truncated = len(matches) > 30
    matches = matches[:30]
    decisions = {x['date'] for x in matches if x['event'] == 'decision_label' and x['date']}
    grants = {x['date'] for x in matches if x['event'] == 'certiorari_granted' and x['date']}
    unlabeled = {x['date'] for x in matches if x['event'] == 'unlabeled' and x['date']}
    flags = []
    if len(decisions) > 1: flags.append('conflicting_decision_labels')
    if decisions & grants and any(day not in decisions for day in unlabeled):
        flags.append('decision_label_matches_grant_but_another_date_appears')
    return {'candidates': matches, 'possible_conflicts': flags, 'truncated': truncated,
            'scan_scope': 'first 4000 characters; English month dates on separate lines only',
            'notice': 'These are unverified date leads. An unlabeled date may mean something else; missing matches do not establish absence.'}


def _examine(url, text, identifiers, text_origin_url=None, _provider_neutral=False):
    if _provider_neutral and url is not None and not valid_origin_url(url):
        raise ValueError('Source URL must be public HTTPS without credentials, query or fragment')
    if not _provider_neutral and not valid_url(url):
        raise ValueError('Use an HTTPS Justia case-opinion URL without query or fragment')
    if not isinstance(text, str) or not text.strip() or len(text) > 2_000_000:
        raise ValueError('Supply up to 2 million characters of extracted opinion text')
    if text_origin_url is not None and not valid_origin_url(text_origin_url):
        raise ValueError('Text origin must be a public HTTPS URL without credentials, query or fragment')
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
    # Retain both ends: an opinion's own disposition often follows many earlier references.
    first, last, outcome_count = [], deque(maxlen=10), 0
    for match in DISPOSITION.finditer(text):
        outcome_count += 1
        if len(first) < 10: first.append(match)
        else: last.append(match)
    outcomes = first + list(last)
    outcome_cues = [{'start': max(0, m.start()-150), 'end': min(len(text), m.end()+150),
                     'excerpt': text[max(0, m.start()-150):min(len(text), m.end()+150)]} for m in outcomes]
    return {'url': url, 'text_origin_url': text_origin_url,
            'text_origin_verification': 'user-supplied; not authenticated' if text_origin_url else 'not specified',
            'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'text_characters': len(text), 'matches': hits[:100], 'truncated_identifiers': truncated,
            'total_match_output_truncated': len(hits) > 100, 'outcome_cues': outcome_cues,
            'outcome_cues_truncated': outcome_count > 20, 'outcome_cue_matches': outcome_count,
            'date_cues': date_cues(text),
            'outcome_selection': 'first ten and last ten matches when more than twenty occur', 'status': 'unverified leads',
            'text_completeness': 'not established', 'notice': NOTICE}



def examine(url, text, identifiers, text_origin_url=None):
    return _examine(url, text, identifiers, text_origin_url)


def examine_source(source_label, text, identifiers, source_url=None):
    if not isinstance(source_label, str) or not source_label.strip() or len(source_label) > 500:
        raise ValueError('Supply a bounded source label; do not invent a reference URL')
    result = _examine(source_url, text, identifiers, source_url, _provider_neutral=True)
    return {**result, 'source_label': source_label.strip(),
            'reference_kind': 'caller-provided source; provider-independent, not authenticated'}


def _closest(anchor, text):
    words = set(re.findall(r'\w+', anchor.lower()))
    lines = text.splitlines()
    best, best_score = '', 0
    for i in range(len(lines)):
        window = ' '.join(x.strip() for x in lines[i:i + 3])
        score = len(words & set(re.findall(r'\w+', window.lower())))
        if score > best_score: best, best_score = window, score
    return re.sub(r'\s+', ' ', best)[:300] if words and best_score >= max(3, len(words) // 2) else ''


def _locate(item, text):
    """Cite by location so long passages need not be retyped: {source, anchor} (a short exact phrase found exactly once)
    or {source, start, end}. The plugin fills in the quote from the file itself; the exact-match check below still runs."""
    if 'anchor' in item:
        anchor = item['anchor']
        if set(item) != {'source', 'anchor'} or not isinstance(anchor, str) or not 8 <= len(anchor) <= 500 or not anchor.strip():
            raise ValueError('An anchor citation has only source and anchor (8-500 characters, exact text from the file)')
        # Line breaks and runs of spaces in the file may differ from how the phrase was typed; match them flexibly,
        # then record the file's own exact text.
        found = list(re.finditer(r'\s+'.join(re.escape(w) for w in anchor.split()), text))
        if not found:
            hint = _closest(anchor, text)
            raise ValueError('Anchor text was not found in that source; copy a shorter exact phrase.' + (' Closest passage in that file (line breaks shown as spaces): "%s"' % hint if hint else ''))
        if len(found) > 1: raise ValueError('Anchor text appears more than once in that source; use a longer or different exact phrase')
        first, last = found[0].span()
        return {'source': item['source'], 'start': first, 'end': last, 'quote': text[first:last]}
    if 'quote' not in item and type(item.get('start')) is int and type(item.get('end')) is int:
        if set(item) != {'source', 'start', 'end'} or not 0 <= item['start'] < item['end'] <= len(text) or item['end'] - item['start'] > 500:
            raise ValueError('A location citation has only source, start and end, inside the file and at most 500 characters')
        return {**item, 'quote': text[item['start']:item['end']]}
    return item


MONTH_NAMES = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December')


def date_in_text(date, text):
    """True when the file itself states this day, in ISO or written form (December 18, 1967 / 18 December 1967 / Dec. 18, 1967)."""
    month, day, year = MONTH_NAMES[date.month - 1], date.day, date.year
    forms = [date.isoformat()]
    for name in (month, month[:3], month[:3] + '.'):
        forms += ['%s %d, %d' % (name, day, year), '%s %02d, %d' % (name, day, year), '%d %s %d' % (day, name, year), '%s %d %d' % (name, day, year)]
    flat = ' '.join(str(text).split())
    return any(f.lower() in flat.lower() for f in forms)


def _review(target, later, evidence, relation, treatment, extent, opinion_role, proposition,
           target_court, later_court, authority_analysis, identity_rationale, outcome, analysis, contrary, limitations,
           target_date=None, later_date=None, reviewer_kind='unspecified', read_scope='unspecified', _provider_neutral=False):
    for source in (target, later):
        if _provider_neutral:
            if not isinstance(source, dict) or not isinstance(source.get('label'), str) or not source['label'].strip() or len(source['label']) > 500 or not isinstance(source.get('text'), str) or not source['text'].strip() or len(source['text']) > 2_000_000:
                raise ValueError('Both sources need a bounded label and extracted opinion text')
            if source.get('url') is not None and not valid_origin_url(source['url']):
                raise ValueError('Optional source URLs must be public HTTPS without credentials, query or fragment')
        elif not isinstance(source, dict) or not valid_url(source.get('url')) or not isinstance(source.get('text'), str) or not source['text'].strip() or len(source['text']) > 2_000_000:
            raise ValueError('Both source objects need a Justia case URL and extracted opinion text')
        if source.get('text_origin_url') is not None and not valid_origin_url(source['text_origin_url']):
            raise ValueError('Text origin must be a public HTTPS URL without credentials, query or fragment')
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
    for value, dated_source in ((target_date, target), (later_date, later)):
        if value is None:
            dates.append(None)
            continue
        if not isinstance(value, str): raise ValueError('Decision dates must be ISO dates (YYYY-MM-DD); omit the field when the file does not state the date')
        try: date = datetime.date.fromisoformat(value)
        except ValueError as exc: raise ValueError('Decision dates must be ISO dates (YYYY-MM-DD); omit the field when the file does not state the date') from exc
        if date.isoformat() != value or date > datetime.date.today(): raise ValueError('Decision dates must be valid nonfuture ISO dates')
        dates.append(date)
    if all(dates) and dates[1] < dates[0]: raise ValueError('Later decision predates the target decision')
    for value, parsed, dated_source in ((target_date, dates[0], target), (later_date, dates[1], later)):
        if parsed is not None and not date_in_text(parsed, dated_source['text']):
            raise ValueError('The date %s does not appear in that source file. Leave the date out unless the file itself states it; do not supply a date from memory.' % value)
    if not all(isinstance(x, str) and x.strip() and len(x) <= 3000 for x in
               (proposition, target_court, later_court, authority_analysis, identity_rationale, outcome, analysis, contrary)):
        raise ValueError('Provide the proposition, both courts and their authority relationship, identity rationale, outcome, supporting and contrary analysis')
    if not isinstance(limitations, list) or not 1 <= len(limitations) <= 20 or any(not isinstance(x, str) or not x.strip() or len(x) > 1000 for x in limitations):
        raise ValueError('Provide 1–20 specific coverage limitations of at most 1,000 characters each')
    if not isinstance(evidence, list) or not 2 <= len(evidence) <= 20:
        raise ValueError('Provide evidence from both sources')
    found = set()
    expanded = []
    for e in evidence:
        if not isinstance(e, dict) or e.get('source') not in {'target', 'later'}:
            raise ValueError('Invalid evidence source')
        src = target if e['source'] == 'target' else later
        e = _locate(e, src['text'])
        expanded.append(e)
        a, b, quote = e.get('start'), e.get('end'), e.get('quote')
        if type(a) is not int or type(b) is not int or not isinstance(quote, str) or not quote.strip() or len(quote) > 500 or not 0 <= a < b <= len(src['text']) or src['text'][a:b] != quote:
            raise ValueError('Evidence must be exact quoted text at the supplied offsets')
        found.add(e['source'])
    if found != {'target', 'later'}:
        raise ValueError('Evidence from both opinions is required')
    evidence = expanded
    return {'status': 'proposed; not independently reviewed', 'relation': relation, 'treatment': treatment,
            'extent': extent, 'opinion_role': opinion_role, 'analysis': analysis, 'contrary': contrary,
            'proposition': proposition, 'target_court': target_court, 'later_court': later_court,
            'authority_analysis': authority_analysis, 'identity_rationale': identity_rationale, 'outcome': outcome,
            'target_date': target_date, 'later_date': later_date,
            'reviewer_kind': reviewer_kind, 'read_scope': read_scope,
            'chronology': 'provided dates checked for order, not authenticated' if all(dates) else 'unverified: decision date missing',
            'limitations': limitations, 'evidence': evidence,
            'sources': [{'url': s['url'], 'text_origin_url': s.get('text_origin_url'),
                         'sha256': hashlib.sha256(s['text'].encode()).hexdigest()} for s in (target, later)],
            'notice': NOTICE + ' Matching quotes do not verify the legal analysis, URL provenance, decision dates or completeness of either text.'}


def review(*args, **kwargs):
    if '_provider_neutral' in kwargs: raise ValueError('Use the provider-independent source review interface explicitly')
    return _review(*args, **kwargs)


def review_sources(target, later, **kwargs):
    if not isinstance(target, dict) or not isinstance(later, dict): raise ValueError('Supply two source objects')
    target, later = ({**source, 'url': source.get('url')} for source in (target, later))
    result = _review(target, later, _provider_neutral=True, **kwargs)
    result['sources'] = [{**record, 'label': source['label'], 'reference_kind': 'caller-provided, not authenticated'}
                         for record, source in zip(result['sources'], (target, later))]
    return result
