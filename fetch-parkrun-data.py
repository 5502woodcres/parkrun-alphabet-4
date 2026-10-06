#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup
import json
import math
from datetime import datetime
from collections import defaultdict

ATHLETES = {
    'lisa': {'id': 'a3934942', 'name': 'Lisa', 'locations': {'chepstow': (51.6521, -2.5124)}},
    'beth': {'id': 'a2475659', 'name': 'Beth', 'locations': {'cheltenham': (51.8958, -2.0833), 'london': (51.5045, -0.2226)}}
}

LOCATIONS = {
    'chepstow': (51.6521, -2.5124),
    'cheltenham': (51.8958, -2.0833),
    'london': (51.5045, -0.2226)
}

def haversine(lat1, lng1, lat2, lng2):
    """Calculate distance in km"""
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    a = math.sin(delta_phi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def fetch_athlete_profile(athlete_id):
    """Fetch athlete's run history from parkrun.org.uk"""
    url = f'https://www.parkrun.org.uk/athlete/{athlete_id}/'
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"Error fetching {athlete_id}: {e}")
        return None
    
    soup = BeautifulSoup(response.content, 'html.parser')
    runs = []
    
    # Find results table
    table = soup.find('table', {'class': 'sortable'})
    if not table:
        print(f"No results table for {athlete_id}")
        return None
    
    rows = table.find_all('tr')[1:]  # Skip header
    
    for row in rows:
        cols = row.find_all('td')
        if len(cols) < 5:
            continue
        
        try:
            date_str = cols[0].text.strip()
            # Parse date (format: DD/MM/YYYY or similar)
            course_link = cols[1].find('a')
            if not course_link:
                continue
            
            course_name = course_link.text.strip()
            letter = course_name[0].upper() if course_name else '?'
            
            location_text = cols[2].text.strip()
            
            # Try to get coordinates from location link
            location_link = cols[2].find('a')
            lat, lng = None, None
            
            if location_link:
                for attr in ['data-latitude', 'data-lat']:
                    if location_link.get(attr):
                        try:
                            lat = float(location_link.get(attr))
                            lng = float(location_link.get('data-longitude') or location_link.get('data-lng'))
                            break
                        except:
                            pass
            
            if lat is None or lng is None:
                continue
            
            runs.append({
                'date': date_str,
                'course': course_name,
                'letter': letter,
                'location': location_text,
                'lat': lat,
                'lng': lng
            })
        except Exception as e:
            continue
    
    return runs

def parse_date(date_str):
    """Parse parkrun date format"""
    for fmt in ['%d/%m/%Y', '%Y-%m-%d', '%d %b %Y']:
        try:
            return datetime.strptime(date_str, fmt)
        except:
            pass
    return None

def build_alphabet_data(runs):
    """Group runs by letter and assign to alphabets"""
    letter_runs = defaultdict(list)
    
    for run in runs:
        letter = run['letter']
        date = parse_date(run['date'])
        if date:
            letter_runs[letter].append({'date': date, 'run': run})
    
    # Sort by date for each letter
    for letter in letter_runs:
        letter_runs[letter].sort(key=lambda x: x['date'])
    
    # Build alphabet assignments
    alphabets = {1: {}, 2: {}, 3: {}, 4: {}}
    
    for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        if letter in letter_runs:
            runs_for_letter = letter_runs[letter]
            for idx, run_data in enumerate(runs_for_letter):
                alphabet_num = min(idx + 1, 4)
                alphabets[alphabet_num][letter] = {
                    'course': run_data['run']['course'],
                    'date': run_data['date'].strftime('%Y-%m-%d'),
                    'location': run_data['run']['location'],
                    'lat': run_data['run']['lat'],
                    'lng': run_data['run']['lng']
                }
    
    return alphabets, letter_runs

def get_remaining_letters(alphabets):
    """Get letters still needed for alphabet 4"""
    all_letters = set('ABCDEFGHIJKLMNOPQRSTUVWXYZ')
    alphabet_4 = set(alphabets[4].keys())
    return sorted(all_letters - alphabet_4)

def rank_parkruns(lat, lng, location_name):
    """Return distance for ranking purposes"""
    return haversine(lat, lng, LOCATIONS[location_name][0], LOCATIONS[location_name][1])

def determine_travel_mode(distances):
    """Determine if car (from Cheltenham) or public transport (from London) is better"""
    cheltenham_dist = distances.get('cheltenham', float('inf'))
    london_dist = distances.get('london', float('inf'))
    
    if cheltenham_dist <= london_dist:
        return 'car_from_cheltenham'
    else:
        return 'public_transport_from_london'

def main():
    print("Starting parkrun data fetch...")
    
    data = {}
    
    for name, athlete_info in ATHLETES.items():
        athlete_id = athlete_info['id']
        print(f"Fetching {name} ({athlete_id})...")
        
        runs = fetch_athlete_profile(athlete_id)
        
        if not runs:
            print(f"Failed to fetch {name}")
            data[name] = {
                'athlete_id': athlete_id,
                'name': athlete_info['name'],
                'error': 'Failed to fetch data',
                'alphabets': {}
            }
            continue
        
        alphabets, letter_runs = build_alphabet_data(runs)
        remaining = get_remaining_letters(alphabets)
        
        # Count runs per letter (for future alphabet potential)
        runs_per_letter = {letter: len(runs) for letter, runs in letter_runs.items()}
        
        data[name] = {
            'athlete_id': athlete_id,
            'name': athlete_info['name'],
            'total_runs': len(runs),
            'alphabets': alphabets,
            'remaining_letters': remaining,
            'runs_per_letter': runs_per_letter,
            'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        print(f"  Found {len(runs)} runs")
        print(f"  Alphabet 4: {len(alphabets[4])}/26 letters")
        print(f"  Remaining: {', '.join(remaining) if remaining else 'None'}")
    
    # Write to file
    with open('parkrun-data.json', 'w') as f:
        json.dump(data, f, indent=2)
    
    print("\nData saved to parkrun-data.json")

if __name__ == '__main__':
    main()
