#!/usr/bin/env python3
import requests
import json
import sys
import time
from datetime import datetime

APIFY_TOKEN = None
APIFY_ACTOR_ID = '5lljkHZ8Jh1vf2NHc'

ATHLETES = {
    '3934942': {'name': 'Lisa', 'location': 'Chepstow'},
    '2475659': {'name': 'Beth', 'location': 'Cheltenham'}
}

def fetch_from_apify(athlete_id):
    print(f"\n[*] Fetching {ATHLETES[athlete_id]['name']} ({athlete_id})...")
    
    url = f'https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs'
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
        print(f"[*] Starting async run...")
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        
        run_data = response.json()
        run_id = run_data.get('data', {}).get('id')
        
        if not run_id:
            print(f"[-] No run ID in response")
            return None
        
        print(f"[*] Run ID: {run_id}")
        print(f"[*] Waiting for results...")
        
        for attempt in range(120):
            time.sleep(1)
            
            result_url = f'https://api.apify.com/v2/runs/{run_id}/dataset/items'
            result_response = requests.get(result_url, headers=headers, timeout=10)
            
            if result_response.status_code == 200:
                items = result_response.json()
                if items:
                    print(f"[+] Got {len(items)} results")
                    return {'items': items}
        
        print(f"[-] Timeout waiting for results")
        return None
        
    except requests.RequestException as e:
        print(f"[-] Error: {e}")
        return None

def parse_athlete_data(apify_response, athlete_id, athlete_info):
    if not apify_response:
        return None
    
    try:
        items = apify_response.get('items', [])
        if
