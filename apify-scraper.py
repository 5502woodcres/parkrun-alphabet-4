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

def test_actor_exists():
    """Verify the actor exists before running"""
    print("\n[*] Testing actor access...")
    headers = {
        'Authorization': f'Bearer {APIFY_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    test_url = f'https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}'
    try:
        response = requests.get(test_url, headers=headers, timeout=10)
        if response.status_code == 200:
            actor_data = response.json().get('data', {})
            print(f"[+] Actor found: {actor_data.get('name', 'Unknown')}")
            return True
        else:
            print(f"[-] Actor not found: {response.status_code}")
            print(f"[-] Response: {response.text}")
            return False
    except Exception as e:
        print(f"[-] Error testing actor: {e}")
        return False

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
        print(f"[*] POST {url}")
        print(f"[*] Payload: {json.dumps(payload)}")
        
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        
        print(f"[*] Response status: {response.status_code}")
        print(f"[*] Response headers: {dict(response.headers)}")
        print(f"[*] Response body: {response.text[:1000]}")
        
        response.raise_for_status()
        
        run_data = response.json()
        run_id = run_data.get('data', {}).get('id')
        
        if not run_id:
            print(f"[-] No run ID in response")
            print(f"[-] Full response: {json.dumps(run_data, indent=2)}")
            return None
        
        print(f"[+] Run created: {run_id}")
        print(f"[*] Waiting for completion (checking every 5s, max 60 attempts)...")
        
        for attempt in range(60):
