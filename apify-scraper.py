#!/usr/bin/env python3
"""Parkrun scraper: Python Playwright headless browser to bypass AWS WAF JS challenge."""
import sys
import json
import os
import traceback
from datetime import datetime

ATHLETES = {
    '3934942': {'name': 'Lisa', 'location': 'Chepstow'},
    '2475659': {'name': 'Beth', 'location': 'Cheltenham'}
}

PARKRUN_AJAX = 'https://www.parkrun.org.uk/results/athleteresultshistory/'

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


def fetch_athlete_runs(page, athlete_id):
    """Fetch all runs for an athlete using an existing Playwright page."""
    all_runs = []
    offset = 0

    while True:
        url = (f"{PARKRUN_AJAX}?athleteNumber={athlete_id}"
               f"&offset={offset}&nbRecords=100")
        log(f"[*]   GET {url}")

        response = page.request.get(url, headers={
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Language': 'en-GB,en;q=0.9',
            'Referer': 'https://www.parkrun.org.uk/',
            'X-Requested-With': 'XMLHttpRequest',
        }, timeout=30000)

        log(f"[*]   HTTP {response.status}")
        body_text = response.text()

        if not response.ok:
            log(f"[!]   Error body: {body_text[:300]}")
            break

        # If we got HTML instead of JSON, the WAF challenge page wasn't solved
        if body_text.lstrip().startswith('<'):
            title = 'N/A'
            if '<title>' in body_text:
                title = body_text[body_text.find('<title>')+7:body_text.find('</title>')][:80]
            log(f"[!]   Got HTML (WAF challenge?) — title: {title}")
            break

        try:
            data = json.loads(body_text)
        except json.JSONDecodeError as e:
            log(f"[!]   JSON decode error: {e} — body: {body_text[:200]}")
            break

        runs = (data.get('data') or {}).get('Results') or []
        log(f"[*]   Got {len(runs)} runs")
        all_runs.extend(runs)

        if len(runs) < 100:
            break
        offset += 100

    return all_runs


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


def launch_browser(pw, proxy_config=None):
    """Launch Chromium with optional proxy."""
    launch_args = {
        'headless': True,
        'args': ['--no-sandbox', '--disable-setuid-sandbox'],
    }
    if proxy_config:
        launch_args['proxy'] = proxy_config
    return pw.chromium.launch(**launch_args)


def main():
    log("=" * 70)
    log("PARKRUN DATA SCRAPER - Python Playwright")
    log("=" * 70)

    # APIFY_TOKEN is optional — used for residential proxy if available
    apify_token = os.environ.get('APIFY_TOKEN', '')
    use_proxy = bool(apify_token)
    if use_proxy:
        log(f"[*] APIFY_TOKEN present (len={len(apify_token)}) — will use residential proxy")
    else:
        log("[*] No APIFY_TOKEN — trying direct connection (no proxy)")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("[-] playwright not installed")
        save_debug()
        sys.exit(1)

    all_data = {}

    proxy_config = None
    if use_proxy:
        proxy_config = {
            'server': 'http://proxy.apify.com:8000',
            'username': 'groups-RESIDENTIAL',
            'password': apify_token,
        }

    try:
        with sync_playwright() as pw:
            browser = launch_browser(pw, proxy_config)
            context = browser.new_context(
                user_agent=(
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                ),
                viewport={'width': 1280, 'height': 800},
                locale='en-GB',
            )

            # Warm up: visit homepage so WAF can execute its JS challenge
            # and set the aws-waf-token cookie in the browser context.
            log("[*] Warming up: visiting parkrun.org.uk homepage...")
            warmup_page = context.new_page()
            try:
                warmup_page.goto(
                    'https://www.parkrun.org.uk/',
                    wait_until='domcontentloaded',
                    timeout=60000
                )
                log(f"[*] Homepage title: {warmup_page.title()}")
                # Allow JS WAF challenge to execute and set cookies
                warmup_page.wait_for_timeout(8000)
                cookies = context.cookies()
                log(f"[*] Cookies after warmup: {len(cookies)}")
                for c in cookies:
                    log(f"[*]   Cookie: {c['name']}={c['value'][:20]}... domain={c['domain']}")
            except Exception as e:
                log(f"[!] Homepage warmup error: {e}")
            finally:
                warmup_page.close()

            # Fetch data for each athlete
            page = context.new_page()
            for athlete_id, athlete_info in ATHLETES.items():
                log(f"\n[*] Fetching {athlete_info['name']} (athlete {athlete_id})...")
                try:
                    raw_runs = fetch_athlete_runs(page, athlete_id)
                except Exception as e:
                    log(f"[-] Error fetching {athlete_info['name']}: {e}")
                    log(traceback.format_exc())
                    continue

                log(f"[*] {athlete_info['name']}: {len(raw_runs)} raw runs")
                if not raw_runs:
                    log(f"[!] No runs returned for {athlete_info['name']}")
                    continue

                if raw_runs and isinstance(raw_runs[0], dict):
                    log(f"[*] First run keys: {list(raw_runs[0].keys())}")
                    log(f"[*] First run: {json.dumps(raw_runs[0], default=str)[:300]}")

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
                    'runs_per_letter': {ltr: len(r) for ltr, r in letters_data.items()},
                    'last_updated': datetime.now().isoformat()
                }

                log(f"\n[+] {athlete_info['name']} Summary:")
                for alph_key, alph_data in alphabet_status.items():
                    alph_num = alph_key.split('_')[1]
                    letters_str = ', '.join(alph_data['letters'][:5])
                    if len(alph_data['letters']) > 5:
                        letters_str += '...'
                    log(f"    Alphabet {alph_num}: {alph_data['completed']}/26 ({letters_str})")

            page.close()
            browser.close()

    except Exception as e:
        log(f"[-] Playwright error: {e}")
        log(traceback.format_exc())
        save_debug()
        sys.exit(1)

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
