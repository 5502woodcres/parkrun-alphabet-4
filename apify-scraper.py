#!/usr/bin/env python3
"""Parkrun scraper using Playwright to bypass AWS WAF."""
import sys
import json
from datetime import datetime

ATHLETES = {
    '3934942': {'name': 'Lisa', 'location': 'Chepstow'},
    '2475659': {'name': 'Beth', 'location': 'Cheltenham'}
}


def fetch_athlete_runs(playwright, athlete_id):
    from playwright.sync_api import sync_playwright

    athlete_info = ATHLETES[athlete_id]
    name = athlete_info['name']
    print(f"\n[*] Fetching {name} ({athlete_id})...")

    browser = playwright.chromium.launch(
        headless=True,
        args=[
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-setuid-sandbox',
            '--disable-blink-features=AutomationControlled',
        ]
    )
    context = browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        extra_http_headers={'Accept-Language': 'en-GB,en;q=0.9'}
    )

    page = context.new_page()

    # Visit parkrun homepage to pass AWS WAF challenge and get cookies
    print(f"[*] Visiting parkrun homepage to pass WAF...")
    page.goto('https://www.parkrun.org.uk/', wait_until='networkidle', timeout=60000)
    print(f"[+] Homepage loaded, WAF cookie set")

    all_results = []
    offset = 0
    batch_size = 100

    while True:
        print(f"[*] Requesting results at offset={offset}...")
        response = context.request.get(
            'https://www.parkrun.org.uk/results/athleteresultshistory/',
            params={
                'athleteNumber': athlete_id,
                'offset': offset,
                'nbRecords': batch_size
            },
            headers={
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Referer': 'https://www.parkrun.org.uk/',
            }
        )

        print(f"[+] HTTP {response.status}")

        if response.status != 200:
            text = response.text()
            print(f"[-] Non-200 response. First 500 chars: {text[:500]}")
            break

        try:
            data = response.json()
        except Exception as e:
            print(f"[-] JSON parse error: {e}")
            print(f"    Response: {response.text()[:500]}")
            break

        results = data.get('data', {}).get('Results', [])
        print(f"[+] Got {len(results)} results")

        if not results:
            # Print top-level keys to help debug structure
            print(f"[*] Response top-level keys: {list(data.keys())}")
            if 'data' in data:
                print(f"[*] data keys: {list(data['data'].keys())}")
            break

        all_results.extend(results)

        if len(results) < batch_size:
            break

        offset += batch_size

    browser.close()
    print(f"[+] Total fetched: {len(all_results)} runs")
    return all_results


def parse_runs(raw_runs):
    if not raw_runs:
        return None

    print(f"[*] First item keys: {list(raw_runs[0].keys())}")
    print(f"[*] First item sample: {json.dumps(raw_runs[0], indent=2, default=str)}")

    runs = []
    for item in raw_runs:
        # Try multiple possible field names
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

    print(f"[+] Parsed {len(runs)} valid runs")
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
    from playwright.sync_api import sync_playwright

    print("=" * 70)
    print("PARKRUN DATA SCRAPER - Playwright Browser")
    print("=" * 70)

    all_data = {}

    with sync_playwright() as playwright:
        for athlete_id, athlete_info in ATHLETES.items():
            try:
                raw_runs = fetch_athlete_runs(playwright, athlete_id)
            except Exception as e:
                print(f"[-] Error fetching {athlete_info['name']}: {e}")
                import traceback
                traceback.print_exc()
                continue

            if not raw_runs:
                print(f"[!] No runs fetched for {athlete_info['name']}")
                continue

            runs = parse_runs(raw_runs)
            if not runs:
                print(f"[!] No valid runs parsed for {athlete_info['name']}")
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
