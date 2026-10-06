#!/usr/bin/env python3
"""Parkrun scraper: bypasses AWS WAF on parkrun.org.uk.

Strategy (in order):
  1. ScraperAPI (free tier, 1k req/month) — no browser needed, handles WAF+IP
  2. Apify residential proxy + Playwright — bypasses IP block (requires paid plan)
  3. Direct Playwright with stealth — fallback (usually blocked by GitHub Actions IP)
  4. Patchright (stealth Chromium fork) — last resort
"""
import sys
import json
import os
import traceback
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime

ATHLETES = {
    '3934942': {'name': 'Lisa', 'location': 'Chepstow'},
    '2475659': {'name': 'Beth', 'location': 'Cheltenham'}
}

PARKRUN_AJAX = 'https://www.parkrun.org.uk/results/athleteresultshistory/'
SCRAPERAPI_BASE = 'https://api.scraperapi.com/'

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


def scraperapi_get(api_key, url, render_js=False, timeout=60):
    """Fetch URL via ScraperAPI (handles WAF + residential IP rotation)."""
    params = {
        'api_key': api_key,
        'url': url,
        'country_code': 'gb',
    }
    if render_js:
        params['render'] = 'true'
    api_url = SCRAPERAPI_BASE + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(api_url, headers={
        'Accept': 'application/json, text/html, */*',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        return e.code, body


def fetch_athlete_via_scraperapi(api_key, athlete_id):
    """Fetch athlete run data via ScraperAPI — no browser required.

    Tries AJAX JSON endpoint first (cheap, no render). Falls back to
    HTML profile page (render_js=True, costs 5 credits on ScraperAPI).
    """
    # Attempt 1: AJAX JSON endpoint
    ajax_url = (f"{PARKRUN_AJAX}?athleteNumber={athlete_id}"
                f"&offset=0&nbRecords=999")
    log(f"[*]   ScraperAPI AJAX: {ajax_url}")
    status, body = scraperapi_get(api_key, ajax_url, render_js=False)
    log(f"[*]   HTTP {status} — body[:80]: {body[:80]}")

    if status == 200 and not body.lstrip().startswith('<'):
        try:
            data = json.loads(body)
            runs = (data.get('data') or {}).get('Results') or []
            log(f"[+]   AJAX returned {len(runs)} runs")
            return runs, 'ajax'
        except json.JSONDecodeError as e:
            log(f"[!]   JSON decode error: {e}")

    # Attempt 2: HTML athlete page with JS rendering
    html_url = f'https://www.parkrun.org.uk/parkrunner/{athlete_id}/all/'
    log(f"[*]   ScraperAPI HTML (render_js=True): {html_url}")
    status, html = scraperapi_get(api_key, html_url, render_js=True, timeout=90)
    log(f"[*]   HTTP {status} — html[:80]: {html[:80]}")

    if status != 200:
        log(f"[!]   HTML fetch failed: {status}")
        return [], None

    # Parse HTML table
    runs = []
    import re
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE)
    for row_html in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL | re.IGNORECASE)
        cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
        if len(cells) >= 2 and cells[0] and cells[1]:
            course = cells[0]
            date_str = cells[1] if len(cells) > 1 else ''
            time_str = cells[3] if len(cells) > 3 else ''
            if course and date_str and not course.lower().startswith('event'):
                runs.append({
                    'date': date_str,
                    'course': course,
                    'time': time_str,
                    'letter': course[0].upper()
                })

    log(f"[+]   HTML parsed {len(runs)} runs")
    return runs, 'html'


def scrape_via_scraperapi(api_key):
    """Fetch all athletes' runs via ScraperAPI. Returns {} on failure."""
    log(f"\n[*] ScraperAPI strategy")
    all_data = {}

    for athlete_id, athlete_info in ATHLETES.items():
        log(f"\n[*] Fetching {athlete_info['name']} (athlete {athlete_id}) via ScraperAPI...")
        raw_runs, source = fetch_athlete_via_scraperapi(api_key, athlete_id)

        if not raw_runs:
            log(f"[!] No runs obtained for {athlete_info['name']} via ScraperAPI")
            continue

        # Parse if from AJAX (already dicts with API field names)
        if source == 'ajax':
            runs = parse_runs(raw_runs)
        else:
            runs = raw_runs  # already parsed from HTML

        if not runs:
            log(f"[!] Failed to parse runs for {athlete_info['name']}")
            continue

        alphabet_status, alphabet_map, letters_data = group_by_alphabet(runs)
        # Build course list per letter for transparency / debugging
        courses_per_letter = {
            ltr: sorted(r['course'] for r in runs_list)
            for ltr, runs_list in letters_data.items()
        }
        all_data[athlete_id] = {
            'name': athlete_info['name'],
            'athlete_id': athlete_id,
            'location': athlete_info['location'],
            'total_runs': len(runs),
            'alphabet_status': alphabet_status,
            'runs_per_letter': {ltr: len(r) for ltr, r in letters_data.items()},
            'courses_per_letter': courses_per_letter,
            'last_updated': datetime.now().isoformat()
        }

        log(f"\n[+] {athlete_info['name']} Summary:")
        for alph_key, alph_data in alphabet_status.items():
            alph_num = alph_key.split('_')[1]
            letters_str = ', '.join(alph_data['letters'][:5])
            if len(alph_data['letters']) > 5:
                letters_str += '...'
            log(f"    Alphabet {alph_num}: {alph_data['completed']}/25 ({letters_str})")

    return all_data


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


# The 25 letters that count toward the alphabet challenge (A-Z, X excluded)
CHALLENGE_LETTERS = [chr(i) for i in range(65, 91) if chr(i) != 'X']


def normalize_course(name):
    """Normalise a parkrun course name for deduplication.

    Strips whitespace, lowercases, and removes a trailing ' parkrun'
    suffix so that 'Cheltenham' and 'Cheltenham parkrun' collapse to
    the same key.
    """
    n = name.strip().lower()
    if n.endswith(' parkrun'):
        n = n[:-8].strip()
    return n


def group_by_alphabet(runs):
    """Return alphabet status for all achievable alphabets (at least 6 shown).

    A letter is 'earned' only by visiting a UNIQUE parkrun venue that
    starts with that letter — revisiting the same course does not add
    another slot. Alphabet N is complete when every challenge letter
    has at least N distinct venues in the athlete's history.

    X is excluded (practically no UK parkruns start with X).
    The alphabet target is 25 letters.
    """
    if not runs:
        return {}, {}, {}

    # Bucket ALL runs by letter first
    all_by_letter = {}
    for run in runs:
        letter = run['letter']
        if letter not in CHALLENGE_LETTERS:
            continue
        all_by_letter.setdefault(letter, []).append(run)

    # For each letter, keep only the FIRST visit to each unique course
    # (sorted chronologically so the earliest visit claims the slot)
    unique_courses = {}   # letter -> [one run per unique venue, sorted by date]
    for letter, letter_runs in all_by_letter.items():
        seen = {}
        for run in sorted(letter_runs, key=lambda x: x['date']):
            key = normalize_course(run['course'])
            if key and key not in seen:
                seen[key] = run
        unique_courses[letter] = list(seen.values())

    # For each letter, the Nth unique venue (chronologically) feeds alphabet N
    alphabet_map = {}
    for letter in sorted(unique_courses.keys()):
        for idx, run in enumerate(unique_courses[letter]):
            n = idx + 1
            alphabet_map.setdefault(n, []).append(letter)

    # Show all complete alphabets plus the next two in progress
    complete_through = 0
    for n in range(1, 100):
        done = set(alphabet_map.get(n, []))
        if all(l in done for l in CHALLENGE_LETTERS):
            complete_through = n
        else:
            break

    max_show = max(complete_through + 2, 6)

    result = {}
    for n in range(1, max_show + 1):
        done = set(alphabet_map.get(n, []))
        remaining = [l for l in CHALLENGE_LETTERS if l not in done]
        # runs_needed = how many more unique venues are required per missing letter
        runs_needed = {l: n - len(unique_courses.get(l, [])) for l in remaining}
        result[f'alphabet_{n}'] = {
            'letters': sorted(done),
            'completed': len(done),
            'total': len(CHALLENGE_LETTERS),
            'remaining': sorted(remaining),
            'runs_needed': runs_needed,
            'is_complete': len(remaining) == 0,
        }

    return result, alphabet_map, unique_courses


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
                log(f"    Alphabet {alph_num}: {alph_data['completed']}/25 ({letters_str})")

        page.close()
        return all_data

    finally:
        browser.close()


def run_scraper_patchright(proxy_config=None):
    """Same scrape logic but using patchright (stealthier Chromium fork)."""
    try:
        from patchright.sync_api import sync_playwright as sync_patchright
    except ImportError:
        log("[!] patchright not installed — skipping")
        return {}

    label = f"patchright+proxy={proxy_config['server']}" if proxy_config else "patchright direct"
    log(f"\n[*] Attempting scrape: {label}")

    launch_kwargs = {
        'headless': True,
        'args': ['--no-sandbox', '--disable-setuid-sandbox'],
    }
    if proxy_config:
        launch_kwargs['proxy'] = proxy_config

    with sync_patchright() as pw:
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

            for athlete_id, athlete_info in ATHLETES.items():
                log(f"\n[*] Fetching {athlete_info['name']} (athlete {athlete_id})...")
                runs = None
                try:
                    raw_runs = fetch_athlete_runs(page, athlete_id)
                    log(f"[*] {athlete_info['name']}: {len(raw_runs)} raw runs via AJAX")
                    if raw_runs:
                        runs = parse_runs(raw_runs)
                except Exception as e:
                    log(f"[-] AJAX error for {athlete_info['name']}: {e}")

                if not runs:
                    log(f"[*] Trying HTML fallback for {athlete_info['name']}...")
                    html_runs = fetch_athlete_via_html(context, athlete_id)
                    if html_runs:
                        runs = html_runs
                        log(f"[*] HTML fallback returned {len(runs)} runs")

                if not runs:
                    log(f"[!] No runs obtained for {athlete_info['name']}")
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
                    log(f"    Alphabet {alph_num}: {alph_data['completed']}/25 ({letters_str})")

            page.close()
            return all_data
        finally:
            browser.close()


def main():
    log("=" * 70)
    log("PARKRUN DATA SCRAPER")
    log("=" * 70)

    scraperapi_key = os.environ.get('SCRAPERAPI_KEY', '')
    apify_token = os.environ.get('APIFY_TOKEN', '')

    if scraperapi_key:
        log(f"[*] SCRAPERAPI_KEY present (len={len(scraperapi_key)})")
    else:
        log("[*] No SCRAPERAPI_KEY set")

    if apify_token:
        prefix = apify_token[:10] if len(apify_token) >= 10 else apify_token
        log(f"[*] APIFY_TOKEN present (len={len(apify_token)}, prefix={prefix})")

        # Verify the token against Apify REST API
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

    all_data = {}

    # Attempt 1: ScraperAPI (no browser needed, free tier = 1k req/month)
    if scraperapi_key and not all_data:
        try:
            all_data = scrape_via_scraperapi(scraperapi_key)
            if all_data:
                log("[+] ScraperAPI scrape succeeded")
            else:
                log("[!] ScraperAPI scrape returned no data")
        except Exception as e:
            log(f"[-] ScraperAPI error: {e}")
            log(traceback.format_exc())

    # Attempts 2-4: Playwright-based (proxy + direct + patchright)
    if not all_data:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log("[-] playwright not installed")
            save_debug()
            sys.exit(1)

        with sync_playwright() as pw:
            # Attempt 2: Apify residential proxy
            if apify_token and not all_data:
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

            # Attempt 3: Direct connection with stealth
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

        # Attempt 4: patchright direct
        if not all_data:
            log("\n[*] Trying patchright (stealth Chromium fork)...")
            try:
                all_data = run_scraper_patchright(proxy_config=None)
                if all_data:
                    log("[+] Patchright direct scrape succeeded")
                else:
                    log("[!] Patchright direct scrape returned no data")
            except Exception as e:
                log(f"[-] Patchright error: {e}")
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
