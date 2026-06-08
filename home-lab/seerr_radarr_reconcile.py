"""
Diagnose and reconcile discrepancy between Radarr queue/library and Jellyseerr request statuses.
Jellyseerr API key is base64-encoded in settings.json main.apiKey field.
"""
import requests
import json
import base64
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

_env_radarr_ip = os.environ["RADARR_IP"]
RADARR_BASE = f"http://{_env_radarr_ip}:7878"
RADARR_KEY = os.environ["RADARR_API_KEY"]
R_HEADERS = {'X-Api-Key': RADARR_KEY}

_env_seerr_ip = os.environ["SEERR_IP"]
SEERR_BASE = f"http://{_env_seerr_ip}:5055"
# Decode the base64 API key
SEERR_KEY_B64 = os.environ["SEERR_API_KEY"]
SEERR_KEY = base64.b64decode(SEERR_KEY_B64).decode('utf-8')
print(f"Seerr API key: {SEERR_KEY}")
S_HEADERS = {'X-Api-Key': SEERR_KEY}

# ── Radarr: full picture ──────────────────────────────────────────────────────

print("\n=== RADARR QUEUE ===")
r = requests.get(f'{RADARR_BASE}/api/v3/queue', headers=R_HEADERS,
                 params={'pageSize': 200, 'includeMovie': True})
queue = r.json()
radarr_queue = queue.get('records', [])
radarr_queue_tmdb = {item['movie']['tmdbId']: item for item in radarr_queue if item.get('movie')}
print(f"Queue count: {len(radarr_queue)}")
for item in radarr_queue:
    m = item.get('movie', {})
    print(f"  [{item.get('status')}] {m.get('title')} ({m.get('year')}) tmdbId:{m.get('tmdbId')}")

print("\n=== RADARR LIBRARY (all movies) ===")
r2 = requests.get(f'{RADARR_BASE}/api/v3/movie', headers=R_HEADERS)
all_movies = r2.json()
radarr_tmdb_map = {m['tmdbId']: m for m in all_movies}
has_file = [m for m in all_movies if m.get('hasFile')]
no_file_monitored = [m for m in all_movies if not m.get('hasFile') and m.get('monitored')]
print(f"Total in library: {len(all_movies)} | Has file: {len(has_file)} | Missing+monitored: {len(no_file_monitored)}")

# ── Jellyseerr: all movie requests ───────────────────────────────────────────

print("\n=== JELLYSEERR MOVIE REQUESTS ===")

# Status codes: 1=PENDING, 2=APPROVED, 3=DECLINED, 4=AVAILABLE, 5=PROCESSING, 6=PARTIALLY_AVAILABLE, 7=ERROR
STATUS_MAP = {1: 'PENDING', 2: 'APPROVED', 3: 'DECLINED', 4: 'AVAILABLE',
              5: 'PROCESSING', 6: 'PARTIAL', 7: 'ERROR'}

# Fetch all pages
page = 1
all_requests = []
while True:
    sr = requests.get(f'{SEERR_BASE}/api/v1/request',
                      headers=S_HEADERS,
                      params={'take': 100, 'skip': (page-1)*100, 'filter': 'all', 'sort': 'added'})
    if sr.status_code != 200:
        print(f"  Seerr API error: {sr.status_code} {sr.text[:200]}")
        break
    data = sr.json()
    results = data.get('results', [])
    all_requests.extend(results)
    total = data.get('pageInfo', {}).get('results', len(results))
    print(f"  Page {page}: got {len(results)} (total reported: {total})")
    if len(all_requests) >= total or not results:
        break
    page += 1

movie_requests = [req for req in all_requests if req.get('type') == 'movie']
print(f"\nTotal movie requests in Seerr: {len(movie_requests)}")

# ── Cross-reference ───────────────────────────────────────────────────────────

print("\n=== CROSS-REFERENCE: Seerr vs Radarr ===")

mismatches = []
for req in movie_requests:
    media = req.get('media', {})
    tmdb_id = media.get('tmdbId')
    seerr_status = media.get('status')  # media status
    req_status = req.get('status')      # request status
    title = media.get('title', f'tmdbId:{tmdb_id}')

    # What Radarr thinks
    radarr_movie = radarr_tmdb_map.get(tmdb_id)
    in_queue = tmdb_id in radarr_queue_tmdb

    if radarr_movie:
        has_file = radarr_movie.get('hasFile', False)
        monitored = radarr_movie.get('monitored', False)
        radarr_status = 'HAS_FILE' if has_file else ('IN_QUEUE' if in_queue else 'MISSING')
    else:
        radarr_status = 'NOT_IN_RADARR'

    seerr_status_str = STATUS_MAP.get(seerr_status, f'?{seerr_status}')

    # Flag mismatches
    mismatch = False
    reason = ''
    if seerr_status_str == 'AVAILABLE' and radarr_status != 'HAS_FILE':
        mismatch = True
        reason = 'Seerr=AVAILABLE but Radarr has no file'
    elif seerr_status_str in ('PROCESSING', 'APPROVED') and radarr_status == 'HAS_FILE':
        mismatch = True
        reason = 'Seerr=PROCESSING/APPROVED but Radarr already HAS file'
    elif seerr_status_str in ('PROCESSING', 'APPROVED') and radarr_status == 'NOT_IN_RADARR':
        mismatch = True
        reason = 'Seerr=PROCESSING/APPROVED but movie not in Radarr at all'
    elif seerr_status_str == 'PENDING' and radarr_status in ('HAS_FILE', 'IN_QUEUE'):
        mismatch = True
        reason = f'Seerr=PENDING but Radarr status={radarr_status}'

    flag = '⚠️ ' if mismatch else '   '
    print(f"{flag}[Seerr:{seerr_status_str}] [Radarr:{radarr_status}] {title} (tmdb:{tmdb_id}){' | '+reason if reason else ''}")
    if mismatch:
        mismatches.append({'tmdbId': tmdb_id, 'title': title, 'seerr_status': seerr_status_str,
                           'radarr_status': radarr_status, 'reason': reason, 'req_id': req.get('id')})

print(f"\n=== SUMMARY ===")
print(f"Total movie requests: {len(movie_requests)}")
print(f"Mismatches found: {len(mismatches)}")
for m in mismatches:
    print(f"  [{m['seerr_status']} vs {m['radarr_status']}] {m['title']} | {m['reason']}")
