#!/usr/bin/env python3
import sys
import json
import requests
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

def fetch_athlete_runs(athlete_id):
    athlete_info = ATHLETES[athlete_id]
    print(f"\n[*] Fetching {athlete_info['name']} ({athlete_id})...")

    all_runs = []
    offset = 0
    batch_size = 100

    while True:
        params = {
            'athleteNumber': athlete_id,
            'offset': offset,
            'nbRecords': batch_size
        }

        try:
            response = requests.get(PARKRUN_API, params=params, headers=HEADERS, timeout=30)
            print(f"[*] HTTP status: {response.status_code}")
            print(f"[*] Content-Type: {response.headers.get('Content-Type', 'unknown')}")
            print(f"[*] Response (first 1000 chars): {response.text[:1000]}")
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            print(f"[-] Request error at offset {offset}: {e}")
            break
        except json.JSONDecodeError as e:
            print(f"[-] JSON decode error at offset {offset}: {e}")
            break

        # Response structure: {"data": {"Results": [...]}}
        print(f"[*] Top-level keys: {list(data.keys())}")
        results = data.get('data', {}).get('Results', [])
        print(f"[+] Got {len(results)} runs at offset {offset}")

        if not results:
            break

        all_runs.extend(results)

        if len(results) < batch_size:
            break

        offset += batch_size

    print(f"[+] Total runs fetched: {len(all_runs)}")
    return all_runs


def parse_runs(raw_runs):
    if raw_runs:
        print(f"[*] First item keys: {list(raw_runs[0].keys())}")
        print(f"[*] First item: {json.dumps(raw_runs[0], indent=2)}")

    runs = []
    for item in raw_runs:
        # Field names from parkrun AJAX API
        date_str = item.get('EventDate') or item.get('date', '')
        course = item.get('EventLongName') or item.get('EventName') or item.get('event', '')

        if not date_str or not course:
            continue

        letter = course[0].upper()
        runs.append({
            'date': date_str,
            'course': course,
            'time': item.get('RunTime') or item.get('time', ''),
            'letter': letter
        })

    print(f"[+] Parsed {len(runs)} valid runs")
    return runs


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
    print("=" * 70)
    print("PARKRUN DATA SCRAPER - Direct API")
    print("=" * 70)

    all_data = {}

    for athlete_id, athlete_info in ATHLETES.items():
        raw_runs = fetch_athlete_runs(athlete_id)

        if not raw_runs:
            print(f"[!] No runs fetched for {athlete_info['name']}")
            continue

        runs = parse_runs(raw_runs)

        if not runs:
            print(f"[!] No runs parsed for {athlete_info['name']}")
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

        print(f"\n[+] {athlete_info['name']} Summary:")
        for alph_key, alph_data in alphabet_status.items():
            alph_num = alph_key.split('_')[1]
            letters_str = ', '.join(alph_data['letters'][:5]) + ('...' if len(alph_data['letters']) > 5 else '')
            print(f"    Alphabet {alph_num}: {alph_data['completed']}/26 ({letters_str})")

    if all_data:
        with open('parkrun-data.json', 'w') as f:
            json.dump(all_data, f, indent=2)
        print(f"\n[+] Saved to parkrun-data.json")
        sys.exit(0)
    else:
        print(f"\n[!] No data collected")
        sys.exit(1)


if __name__ == '__main__':
    main()
