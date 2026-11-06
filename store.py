"""Optional private review receipts. Hashes detect accidents, not tampering."""
import hashlib
import json
import os
from pathlib import Path
import uuid


def canonical(record):
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


class Reviews:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, review_id):
        if not isinstance(review_id, str) or len(review_id) != 32 or any(c not in '0123456789abcdef' for c in review_id):
            raise ValueError('Invalid review ID')
        path = self.root / (review_id + '.json')
        if path.is_symlink(): raise ValueError('Invalid review path')
        return path

    def save(self, record):
        review_id = uuid.uuid4().hex
        envelope = {'record': record, 'sha256': hashlib.sha256(canonical(record)).hexdigest()}
        if len(canonical(envelope)) > 128 * 1024: raise ValueError('Review receipt exceeds size limit')
        path = self.path(review_id)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f: json.dump(envelope, f, ensure_ascii=False)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return review_id

    def get(self, review_id):
        path = self.path(review_id)
        if not path.is_file() or path.stat().st_size > 128 * 1024: raise ValueError('Review receipt is unavailable or too large')
        envelope = json.loads(path.read_text(encoding='utf-8'))
        record = envelope['record']
        if hashlib.sha256(canonical(record)).hexdigest() != envelope['sha256']:
            raise ValueError('Stored review fingerprint mismatch')
        return {'review_id': review_id, 'review': record,
                'notice': 'The checksum detects accidental change, not tampering or legal correctness. Source URLs and dates remain unverified.'}

    def list(self):
        paths = sorted(self.root.glob('*.json'))
        if len(paths) > 1000: raise ValueError('More than 1,000 review receipts; narrow the directory')
        records, unreadable = [], 0
        for path in paths:
            try:
                item = self.get(path.stem)
                r = item['review']
                records.append({'review_id': path.stem, 'relation': r['relation'], 'treatment': r['treatment'], 'status': r['status']})
            except (ValueError, KeyError, TypeError, OSError):
                unreadable += 1
        return {'reviews': records, 'unreadable_records': unreadable}
