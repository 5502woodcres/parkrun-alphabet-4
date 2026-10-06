#!/usr/bin/env python3
"""Upload a file to GitHub via the Contents API.
Usage: python gh-upload.py <local-file> <repo-path> <commit-message>
"""
import base64
import datetime
import json
import os
import sys
import traceback
import urllib.error
import urllib.request


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <local-file> [repo-path] [message]")
        sys.exit(1)

    local_file = sys.argv[1]
    repo_path = sys.argv[2] if len(sys.argv) > 2 else local_file
    message = sys.argv[3] if len(sys.argv) > 3 else f"chore: update {repo_path}"

    token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    repo = os.environ.get('GITHUB_REPOSITORY')

    print(f"[gh-upload] file={local_file} repo_path={repo_path}")
    print(f"[gh-upload] repo={repo}")
    print(f"[gh-upload] token_present={'yes' if token else 'NO'}")

    if not token:
        print("ERROR: GITHUB_TOKEN or GH_TOKEN not set")
        sys.exit(1)
    if not repo:
        print("ERROR: GITHUB_REPOSITORY not set")
        sys.exit(1)
    if not os.path.exists(local_file):
        print(f"ERROR: {local_file} not found (cwd={os.getcwd()})")
        print(f"Files: {os.listdir('.')}")
        sys.exit(1)

    with open(local_file, 'rb') as f:
        content_b64 = base64.b64encode(f.read()).decode()
    print(f"[gh-upload] content length (b64): {len(content_b64)} chars")

    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json',
        'User-Agent': 'parkrun-bot/1.0',
    }
    api_url = f'https://api.github.com/repos/{repo}/contents/{repo_path}'
    print(f"[gh-upload] api_url={api_url}")

    # Get existing SHA
    sha = ''
    try:
        get_req = urllib.request.Request(api_url, headers=headers, method='GET')
        with urllib.request.urlopen(get_req, timeout=30) as r:
            existing = json.loads(r.read())
            sha = existing.get('sha', '')
            print(f"[gh-upload] existing sha={sha[:10]}...")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print("[gh-upload] file does not exist yet, will create")
        else:
            print(f"[gh-upload] GET failed: {e.code} {e.reason}")
            body = e.read().decode(errors='replace')[:300]
            print(f"[gh-upload] GET error body: {body}")
    except Exception as e:
        print(f"[gh-upload] GET exception: {type(e).__name__}: {e}")
        traceback.print_exc()

    # Build PUT payload
    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    payload = {
        'message': message.replace('{ts}', ts),
        'content': content_b64,
    }
    if sha:
        payload['sha'] = sha

    data = json.dumps(payload).encode()
    print(f"[gh-upload] PUT payload size: {len(data)} bytes")

    try:
        put_req = urllib.request.Request(api_url, data=data, headers=headers, method='PUT')
        with urllib.request.urlopen(put_req, timeout=30) as r:
            result = json.loads(r.read())
            print(f"[gh-upload] SUCCESS: {r.status} - commit {result.get('commit', {}).get('sha', '')[:7]}")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors='replace')[:500]
        print(f"[gh-upload] PUT FAILED: {e.code} {e.reason}")
        print(f"[gh-upload] Response: {body}")
        sys.exit(1)
    except Exception as e:
        print(f"[gh-upload] PUT exception: {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
