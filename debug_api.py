#!/usr/bin/env python3
"""Debug script: dumps raw parkrun API response to identify field names."""
import requests
import json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'en-GB,en;q=0.9',
    'Referer': 'https://www.parkrun.org.uk/',
    'X-Requested-With': 'XMLHttpRequest',
}

debug_output = {}

for athlete_id, name in [('3934942', 'Lisa'), ('2475659', 'Beth')]:
    print(f"\n=== {name} ({athlete_id}) ===")
    r = requests.get(
        'https://www.parkrun.org.uk/results/athleteresultshistory/',
        params={'athleteNumber': athlete_id, 'offset': 0, 'nbRecords': 3},
        headers=HEADERS,
        timeout=30
    )
    print(f"HTTP {r.status_code} | Content-Type: {r.headers.get('Content-Type')}")
    try:
        data = r.json()
        print(json.dumps(data, indent=2))
        debug_output[athlete_id] = {
            'status': r.status_code,
            'content_type': r.headers.get('Content-Type'),
            'data': data
        }
    except Exception as e:
        print(f"JSON parse error: {e}")
        print(f"Raw (first 2000 chars): {r.text[:2000]}")
        debug_output[athlete_id] = {
            'status': r.status_code,
            'error': str(e),
            'raw': r.text[:2000]
        }

# Save to file so it can be committed and read back
with open('debug-raw-response.json', 'w') as f:
    json.dump(debug_output, f, indent=2)
print("\n[+] Saved debug-raw-response.json")
