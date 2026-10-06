#!/usr/bin/env python3
import requests
import json
import sys
from datetime import datetime

APIFY_TOKEN = None
APIFY_ACTOR_ID = '5lljkHZ8Jh1vf2NHc'

ATHLETES = {
    'a3934942': {'name': 'Lisa', 'location': 'Chepstow'},
    'a2475659': {'name': 'Beth', 'location': 'Cheltenham'}
}

def fetch_from_apify(athlete_id):
    print(f"\n[*] Fetching {ATHLETES[athlete_id]['name']} ({athlete_id})...")
    
    url = f'https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/run-sync'
    headers = {
        'Authorization': f'Bearer {APIFY_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        'mode': 'athlete-history',
        'athleteNumbers': [athlete_id],
        'country': 'org.uk'
    }
    
    try:
        print(f"[*] Calling: {url}")
        print(f"[*] Payload: {payload}")
        response = requests.post(url, json=payload, headers=headers, timeout=120)
        
        print(f"[*] Status: {response.status_code}")
        print(f"[*] Response text: {response.text[:500]}")
        
        response.raise_for_status()
        
        if response.text:
            return response.json()
        else:
            print(f"[-] Empty response from API")
            return None
            
    except requests.exceptions.HTTPError as e:
        print(f"[-] HTTP Error: {e}")
        print(f"[-] Response: {response.text}")
        return None
    except json.JSONDecodeError as e:
        print(f"[-] JSON Parse Error: {e}")
        print(f"[-] Raw response: {response.text}")
        return None
    except requests.RequestException as e:
        print(f"[-] Request Error: {e}")
        return None

def parse_athlete_data(apify_response, athlete_id, athlete_info):
    if not apify_response:
        return None
    
    try:
        results = apify_response.get('output', {}).get('athleteData', [])
        if not results:
            print(f"[-] No results for {athlete_id}")
            return None
        
        runs = []
        for result in results:
            date_str = result.get('date')
            course = result.get('courseName') or result.get('course', '')
            time_str = result.get('time', '')
            
            if not date_str or not course:
                continue
            
            letter = course[0].upper() if course else '?'
            runs.append({
                'date': date_str,
                'course': course,
                'time': time_str,
                'letter': letter
            })
        
        print(f"[+] Parsed {len(runs)} runs")
        return runs
    except Exception as e:
        print(f"[-] Error parsing: {e}")
        return None

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
        runs_for_letter = sorted(letters[letter], key=lambda x: x['date'])
        for idx, run in enumerate(runs_for_letter):
            alphabet_num = idx + 1
            if alphabet_num not in alphabet_map:
                alphabet_map[alphabet_num] = []
            alphabet_map[alphabet_num].append(letter)
    
    result = {}
    for alphabet_num in range(1, 5):
        letters_completed = set(alphabet_map.get(alphabet_num, []))
        result[f'alphabet_{alphabet_num}'] = {
            'letters': sorted(list(letters_completed)),
            'completed': len(letters_completed),
            'remaining': sorted([chr(i) for i in range(ord('A'), ord('Z')+1) if chr(i) not in letters_completed])
        }
    
    return result, alphabet_map, letters

def main():
    global APIFY_TOKEN
    
    import os
    APIFY_TOKEN = os.environ.get('APIFY_TOKEN')
    
    if not APIFY_TOKEN:
        print("[!] APIFY_TOKEN not set")
        sys.exit(1)
    
    print("="*70)
    print("PARKRUN DATA SCRAPER - Apify")
    print("="*70)
    
    all_data = {}
    
    for athlete_id, athlete_info in ATHLETES.items():
        apify_response = fetch_from_apify(athlete_id)
        if not apify_response:
            continue
        
        runs = parse_athlete_data(apify_response, athlete_id, athlete_info)
        if not runs:
            continue
        
        alphabet_status, alphabet_map, letters_data = group_by_alphabet(runs)
        
        athlete_data = {
            'name': athlete_info['name'],
            'athlete_id': athlete_id,
            'location': athlete_info['location'],
            'total_runs': len(runs),
            'alphabet_status': alphabet_status,
            'runs_per_letter': {letter: len(letter_runs) for letter, letter_runs in letters_data.items()},
            'last_updated': datetime.now().isoformat()
        }
        
        all_data[athlete_id] = athlete_data
        
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
