#!/usr/bin/env python3
"""Parkrun scraper: Playwright headless browser to bypass AWS WAF JS challenge.

Strategy:
  1. If APIFY_TOKEN set → use Apify residential proxy (bypasses IP block)
  2. If proxy fails or no token → try direct with playwright-stealth (avoids headless detection)
"""
import sys
import json
import os
import traceback
import urllib.request
import urllib.error
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


def apply_stealth(page):
    """Apply basic stealth patches to avoid headless browser detection."""
    try:
        from playwright_stealth import stealth_sync
        stealth_sync(page)
        log("[*] playwright-stealth applied")
    except ImportError:
        # Manual stealth: remove webdriver flag, spoof plugins etc.
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-GB', 'en'] });
            window.chrome = { runtime: {} };
        """)
        log("[*] Manual stealth patches applied (playwright-stealth not installed)")


def warmup_context(context):
    """Visit parkrun homepage so WAF JS challenge can execute and set the token cookie."""
    log("[*] Warming up: visiting parkrun.org.uk homepage...")
    warmup_page = context.new_page()
    apply_stealth(warmup_page)
    try:
        warmup_page.goto(
            'https://www.parkrun.org.uk/',
            wait_until='domcontentloaded',
            timeout=60000
        )
        log(f"[*] Homepage title (initial): {warmup_page.title()}")

        # Wait for WAF JS challenge to execute and redirect
        try:
            warmup_page.wait_for_function(
                "document.title !== 'Human Verification'",
                timeout=20000
            )
            log(f"[*] Homepage title (after WAF): {warmup_page.title()}")
        except Exception:
            log(f"[!] WAF challenge did not resolve — title still: {warmup_page.title()}")

        warmup_page.wait_for_timeout(3000)
        cookies = context.cookies()
        log(f"[*] Cookies after warmup: {len(cookies)}")
        for c in cookies:
            name = c['name']
            val_preview = c['value'][:20] + '...' if len(c['value']) > 20 else c['value']
            log(f"[*]   Cookie: {name}={val_preview} domain={c['domain']}")
    except Exception as e:
        log(f"[!] Homepage warmup error: {e}")
    finally:
        warmup_page.close()


def fetch_athlete_via_html(context, athlete_id):
    """Navigate to the HTML athlete results page and parse the table.

    Used as fallback when the AJAX endpoint is WAF-blocked (405).
    The HTML page returns 200 + JS challenge, which Playwright can solve.
    """
    url = f'https://www.parkrun.org.uk/parkrunner/{athlete_id}/all/'
    log(f"[*] HTML fallback: navigating to {url}")
    page = context.new_page()
    apply_stealth(page)
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=60000)
        log(f"[*] HTML page title (initial): {page.title()}")

        # Wait for WAF JS challenge to redirect away
        try:
            page.wait_for_function(
                "document.title !== 'Human Verification'",
                timeout=20000
            )
            log(f"[*] HTML page title (after WAF): {page.title()}")
        except Exception:
            log(f"[!] WAF challenge did not resolve — title: {page.title()}")

        page.wait_for_timeout(3000)

        # Try to find the results table rows
        rows = page.query_selector_all('table#results tbody tr')
        if not rows:
            rows = page.query_selector_all('table.sortable tbody tr')
        if not rows:
            rows = page.query_selector_all('tbody tr')
        log(f"[*] HTML rows found: {len(rows)}")

        runs = []
        for row in rows:
            cells = row.query_selector_all('td')
            if len(cells) < 2:
                continue
            # parkrun table: Event | Run Date | Position | Time | Age Grade | PB
            course = cells[0].inner_text().strip()
            date_str = cells[1].inner_text().strip() if len(cells) > 1 else ''
            time_str = cells[3].inner_text().strip() if len(cells) > 3 else ''
            if not course or not date_str:
                continue
            letter = course[0].upper()
            runs.append({
                'date': date_str,
                'course': course,
                'time': time_str,
                'letter': letter
            })

        log(f"[*] HTML parsed {len(runs)} runs for athlete {athlete_id}")
        return runs
    except Exception as e:
        log(f"[-] HTML fetch error for {athlete_id}: {e}")
        return []
    finally:
        page.close()


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


def run_scraper(pw, proxy_config=None):
    """Run the full scrape, return dict of data or {} on failure."""
    label = f"proxy={proxy_config['server']}" if proxy_config else "direct (no proxy)"
    log(f"\n[*] Attempting scrape: {label}")

    launch_kwargs = {
        'headless': True,
        'args': ['--no-sandbox', '--disable-setuid-sandbox'],
    }
    if proxy_config:
        launch_kwargs['proxy'] = proxy_config

    browser = pw.chromium.launch(**launch_kwargs)
    context = browser.new_context(
        user_agent=(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
        viewport={'width': 1280, 'height': 800},
        locale='en-GB',
    )

    try:
        warmup_context(context)

        all_data = {}
        page = context.new_page()
        apply_stealth(page)

        for athlete_id, athlete_info in ATHLETES.items():
            log(f"\n[*] Fetching {athlete_info['name']} (athlete {athlete_id})...")
            runs = None

            # Try AJAX endpoint first
            try:
                raw_runs = fetch_athlete_runs(page, athlete_id)
                log(f"[*] {athlete_info['name']}: {len(raw_runs)} raw runs via AJAX")
                if raw_runs and isinstance(raw_runs[0], dict):
                    log(f"[*] First run keys: {list(raw_runs[0].keys())}")
                    log(f"[*] First run: {json.dumps(raw_runs[0], default=str)[:300]}")
                if raw_runs:
                    runs = parse_runs(raw_runs)
            except Exception as e:
                log(f"[-] AJAX error for {athlete_info['name']}: {e}")

            # Fall back to HTML scraping if AJAX gave nothing
            if not runs:
                log(f"[*] Trying HTML fallback for {athlete_info['name']}...")
                html_runs = fetch_athlete_via_html(context, athlete_id)
                if html_runs:
                    runs = html_runs  # already parsed, just need parse_runs for date normalisation
                    log(f"[*] HTML fallback returned {len(runs)} runs")

            if not runs:
                log(f"[!] No runs obtained for {athlete_info['name']} (AJAX + HTML both failed)")
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
        return all_data

    finally:
        browser.close()


def main():
    log("=" * 70)
    log("PARKRUN DATA SCRAPER - Python Playwright")
    log("=" * 70)

    apify_token = os.environ.get('APIFY_TOKEN', '')
    if apify_token:
        prefix = apify_token[:10] if len(apify_token) >= 10 else apify_token
        log(f"[*] APIFY_TOKEN present (len={len(apify_token)}, prefix={prefix})")

        # Verify the token against Apify REST API (independent of proxy access)
        try:
            req = urllib.request.Request(
                'https://api.apify.com/v2/users/me',
                headers={'Authorization': f'Bearer {apify_token}'}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read())
                username = body.get('data', {}).get('username', 'unknown')
                plan = body.get('data', {}).get('plan', {}).get('id', 'unknown')
                log(f"[+] Apify token VALID — user: {username}, plan: {plan}")
        except urllib.error.HTTPError as e:
            log(f"[!] Apify token INVALID — API returned {e.code}: {e.reason}")
        except Exception as e:
            log(f"[!] Apify token check failed: {e}")
    else:
        log("[*] No APIFY_TOKEN set")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("[-] playwright not installed")
        save_debug()
        sys.exit(1)

    all_data = {}

    with sync_playwright() as pw:
        # Attempt 1: Apify residential proxy (if token available)
        if apify_token:
            proxy_config = {
                'server': 'http://proxy.apify.com:8000',
                'username': 'auto',
                'password': apify_token,
            }
            try:
                all_data = run_scraper(pw, proxy_config)
                if all_data:
                    log("[+] Proxy scrape succeeded")
                else:
                    log("[!] Proxy scrape returned no data")
            except Exception as e:
                log(f"[-] Proxy scrape error: {e}")
                log(traceback.format_exc())

        # Attempt 2: Direct connection with stealth (fallback or if no token)
        if not all_data:
            log("\n[*] Falling back to direct connection with stealth...")
            try:
                all_data = run_scraper(pw, proxy_config=None)
                if all_data:
                    log("[+] Direct scrape succeeded")
                else:
                    log("[!] Direct scrape returned no data")
            except Exception as e:
                log(f"[-] Direct scrape error: {e}")
                log(traceback.format_exc())

    save_debug()

    if all_data:
        with open('parkrun-data.json', 'w') as f:
            json.dump(all_data, f, indent=2)
        log(f"\n[+] Saved to parkrun-data.json")
        sys.exit(0)
    else:
        log(f"\n[!] No data collected from any attempt")
        sys.exit(1)


if __name__ == '__main__':
    main()
