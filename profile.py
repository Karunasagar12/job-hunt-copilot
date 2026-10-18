"""Validated candidate profiles and their generated identity document."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import re
import tempfile
import time
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import Image

import paths


class ProfileError(ValueError):
    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


PLACEHOLDERS = ('name', 'email', 'linkedin', 'github', 'headline', 'signoff_name', 'signoff_title')
REGION_PRESETS = {
    'gcc': {'id': 'gcc', 'label': 'Gulf',
            'keywords': ['dubai', 'abu dhabi', 'saudi', 'riyadh', 'jeddah', 'qatar', 'doha', 'oman', 'muscat', 'bahrain', 'kuwait', 'uae', 'united arab emirates'],
            'salary_sites': ['bayt.com', 'glassdoor.com']},
    'eu': {'id': 'eu', 'label': 'Europe',
           'keywords': ['france', 'paris', 'lyon', 'netherlands', 'amsterdam', 'germany', 'berlin', 'munich', 'hamburg', 'frankfurt', 'ireland', 'dublin', 'brussels', 'belgium', 'zurich', 'geneva', 'switzerland', 'austria', 'vienna', 'luxembourg', 'spain', 'madrid', 'barcelona', 'italy', 'milan', 'portugal', 'lisbon', 'sweden', 'stockholm', 'denmark', 'copenhagen', 'norway', 'oslo', 'finland', 'helsinki', 'poland', 'warsaw', 'czech', 'prague', 'europe'],
           'salary_sites': ['glassdoor.com', 'levels.fyi']},
    'uk': {'id': 'uk', 'label': 'United Kingdom',
           'keywords': ['uk', 'united kingdom', 'london', 'manchester', 'edinburgh', 'glasgow', 'bristol', 'cambridge', 'oxford', 'leeds', 'birmingham'],
           'salary_sites': ['glassdoor.co.uk', 'levels.fyi']},
    'india': {'id': 'india', 'label': 'India',
              'keywords': ['chennai', 'bangalore', 'bengaluru', 'mumbai', 'delhi', 'gurgaon', 'gurugram', 'noida', 'hyderabad', 'pune', 'kolkata', 'india'],
              'salary_sites': ['ambitionbox.com', 'glassdoor.co.in']},
    'us': {'id': 'us', 'label': 'United States',
           'keywords': ['united states', 'usa', 'new york', 'san francisco', 'seattle', 'boston', 'austin', 'chicago', 'los angeles', 'denver', 'atlanta', 'washington, dc', 'remote us'],
           'salary_sites': ['glassdoor.com', 'levels.fyi']},
}
_cache = None


def derive_file_prefix(name):
    ascii_name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^A-Za-z0-9]', '', ascii_name)[:40] or 'Candidate'


def _string(value, field):
    if not isinstance(value, str):
        raise ProfileError(f'{field} must be a string', field)
    return value.strip()


def _strings(value, field, *, lowercase=False):
    if not isinstance(value, list):
        raise ProfileError(f'{field} must be a list of strings', field)
    items = [_string(item, field) for item in value]
    return [(item.lower() if lowercase else item) for item in items if item]


MAX_PHOTO_BYTES = 5 * 1024 * 1024


def validate_photo(blob, extension):
    """Require a bounded, decodable JPEG or PNG matching its file extension."""
    expected = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG'}.get(extension.lower())
    if expected is None:
        raise ProfileError('Photo must be JPG, JPEG or PNG', 'photo')
    if len(blob) > MAX_PHOTO_BYTES:
        raise ProfileError('Photo must be at most 5 MB', 'photo')
    try:
        with Image.open(BytesIO(blob), formats=['JPEG', 'PNG']) as image:
            if image.format != expected:
                raise ProfileError('Photo content must match its extension', 'photo')
            image.verify()
        with Image.open(BytesIO(blob), formats=['JPEG', 'PNG']) as image:
            image.load()
    except ProfileError:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ProfileError('Invalid photo file', 'photo') from exc


def _photo(value):
    if not value:
        return None
    root = paths.data().resolve()
    try:
        candidate = (root / value).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise ProfileError('photo must be an existing file inside DATA_DIR', 'photo')
        with candidate.open('rb') as handle:
            validate_photo(handle.read(MAX_PHOTO_BYTES + 1), candidate.suffix)
    except ProfileError:
        raise
    except (OSError, ValueError) as exc:
        raise ProfileError('photo must be an existing file inside DATA_DIR', 'photo') from exc
    return candidate


def validate(p):
    """Return a normalized independent copy, or a field-specific error."""
    if not isinstance(p, dict):
        raise ProfileError('Profile must be a JSON object')
    p = deepcopy(p)
    for field in ('name', 'email'):
        p[field] = _string(p.get(field, ''), field)
        if not p[field]:
            raise ProfileError(f'{field} is required', field)
    p['file_prefix'] = _string(p.get('file_prefix', derive_file_prefix(p['name'])), 'file_prefix')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', p['file_prefix']):
        raise ProfileError('file_prefix must contain 1-40 letters, digits, underscores or hyphens', 'file_prefix')
    for field in ('linkedin', 'github', 'headline', 'photo'):
        p[field] = _string(p.get(field, ''), field)
    p['signoff_name'] = _string(p.get('signoff_name', p['name'].split()[0]), 'signoff_name')
    p['signoff_title'] = _string(p.get('signoff_title', p['headline']), 'signoff_title')
    _photo(p['photo'])
    p['timezone'] = _string(p.get('timezone', 'UTC'), 'timezone')
    try:
        ZoneInfo(p['timezone'])
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ProfileError('timezone must be a valid IANA timezone', 'timezone') from exc
    regions = p.get('regions')
    if not isinstance(regions, list) or not regions:
        raise ProfileError('At least one region is required', 'regions')
    ids = set()
    for region in regions:
        if not isinstance(region, dict):
            raise ProfileError('Each region must be an object', 'regions')
        rid = _string(region.get('id', ''), 'regions')
        if not re.fullmatch(r'[a-z0-9_]{1,20}', rid) or rid in ids:
            raise ProfileError('Region ids must be unique lowercase identifiers of 1-20 characters', 'regions')
        region['id'] = rid
        ids.add(rid)
        for field, default in (('label', rid), ('phone', ''), ('location', '')):
            region[field] = _string(region.get(field, default), 'regions')
        for field in ('keywords', 'salary_sites'):
            region[field] = _strings(region.get(field, []), 'regions', lowercase=field == 'keywords')
    p['default_region'] = _string(p.get('default_region', regions[0]['id']), 'default_region')
    if p['default_region'] not in ids:
        raise ProfileError('default_region must name a configured region', 'default_region')
    for field in ('extra_agencies', 'target_titles', 'target_locations'):
        p[field] = _strings(p.get(field, []), field)
    return p


def profile_exists():
    return paths.profile_path().is_file()


def load_profile():
    """Cache by resolved path and file version; never expose cached objects."""
    global _cache
    path = paths.profile_path().resolve()
    try:
        stat = path.stat()
        key = (path, stat.st_mtime_ns, stat.st_size)
        if _cache is not None and _cache[0] == key:
            return deepcopy(_cache[1])
        p = validate(json.loads(path.read_text(encoding='utf-8')))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProfileError(f'Cannot read profile: {exc}') from exc
    _cache = (key, p)
    return deepcopy(p)


def _atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=path.parent, delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(text)
        # Windows readers can briefly deny replacement even after our writer closes.
        for attempt in range(5):
            try:
                os.replace(temp_path, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def save_profile(p):
    global _cache
    p = validate(p)
    _atomic_write(paths.profile_path(), json.dumps(p, ensure_ascii=False, indent=2) + '\n')
    _cache = None
    _atomic_write(paths.knowledge_dir() / 'identity.md', render_identity_md(p))
    return p


def region_ids(p=None):
    p = load_profile() if p is None else p
    return [region['id'] for region in p['regions']]


def get_region(region_id=None, p=None):
    p = load_profile() if p is None else p
    for region in p['regions']:
        if region['id'] == region_id:
            return deepcopy(region)
    return deepcopy(next(region for region in p['regions'] if region['id'] == p['default_region']))


def detect_region(text, p=None):
    p = load_profile() if p is None else p
    text = text.lower()
    for region in p['regions']:
        if any(re.search(r'\b' + re.escape(keyword) + r'\b', text) for keyword in region['keywords']):
            return region['id']
    return p['default_region']


def is_extra_agency(company, p=None):
    p = load_profile() if p is None else p
    return company.strip().casefold() in {agency.casefold() for agency in p['extra_agencies']}


def render_identity_md(p):
    p = validate(p)
    lines = ['# Identity', '', '## Common']
    for label, key in (('Name', 'name'), ('Email', 'email'), ('LinkedIn', 'linkedin'), ('GitHub', 'github'), ('Title', 'headline')):
        lines.append(f'{label}: {p[key]}')
    lines.append(f"Photo: {p['photo'] or 'none'}")
    for region in p['regions']:
        lines.extend(['', f"## {region['label']}", f"Phone: {region['phone']}", f"Location: {region['location']}"])
    return '\n'.join(lines) + '\n'


def fill_placeholders(text, p=None):
    p = load_profile() if p is None else p
    def replace(match):
        key = match.group(1).strip()
        if key not in PLACEHOLDERS:
            raise ProfileError(f'Unknown placeholder: {key}', key)
        return p[key]
    return re.sub(r'{{([^{}]*)}}', replace, text)


def photo_path(p=None):
    p = load_profile() if p is None else p
    try:
        return _photo(p.get('photo', ''))
    except ProfileError:
        return None


def today_local(p=None, now=None):
    p = load_profile() if p is None else p
    return (now if now is not None else datetime.now(timezone.utc)).astimezone(ZoneInfo(p['timezone'])).date()
