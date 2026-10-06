#!/usr/bin/env python3
"""Parkrun scraper: uses Apify proxy to bypass AWS WAF, then calls AJAX endpoint."""
import sys
import json
import os
import requests
import traceback
from datetime import datetime

ATHLETES = {
    '3934942': {'name': 'Lisa', 'location': 'Chepstow'},
    '2475659': {'name': 'Beth', 'location': 'Cheltenham'}
}

PARKRUN_API = 'https://www.parkrun.org.uk/results/athleteresultshistory/'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'en-GB,en;q=0.9',
    'Referer': 'https://www.parkrun.org.uk/',
    'X-Requested-With': 'XMLHttpRequest',
}

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


def make_session(apify_token):
    """Create a requests session routed through Apify proxy."""
    session = requests.Session()
    if apify_token:
        # Apify proxy: auto mode picks best proxy type for the target URL
        proxy_url = f'http://auto:{apify_token}@proxy.apify.com:8000'
        session.proxies = {'http': proxy_url, 'https': proxy_url}
        log("[*] Using Apify proxy to bypass WAF")
    else:
        log("[!] No APIFY_TOKEN — direct requests (may hit WAF)")
    session.headers.update(HEADERS)
    return session


def fetch_athlete_runs(session, athlete_id):
    athlete_info = ATHLETES[athlete_id]
    name = athlete_info['name']
    log(f"\n[*] Fetching {name} ({athlete_id})...")

    all_results = []
    offset = 0
    batch_size = 100

    while True:
        params = {
            'athleteNumber': athlete_id,
            'offset': offset,
            'nbRecords': batch_size
        }

        try:
            r = session.get(PARKRUN_API, params=params, timeout=30)
        except requests.RequestException as e:
            log(f"[-] Request error at offset={offset}: {e}")
            break

        log(f"[+] HTTP {r.status_code} | Content-Type: {r.headers.get('Content-Type', '?')}")

        if r.status_code != 200:
            log(f"[-] Non-200. Response (first 500): {r.text[:500]}")
            break

        try:
            data = r.json()
        except Exception as e:
            log(f"[-] JSON parse error: {e} | Response: {r.text[:500]}")
            break

        log(f"[*] Top-level keys: {list(data.keys())}")

        results = data.get('data', {}).get('Results', [])
        log(f"[+] Got {len(results)} results at offset={offset}")

        if not results:
            if 'data' in data:
                sub = data['data']
                log(f"[*] data sub-keys: {list(sub.keys()) if isinstance(sub, dict) else type(sub)}")
            break

        if offset == 0 and results:
            log(f"[*] First result keys: {list(results[0].keys())}")
            log(f"[*] First result: {json.dumps(results[0], indent=2, default=str)}")

        all_results.extend(results)

        if len(results) < batch_size:
            break
        offset += batch_size

    log(f"[+] Total fetched: {len(all_results)} runs")
    return all_results


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
    log("PARKRUN DATA SCRAPER - Apify Proxy + Direct AJAX")
    log("=" * 70)

    apify_token = os.environ.get('APIFY_TOKEN')
    log(f"[*] APIFY_TOKEN present: {bool(apify_token)}, length: {len(apify_token) if apify_token else 0}")
    session = make_session(apify_token)

    all_data = {}

    for athlete_id, athlete_info in ATHLETES.items():
        try:
            raw_runs = fetch_athlete_runs(session, athlete_id)
        except Exception as e:
            log(f"[-] Error fetching {athlete_info['name']}: {e}")
            log(traceback.format_exc())
            continue

        if not raw_runs:
            log(f"[!] No runs fetched for {athlete_info['name']}")
            continue

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
