"""Opt-in, low-volume public opinion retrieval with explicit provenance."""
import datetime
import hashlib
import http.client
from html.parser import HTMLParser
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import threading
import time
from urllib.parse import unquote, urlsplit
from urllib.robotparser import RobotFileParser
import uuid

HOST = 'openjurist.org'
AGENT = 'HermesCaseResearch/1.0'
MAX_RESPONSE = 2_000_000
MAX_RECORD = 4_000_000
_lock = threading.Lock()
_last_request = 0.0


class PublicConnection(http.client.HTTPSConnection):
    """Resolve a fixed host, then connect only to the checked public address."""
    def connect(self):
        last_error = None
        addresses = socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM)
        for family, kind, proto, _, address in addresses[:4]:
            try:
                if not ipaddress.ip_address(address[0]).is_global:
                    continue
                sock = socket.socket(family, kind, proto)
                try:
                    sock.settimeout(self.timeout)
                    sock.connect(address)
                    self.sock = self._context.wrap_socket(sock, server_hostname=HOST)
                    return
                except (OSError, ssl.SSLError):
                    sock.close()
                    raise
            except (OSError, ValueError, ssl.SSLError) as exc:
                last_error = exc
        raise OSError('No reachable public OpenJurist address') from last_error


def request(path, limit):
    connection = PublicConnection(HOST, 443, timeout=8, context=ssl.create_default_context())
    try:
        connection.request('GET', path, headers={'User-Agent': AGENT, 'Accept-Encoding': 'identity', 'Accept': 'text/html, text/plain'})
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError('OpenJurist returned HTTP ' + str(response.status) + '; no retry was made')
        if response.getheader('Content-Encoding', 'identity').lower() not in ('', 'identity'):
            raise RuntimeError('OpenJurist returned unsupported content encoding')
        length = response.getheader('Content-Length')
        if length and (not length.isdigit() or int(length) > limit):
            raise RuntimeError('OpenJurist response exceeds the size limit')
        data = response.read(limit + 1)
        if len(data) > limit:
            raise RuntimeError('OpenJurist response exceeds the size limit')
        return data
    except (OSError, http.client.HTTPException) as exc:
        raise RuntimeError('OpenJurist request failed; no retry was made') from exc
    finally:
        connection.close()


def paced_request(path, limit, interval, getter, sleeper):
    global _last_request
    delay = interval - (time.monotonic() - _last_request)
    if delay > 0:
        sleeper(delay)
    _last_request = time.monotonic()
    return getter(path, limit)


class BodyText(HTMLParser):
    BLOCKS = {'p', 'div', 'section', 'article', 'li', 'h1', 'h2', 'h3', 'h4', 'blockquote', 'br', 'tr'}
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.stack = []
        self.skip = 0
        self.found = 0
        self.in_title = False
        self.title_parts = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'h1' and not self.stack and not self.title_parts:
            self.in_title = True
        if not self.stack and tag == 'article' and 'opinion-body' in (attrs.get('class') or '').split():
            self.found += 1
            self.stack.append(tag)
            return
        if not self.stack:
            return
        if tag not in self.VOID:
            self.stack.append(tag)
        if tag in ('script', 'style'):
            self.skip += 1
        elif not self.skip and tag in self.BLOCKS:
            self.parts.append('\n')
    def handle_startendtag(self, tag, attrs):
        if self.stack and not self.skip and tag in self.BLOCKS:
            self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag == 'h1' and self.in_title:
            self.in_title = False
        if not self.stack or tag in self.VOID:
            return
        if tag not in self.stack:
            return
        if self.stack[-1] != tag:
            raise ValueError('OpenJurist opinion HTML structure is unsupported')
        if tag in ('script', 'style') and self.skip:
            self.skip -= 1
        elif not self.skip and tag in self.BLOCKS:
            self.parts.append('\n')
        self.stack.pop()
    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)
        if self.stack and not self.skip:
            self.parts.append(data)


def extract_body(body):
    if not isinstance(body, str) or not body.strip() or len(body) > MAX_RESPONSE:
        raise ValueError('OpenJurist case page is missing or too large')
    parser = BodyText()
    parser.feed(body)
    parser.close()
    if parser.found != 1 or parser.stack:
        raise ValueError('OpenJurist opinion section is missing, ambiguous or incomplete')
    text = re.sub(r'\n{3,}', '\n\n', ''.join(parser.parts)).strip()
    if len(text) < 40 or len(text.encode('utf-8')) > MAX_RESPONSE:
        raise ValueError('Extracted opinion text is missing or too large')
    return text, ' '.join(''.join(parser.title_parts).split())[:500] or None


def public_case_path(public_url, volume, series, page):
    expected = reporter_path(volume, series, page)
    if not isinstance(public_url, str) or len(public_url) > 2000:
        raise ValueError('Provide a public OpenJurist case page URL')
    try:
        parsed = urlsplit(public_url)
        if (parsed.scheme != 'https' or parsed.hostname != HOST or parsed.port not in (None, 443)
                or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment
                or not re.fullmatch(re.escape(expected) + r'(?:/[a-z0-9][a-z0-9-]{0,199})?/?', parsed.path)):
            raise ValueError('OpenJurist case URL must match the requested reporter citation')
    except ValueError as exc:
        raise ValueError('OpenJurist case URL must match the requested reporter citation') from exc
    return parsed.path


def conservative_robots_allow(text, path):
    """Fail closed on every matching Disallow, including rules for other agents."""
    if not re.search(r'(?im)^\s*user-agent\s*:', text):
        raise RuntimeError('OpenJurist robots policy is missing or unsupported')
    target = unquote(path)
    for line in text.splitlines():
        field, separator, value = line.split('#', 1)[0].partition(':')
        value = unquote(value.strip())
        if not separator or field.strip().lower() != 'disallow' or not value:
            continue
        anchored = value.endswith('$')
        if anchored: value = value[:-1]
        pattern = '^' + re.escape(value).replace(r'\*', '.*') + ('$' if anchored else '')
        if re.search(pattern, target):
            return False
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    return parser.can_fetch(AGENT, 'https://' + HOST + path)


def reporter_path(volume, series, page):
    if type(volume) is not int or not 1 <= volume <= 9999 or type(page) is not int or not 1 <= page <= 99999:
        raise ValueError('Use positive reporter volume and first-page integers')
    if not isinstance(series, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,31}', series):
        raise ValueError('Use a lowercase OpenJurist reporter-series slug')
    return f'/{volume}/{series}/{page}'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


class PublicOpinions:
    def __init__(self, root):
        self.root = Path(root) / 'public-opinions'
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, source_id):
        if not isinstance(source_id, str) or not re.fullmatch(r'[0-9a-f]{32}', source_id):
            raise ValueError('Invalid public source ID')
        path = self.root / (source_id + '.json')
        if path.is_symlink():
            raise ValueError('Invalid public source path')
        return path

    def load(self, source_id):
        from .core import valid_origin_url, valid_url
        path = self.path(source_id)
        if not path.is_file() or path.stat().st_size > MAX_RECORD:
            raise ValueError('Public source is unavailable or too large')
        envelope = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(envelope, dict) or not isinstance(envelope.get('record'), dict):
            raise ValueError('Invalid public source record')
        record = envelope['record']
        if hashlib.sha256(canonical(record)).hexdigest() != envelope.get('record_sha256'):
            raise ValueError('Public source record fingerprint mismatch')
        if not isinstance(record, dict) or not isinstance(record.get('text'), str):
            raise ValueError('Invalid public source record')
        if hashlib.sha256(record['text'].encode('utf-8')).hexdigest() != record.get('sha256'):
            raise ValueError('Public source fingerprint mismatch')
        if not valid_url(record.get('reference_url')) or not valid_origin_url(record.get('text_origin_url')):
            raise ValueError('Invalid public source provenance')
        return record

    def fetch(self, url, public_url, volume, series, page, *, _request=None, _sleep=None):
        from .core import valid_url
        if not valid_url(url):
            raise ValueError('Provide the Justia reference URL for this case')
        page_path = public_case_path(public_url, volume, series, page)
        getter = _request or request
        sleeper = _sleep or time.sleep
        # ponytail: this lock paces one process; separate Hermes processes need external coordination.
        if not _lock.acquire(blocking=False):
            raise RuntimeError('Another OpenJurist request is already running')
        try:
            robots_raw = paced_request('/robots.txt', 65536, 1, getter, sleeper)
            if not isinstance(robots_raw, bytes) or len(robots_raw) > 65536:
                raise RuntimeError('OpenJurist robots policy is invalid or too large')
            robots_text = robots_raw.decode('utf-8-sig')
            if not conservative_robots_allow(robots_text, page_path):
                raise RuntimeError('OpenJurist robots policy does not permit this request')
            robots = RobotFileParser()
            robots.parse(robots_text.splitlines())
            delay = robots.crawl_delay(AGENT) or robots.crawl_delay('*') or 0
            if delay > 5:
                raise RuntimeError('OpenJurist crawl delay exceeds the automatic request limit')
            data = paced_request(page_path, MAX_RESPONSE, max(1, delay), getter, sleeper)
            if not isinstance(data, bytes) or len(data) > MAX_RESPONSE:
                raise RuntimeError('OpenJurist response is invalid or too large')
        finally:
            _lock.release()
        try:
            text, title = extract_body(data.decode('utf-8'))
        except UnicodeError as exc:
            raise RuntimeError('OpenJurist returned invalid UTF-8') from exc
        fields = {'title': title, 'citation': None, 'court': None, 'decidedOn': None,
                  'bodySource': 'OpenJurist case page', 'bodyQuality': 'not reported; verify source and OCR'}
        source_id = uuid.uuid4().hex
        record = {'reference_url': url, 'text_origin_url': public_url,
                  'reporter_path': reporter_path(volume, series, page), 'metadata': fields, 'text': text,
                  'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
                  'fetched_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
        envelope = {'record': record, 'record_sha256': hashlib.sha256(canonical(record)).hexdigest()}
        if len(canonical(envelope)) > MAX_RECORD:
            raise ValueError('Public source record exceeds the size limit')
        path_out = self.path(source_id)
        fd = os.open(path_out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(envelope, stream, ensure_ascii=False, separators=(',', ':'))
        except BaseException:
            path_out.unlink(missing_ok=True)
            raise
        return {'source_id': source_id, **{k: v for k, v in record.items() if k != 'text'},
                'notice': 'OpenJurist receives the selected page URL and your IP address. Text and metadata are untrusted; identity, OCR quality, separate opinions and completeness require review. No legal status is certified.'}

    def list(self):
        paths = sorted(self.root.glob('*.json'))
        if len(paths) > 1000:
            raise ValueError('More than 1,000 public source records')
        records, unreadable = [], 0
        for path in paths:
            try:
                record = self.load(path.stem)
                records.append({'source_id': path.stem, 'reference_url': record['reference_url'], 'metadata': record['metadata'],
                                'sha256': record['sha256'], 'fetched_at': record['fetched_at']})
            except (OSError, ValueError, KeyError, TypeError):
                unreadable += 1
        return {'sources': records, 'unreadable_records': unreadable,
                'notice': 'Metadata and references are unverified and stored privately.'}

    def check_review(self, review, target_source_id, later_source_id):
        sources = review.get('sources') if isinstance(review, dict) else None
        if not isinstance(sources, list) or len(sources) != 2:
            raise ValueError('Review receipt has invalid source fingerprints')
        checks = []
        for role, ident, expected in zip(('target', 'later'), (target_source_id, later_source_id), sources):
            if not isinstance(expected, dict):
                raise ValueError('Review receipt has invalid source fingerprints')
            try:
                record = self.load(ident)
                same = (record['sha256'] == expected.get('sha256') and
                        record['reference_url'] == expected.get('url') and
                        record['text_origin_url'] == expected.get('text_origin_url'))
                checks.append({'role': role, 'status': 'matches' if same else 'changed'})
            except (OSError, ValueError, KeyError, TypeError):
                checks.append({'role': role, 'status': 'unavailable_or_unsupported'})
        statuses = {item['status'] for item in checks}
        state = 'changed' if 'changed' in statuses else 'incomplete' if 'unavailable_or_unsupported' in statuses else 'source_texts_match'
        return {'source_check': state, 'sources': checks,
                'notice': 'Matching stored text does not verify provenance, legal analysis or later developments. Refreshing requires a separate explicit request.'}
