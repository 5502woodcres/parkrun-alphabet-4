#!/usr/bin/env python3
"""Parkrun scraper: deploys a minimal actor to Apify's cloud to bypass AWS WAF."""
import sys
import json
import os
import requests
import time
import traceback
from datetime import datetime

ATHLETES = {
    '3934942': {'name': 'Lisa', 'location': 'Chepstow'},
    '2475659': {'name': 'Beth', 'location': 'Cheltenham'}
}

PARKRUN_AJAX = 'https://www.parkrun.org.uk/results/athleteresultshistory/'
APIFY_BASE = 'https://api.apify.com/v2'
ACTOR_NAME = 'parkrun-data-fetcher'

# Runs on Apify's servers (trusted IPs that bypass parkrun WAF)
ACTOR_JS = """\
import { Actor } from 'apify';

await Actor.init();
const { athleteIds, baseUrl, headers } = await Actor.getInput();
const results = {};

for (const athleteId of athleteIds) {
    console.log(`Fetching athlete ${athleteId}...`);
    const allRuns = [];
    let offset = 0;
    while (true) {
        const url = `${baseUrl}?athleteNumber=${athleteId}&offset=${offset}&nbRecords=100`;
        const resp = await fetch(url, { headers });
        console.log(`  offset=${offset}: HTTP ${resp.status}`);
        if (!resp.ok) { console.log('  body:', (await resp.text()).slice(0, 200)); break; }
        const data = await resp.json();
        const runs = data?.data?.Results ?? [];
        console.log(`  got ${runs.length} runs`);
        allRuns.push(...runs);
        if (runs.length < 100) break;
        offset += 100;
    }
    results[athleteId] = allRuns;
    console.log(`Total for ${athleteId}: ${allRuns.length}`);
}

await Actor.setValue('OUTPUT', results);
await Actor.exit();
"""

PACKAGE_JSON = json.dumps({
    "name": "parkrun-data-fetcher",
    "version": "0.0.1",
    "type": "module",
    "dependencies": {"apify": "^3.0.0"}
})

LOG = []


def log(msg):
    print(msg)
    LOG.append(str(msg))


def save_debug(extra=None):
    debug = {'log': LOG}
    if extra:
        debug.update(extra)
    with open('debug-scraper.json', 'w') as f:
        json.dump(debug, f, indent=2, default=str)


def _auth_headers(token):
    return {'Authorization': f'Bearer {token}'}


def api_get(path, token):
    r = requests.get(f'{APIFY_BASE}{path}', headers=_auth_headers(token), timeout=30)
    r.raise_for_status()
    return r.json()


def api_post(path, token, data=None, extra_params=None):
    params = extra_params or {}
    r = requests.post(
        f'{APIFY_BASE}{path}',
        params=params,
        headers=_auth_headers(token),
        json=data,
        timeout=60
    )
    if not r.ok:
        log(f"[-] API error {r.status_code}: {r.text[:300]}")
    r.raise_for_status()
    return r.json()


def api_put(path, token, data=None):
    r = requests.put(
        f'{APIFY_BASE}{path}',
        headers=_auth_headers(token),
        json=data,
        timeout=60
    )
    if not r.ok:
        log(f"[-] API error {r.status_code}: {r.text[:300]}")
    r.raise_for_status()
    return r.json()


SOURCE_FILES_PAYLOAD = {
    'versionNumber': '0.0',
    'sourceType': 'SOURCE_FILES',
    'buildTag': 'latest',
    'sourceFiles': [
        {'name': 'src/main.js', 'format': 'TEXT', 'content': ACTOR_JS},
        {'name': 'package.json', 'format': 'TEXT', 'content': PACKAGE_JSON},
    ]
}


def build_actor(token, actor_id):
    """Upload/update source code and build the actor. Returns actor_id."""
    try:
        api_post(f'/acts/{actor_id}/versions', token, SOURCE_FILES_PAYLOAD)
        log("[+] Source version created")
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 403 and 'version-already-exists' in (e.response.text or ''):
            log("[*] Version 0.0 already exists — updating via PUT")
            api_put(f'/acts/{actor_id}/versions/0.0', token, SOURCE_FILES_PAYLOAD)
            log("[+] Source version updated")
        else:
            raise
    log("[+] Source uploaded")

    build_id = api_post(f'/acts/{actor_id}/builds', token, extra_params={
        'version': '0.0', 'tag': 'latest'
    })['data']['id']
    log(f"[*] Building actor (id={build_id})...")

    for i in range(60):
        time.sleep(10)
        build = api_get(f'/actor-builds/{build_id}', token)['data']
        status = build['status']
        log(f"[*]   build status: {status} ({(i+1)*10}s)")
        if status == 'SUCCEEDED':
            log("[+] Build succeeded")
            return actor_id
        if status in ['FAILED', 'ABORTED', 'TIMED-OUT']:
            raise Exception(f"Build failed: {status}\n{build.get('log', '')}")

    raise Exception("Build timed out")


def get_or_create_actor(token):
    """Return actor ID with a valid latest build, creating/rebuilding if needed."""
    # Check for existing actor
    actors = api_get('/acts?my=true&limit=100', token).get('data', {}).get('items', [])
    actor_id = None
    for actor in actors:
        if actor['name'] == ACTOR_NAME:
            actor_id = actor['id']
            log(f"[+] Found existing actor: {actor_id}")
            break

    if actor_id:
        # Verify it has a successful 'latest' build
        try:
            builds = api_get(f'/acts/{actor_id}/builds?tag=latest&limit=1', token)
            items = builds.get('data', {}).get('items', [])
            if items and items[0].get('status') == 'SUCCEEDED':
                log(f"[+] Actor has valid latest build — skipping rebuild")
                return actor_id
            log(f"[!] No valid latest build found — rebuilding actor")
        except Exception as e:
            log(f"[!] Could not check builds: {e} — rebuilding actor")
        return build_actor(token, actor_id)

    # Create actor from scratch
    log("[*] Creating Apify actor...")
    actor_id = api_post('/acts', token, {
        'name': ACTOR_NAME,
        'isPublic': False,
        'defaultRunOptions': {'timeoutSecs': 180, 'memoryMbytes': 256}
    })['data']['id']
    log(f"[+] Actor created: {actor_id}")
    return build_actor(token, actor_id)


def run_actor(token, actor_id):
    """Run the actor and return {athlete_id: [run_dicts]}."""
    run_input = {
        'athleteIds': list(ATHLETES.keys()),
        'baseUrl': PARKRUN_AJAX,
        'headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Language': 'en-GB,en;q=0.9',
            'Referer': 'https://www.parkrun.org.uk/',
            'X-Requested-With': 'XMLHttpRequest',
        }
    }

    log(f"[*] Running actor {actor_id}...")
    run_id = api_post(f'/acts/{actor_id}/runs', token, run_input)['data']['id']
    log(f"[*] Run ID: {run_id}")

    # Poll for completion
    for i in range(36):  # 6 minutes max
        time.sleep(10)
        run = api_get(f'/actor-runs/{run_id}', token)['data']
        status = run['status']
        log(f"[*]   run status: {status} ({(i+1)*10}s)")
        if status == 'SUCCEEDED':
            break
        if status in ['FAILED', 'ABORTED', 'TIMED-OUT']:
            raise Exception(f"Run failed: {status}")
    else:
        raise Exception("Run timed out")

    # Get OUTPUT from key-value store
    kv_id = run['defaultKeyValueStoreId']
    log(f"[*] Fetching output from KV store {kv_id}...")
    r = requests.get(
        f'{APIFY_BASE}/key-value-stores/{kv_id}/records/OUTPUT',
        headers=_auth_headers(token),
        timeout=30
    )
    r.raise_for_status()
    return r.json()


def parse_runs(raw_runs):
    if not raw_runs:
        return None
    runs = []
    for item in raw_runs:
        date_str = (item.get('EventDate') or item.get('RunDate') or
                    item.get('date') or item.get('eventDate') or '')
        course = (item.get('EventLongName') or item.get('EventName') or
                  item.get('event') or item.get('courseName') or
                  item.get('name') or '')
        if not date_str or not course:
            continue
        letter = course[0].upper()
        runs.append({
            'date': str(date_str),
            'course': course,
            'time': str(item.get('RunTime') or item.get('time') or ''),
            'letter': letter
        })
    log(f"[+] Parsed {len(runs)} valid runs")
    return runs if runs else None


def group_by_alphabet(runs):
    if not runs:
        return {}, {}, {}
    letters = {}
    for run in runs:
        letter = run['letter']
        if letter not in letters:
            letters[letter] = []
        letters[letter].append(run)
    alphabet_map = {}
    for letter in sorted(letters.keys()):
        for idx, run in enumerate(sorted(letters[letter], key=lambda x: x['date'])):
            alphabet_num = idx + 1
            if alphabet_num not in alphabet_map:
                alphabet_map[alphabet_num] = []
            alphabet_map[alphabet_num].append(letter)
    result = {}
    for alphabet_num in range(1, 5):
        done = set(alphabet_map.get(alphabet_num, []))
        result[f'alphabet_{alphabet_num}'] = {
            'letters': sorted(list(done)),
            'completed': len(done),
            'remaining': sorted([chr(i) for i in range(65, 91) if chr(i) not in done])
        }
    return result, alphabet_map, letters


def main():
    log("=" * 70)
    log("PARKRUN DATA SCRAPER - Apify Actor API")
    log("=" * 70)

    apify_token = os.environ.get('APIFY_TOKEN')
    if not apify_token:
        log("[-] APIFY_TOKEN not set — aborting")
        save_debug()
        sys.exit(1)
    log(f"[*] APIFY_TOKEN present, length={len(apify_token)}")

    try:
        actor_id = get_or_create_actor(apify_token)
        raw_output = run_actor(apify_token, actor_id)
    except Exception as e:
        log(f"[-] Actor error: {e}")
        log(traceback.format_exc())
        save_debug()
        sys.exit(1)

    log(f"[*] Raw output keys: {list(raw_output.keys())}")

    all_data = {}
    for athlete_id, athlete_info in ATHLETES.items():
        raw_runs = raw_output.get(athlete_id, [])
        log(f"\n[*] {athlete_info['name']}: {len(raw_runs)} raw runs")

        if not raw_runs:
            log(f"[!] No runs for {athlete_info['name']}")
            continue

        if raw_runs and isinstance(raw_runs[0], dict):
            log(f"[*] First run keys: {list(raw_runs[0].keys())}")
            log(f"[*] First run: {json.dumps(raw_runs[0], indent=2, default=str)}")

        runs = parse_runs(raw_runs)
        if not runs:
            log(f"[!] No valid runs parsed for {athlete_info['name']}")
            continue

        alphabet_status, alphabet_map, letters_data = group_by_alphabet(runs)

        all_data[athlete_id] = {
            'name': athlete_info['name'],
            'athlete_id': athlete_id,
            'location': athlete_info['location'],
            'total_runs': len(runs),
            'alphabet_status': alphabet_status,
            'runs_per_letter': {l: len(r) for l, r in letters_data.items()},
            'last_updated': datetime.now().isoformat()
        }

        log(f"\n[+] {athlete_info['name']} Summary:")
        for alph_key, alph_data in alphabet_status.items():
            alph_num = alph_key.split('_')[1]
            letters_str = ', '.join(alph_data['letters'][:5]) + ('...' if len(alph_data['letters']) > 5 else '')
            log(f"    Alphabet {alph_num}: {alph_data['completed']}/26 ({letters_str})")

    save_debug()

    if all_data:
        with open('parkrun-data.json', 'w') as f:
            json.dump(all_data, f, indent=2)
        log(f"\n[+] Saved to parkrun-data.json")
        sys.exit(0)
    else:
        log(f"\n[!] No data collected")
        sys.exit(1)


if __name__ == '__main__':
    main()
