"""
Full reconciliation of Jellyseerr movie requests vs Radarr library/queue.
Uses raw base64 API key for Jellyseerr (X-Api-Key header).
"""
import requests
import json
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
SEERR_KEY = os.environ["SEERR_API_KEY"]
S_HEADERS = {'X-Api-Key': SEERR_KEY}

STATUS_MAP = {1: 'PENDING', 2: 'APPROVED', 3: 'DECLINED', 4: 'AVAILABLE',
              5: 'PROCESSING', 6: 'PARTIAL', 7: 'ERROR'}

# Media status codes (on the media object itself)
MEDIA_STATUS_MAP = {1: 'UNKNOWN', 2: 'PENDING', 3: 'PROCESSING', 4: 'PARTIAL', 5: 'AVAILABLE'}

# ── Radarr data ───────────────────────────────────────────────────────────────

r = requests.get(f'{RADARR_BASE}/api/v3/queue', headers=R_HEADERS,
                 params={'pageSize': 200, 'includeMovie': True})
radarr_queue_records = r.json().get('records', [])
radarr_queue_tmdb = {item['movie']['tmdbId']: item for item in radarr_queue_records if item.get('movie')}

r2 = requests.get(f'{RADARR_BASE}/api/v3/movie', headers=R_HEADERS)
all_radarr = r2.json()
radarr_tmdb_map = {m['tmdbId']: m for m in all_radarr}

# ── Jellyseerr: fetch all movie requests ─────────────────────────────────────

all_requests = []
page = 1
while True:
    sr = requests.get(f'{SEERR_BASE}/api/v1/request', headers=S_HEADERS,
                      params={'take': 100, 'skip': (page - 1) * 100, 'filter': 'all', 'sort': 'added'})
    data = sr.json()
    results = data.get('results', [])
    all_requests.extend(results)
    total = data.get('pageInfo', {}).get('results', 0)
    if len(all_requests) >= total or not results:
        break
    page += 1

movie_requests = [r for r in all_requests if r.get('type') == 'movie']
tv_requests = [r for r in all_requests if r.get('type') == 'tv']

print(f"Jellyseerr total requests: {len(all_requests)} ({len(movie_requests)} movies, {len(tv_requests)} TV)")
print(f"Radarr library: {len(all_radarr)} total | {sum(1 for m in all_radarr if m.get('hasFile'))} with files | {len(radarr_queue_records)} in queue")

# ── Cross-reference ───────────────────────────────────────────────────────────

print("\n=== ALL MOVIE REQUESTS (Seerr vs Radarr) ===")
mismatches = []

for req in movie_requests:
    media = req.get('media', {})
    tmdb_id = media.get('tmdbId')
    media_status = MEDIA_STATUS_MAP.get(media.get('status'), f"?{media.get('status')}")
    req_status = STATUS_MAP.get(req.get('status'), f"?{req.get('status')}")
    title = media.get('title', f'tmdbId:{tmdb_id}')

    radarr_movie = radarr_tmdb_map.get(tmdb_id)
    in_queue = tmdb_id in radarr_queue_tmdb

    if radarr_movie:
        has_file = radarr_movie.get('hasFile', False)
        if has_file:
            radarr_str = 'HAS_FILE'
        elif in_queue:
            q_item = radarr_queue_tmdb[tmdb_id]
            radarr_str = f"IN_QUEUE({q_item.get('status')})"
        else:
            radarr_str = 'MISSING'
    else:
        radarr_str = 'NOT_IN_RADARR'

    # Detect mismatches
    reason = None
    if media_status == 'AVAILABLE' and radarr_str != 'HAS_FILE':
        reason = f'Seerr shows AVAILABLE but Radarr={radarr_str}'
    elif media_status in ('PROCESSING', 'PENDING') and radarr_str == 'HAS_FILE':
        reason = 'Seerr shows PROCESSING/PENDING but Radarr already has the file'
    elif media_status in ('PROCESSING', 'PENDING') and radarr_str == 'NOT_IN_RADARR':
        reason = 'Seerr shows PROCESSING/PENDING but movie missing from Radarr entirely'
    elif media_status == 'UNKNOWN' and radarr_str in ('HAS_FILE', 'IN_QUEUE(queued)'):
        reason = f'Seerr status=UNKNOWN but Radarr={radarr_str}'

    flag = '⚠️ ' if reason else '   '
    print(f"{flag}[media:{media_status}|req:{req_status}] [radarr:{radarr_str}] {title} (tmdb:{tmdb_id})")
    if reason:
        print(f"       MISMATCH: {reason}")
        mismatches.append({
            'req_id': req.get('id'),
            'tmdb_id': tmdb_id,
            'title': title,
            'media_status': media_status,
            'req_status': req_status,
            'radarr_status': radarr_str,
            'reason': reason,
        })

print(f"\n=== SUMMARY ===")
print(f"Movie requests in Seerr: {len(movie_requests)}")
print(f"Mismatches: {len(mismatches)}")
for m in mismatches:
    print(f"  req#{m['req_id']} | [{m['media_status']}] vs [{m['radarr_status']}] | {m['title']} | {m['reason']}")

print(f"\n=== TV REQUESTS (summary) ===")
tv_status_counts = {}
for req in tv_requests:
    ms = MEDIA_STATUS_MAP.get(req.get('media', {}).get('status'), '?')
    tv_status_counts[ms] = tv_status_counts.get(ms, 0) + 1
for k, v in tv_status_counts.items():
    print(f"  {k}: {v}")
