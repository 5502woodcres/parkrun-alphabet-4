#!/usr/bin/env python3
"""Parkrun scraper using Playwright with stealth mode to bypass AWS WAF."""
import sys
import json
import traceback
from datetime import datetime

ATHLETES = {
    '3934942': {'name': 'Lisa', 'location': 'Chepstow'},
    '2475659': {'name': 'Beth', 'location': 'Cheltenham'}
}

LOG = []


def log(msg):
    print(msg)
    LOG.append(msg)


def save_debug(extra=None):
    debug = {'log': LOG}
    if extra:
        debug.update(extra)
    with open('debug-scraper.json', 'w') as f:
        json.dump(debug, f, indent=2, default=str)


def fetch_athlete_runs(playwright, athlete_id):
    athlete_info = ATHLETES[athlete_id]
    name = athlete_info['name']
    log(f"\n[*] Fetching {name} ({athlete_id})...")

    browser = playwright.chromium.launch(
        headless=True,
        args=[
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-setuid-sandbox',
            '--disable-blink-features=AutomationControlled',
            '--disable-infobars',
            '--window-size=1920,1080',
        ]
    )

    context = browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        viewport={'width': 1920, 'height': 1080},
        extra_http_headers={'Accept-Language': 'en-GB,en;q=0.9'}
    )

    # Apply stealth patches to hide automation fingerprints
    try:
        from playwright_stealth import stealth_sync
        page = context.new_page()
        stealth_sync(page)
        log("[+] playwright-stealth applied")
    except ImportError:
        log("[!] playwright-stealth not installed, proceeding without it")
        page = context.new_page()

    # Override navigator.webdriver manually
    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['en-GB', 'en']});
        window.chrome = {runtime: {}};
    """)

    log(f"[*] Visiting parkrun homepage to pass WAF...")
    try:
        response = page.goto(
            'https://www.parkrun.org.uk/',
            wait_until='domcontentloaded',
            timeout=45000
        )
        log(f"[+] Homepage: HTTP {response.status if response else 'unknown'}")
        page.wait_for_timeout(5000)  # Allow WAF JS challenge to complete
        title = page.title()
        log(f"[+] Page title: {title}")
    except Exception as e:
        log(f"[-] Homepage load error: {e}")
        browser.close()
        return None

    # Grab cookies after WAF challenge
    cookies = context.cookies()
    waf_cookies = [c for c in cookies if 'waf' in c['name'].lower() or 'aws' in c['name'].lower()]
    log(f"[+] Cookies set: {len(cookies)} total, {len(waf_cookies)} WAF-related")
    log(f"[+] Cookie names: {[c['name'] for c in cookies]}")

    all_results = []
    offset = 0
    batch_size = 100

    while True:
        log(f"[*] API request: offset={offset}...")
        try:
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
        except Exception as e:
            log(f"[-] Request error: {e}")
            break

        log(f"[+] API HTTP {response.status}")

        text = response.text()
        log(f"[+] Response (first 300 chars): {text[:300]}")

        if response.status != 200:
            break

        try:
            data = json.loads(text)
        except Exception as e:
            log(f"[-] JSON parse error: {e}")
            break

        results = data.get('data', {}).get('Results', [])
        log(f"[+] Got {len(results)} results at offset={offset}")

        if not results:
            log(f"[*] Top-level keys: {list(data.keys())}")
            if 'data' in data:
                log(f"[*] data sub-keys: {list(data['data'].keys()) if isinstance(data['data'], dict) else type(data['data'])}")
            break

        all_results.extend(results)

        if len(results) < batch_size:
            break
        offset += batch_size

    browser.close()
    log(f"[+] Total runs fetched: {len(all_results)}")
    return all_results


def parse_runs(raw_runs):
    if not raw_runs:
        return None

    log(f"[*] First item keys: {list(raw_runs[0].keys())}")
    log(f"[*] First item: {json.dumps(raw_runs[0], indent=2, default=str)}")

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
    from playwright.sync_api import sync_playwright

    log("=" * 70)
    log("PARKRUN DATA SCRAPER - Playwright + Stealth")
    log("=" * 70)

    all_data = {}

    try:
        with sync_playwright() as playwright:
            for athlete_id, athlete_info in ATHLETES.items():
                try:
                    raw_runs = fetch_athlete_runs(playwright, athlete_id)
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

    except Exception as e:
        log(f"[-] Fatal error: {e}")
        log(traceback.format_exc())

    save_debug()

    if all_data:
        with open('parkrun-data.json', 'w') as f:
            json.dump(all_data, f, indent=2)
        log(f"\n[+] Saved to parkrun-data.json")
        sys.exit(0)
    else:
        log(f"\n[!] No data collected — see debug-scraper.json")
        sys.exit(1)


if __name__ == '__main__':
    main()
