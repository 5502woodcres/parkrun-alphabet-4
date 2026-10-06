#!/usr/bin/env python3
import sys
import json
from datetime import datetime

APIFY_ACTOR_ID = '5lljkHZ8Jh1vf2NHc'

ATHLETES = {
    '3934942': {'name': 'Lisa', 'location': 'Chepstow'},
    '2475659': {'name': 'Beth', 'location': 'Cheltenham'}
}

def fetch_from_apify(athlete_id, token):
    from apify_client import ApifyClient

    client = ApifyClient(token)
    athlete_info = ATHLETES[athlete_id]
    print(f"\n[*] Fetching {athlete_info['name']} ({athlete_id})...")

    payload = {
        'mode': 'athlete-history',
        'athleteNumbers': [athlete_id],
        'country': 'org.uk'
    }

    run = client.actor(APIFY_ACTOR_ID).call(run_input=payload)
    print(f"[+] Run status: {run.get('status')}")

    items = list(client.dataset(run['defaultDatasetId']).iterate_items())
    print(f"[+] Got {len(items)} items")
    if items:
        print(f"[*] Sample item keys: {list(items[0].keys())}")
        print(f"[*] Sample: {json.dumps(items[0], indent=2)}")

    return {'items': items} if items else None

def parse_athlete_data(apify_response, athlete_id, athlete_info):
    if not apify_response:
        return None
    items = apify_response.get('items', [])
    if not items:
        print(f"[-] No items")
        return None

    runs = []
    for item in items:
        date_str = item.get('date')
        course = item.get('courseName') or item.get('course', '')
        if not date_str or not course:
            continue
        runs.append({
            'date': date_str,
            'course': course,
            'time': item.get('time', ''),
            'letter': course[0].upper()
        })
    print(f"[+] Parsed {len(runs)} runs")
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
    import os
    token = os.environ.get('APIFY_TOKEN')
    if not token:
        print("[!] APIFY_TOKEN not set")
        sys.exit(1)

    print("="*70)
    print("PARKRUN DATA SCRAPER")
    print("="*70)

    all_data = {}
    for athlete_id, athlete_info in ATHLETES.items():
        try:
            apify_response = fetch_from_apify(athlete_id, token)
        except Exception as e:
            print(f"[-] Error fetching {athlete_info['name']}: {e}")
            continue

        runs = parse_athlete_data(apify_response, athlete_id, athlete_info)
        if not runs:
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
        print(f"\n[!] No data")
        sys.exit(1)

if __name__ == '__main__':
    main()
