#!/usr/bin/env python3
"""Upload a file to GitHub via the Contents API.
Usage: python gh-upload.py <local-file> <repo-path> <commit-message>
Writes all output to stdout. Exits 0 on success, 1 on failure.
"""
import base64
import datetime
import json
import os
import sys
import traceback

# Try requests first, fall back to urllib
try:
    import requests as _requests
    USE_REQUESTS = True
except ImportError:
    import urllib.error
    import urllib.request
    USE_REQUESTS = False


def http_get(url, headers):
    if USE_REQUESTS:
        r = _requests.get(url, headers=headers, timeout=30)
        if r.ok:
            return r.json(), None
        return None, f"GET {r.status_code}: {r.text[:300]}"
    else:
        try:
            req = urllib.request.Request(url, headers=headers, method='GET')
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read()), None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, None  # Not found is OK
            return None, f"GET {e.code}: {e.read().decode(errors='replace')[:300]}"
        except Exception as e:
            return None, f"GET exception: {e}"


def http_put(url, headers, payload):
    data = json.dumps(payload).encode()
    if USE_REQUESTS:
        r = _requests.put(url, headers=headers, data=data, timeout=30)
        if r.ok:
            return r.json(), None
        return None, f"PUT {r.status_code}: {r.text[:500]}"
    else:
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method='PUT')
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read()), None
        except urllib.error.HTTPError as e:
            return None, f"PUT {e.code}: {e.read().decode(errors='replace')[:500]}"
        except Exception as e:
            return None, f"PUT exception: {type(e).__name__}: {e}"


def main():
    print(f"[gh-upload] Python {sys.version.split()[0]}, requests={USE_REQUESTS}")

    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <local-file> <repo-path> [message]")
        sys.exit(1)

    local_file = sys.argv[1]
    repo_path = sys.argv[2]
    message = sys.argv[3] if len(sys.argv) > 3 else f"chore: update {repo_path}"

    token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN', '')
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    message = message.replace('{ts}', ts)

    print(f"[gh-upload] repo={repo!r} token_len={len(token)} file={local_file}")

    if not token:
        print("ERROR: GITHUB_TOKEN not set")
        sys.exit(1)
    if not repo:
        print("ERROR: GITHUB_REPOSITORY not set")
        sys.exit(1)
    if not os.path.exists(local_file):
        print(f"ERROR: {local_file} not found (cwd={os.getcwd()})")
        print(f"Files: {sorted(os.listdir('.'))}")
        sys.exit(0)  # Don't fail workflow if file missing

    with open(local_file, 'rb') as f:
        raw = f.read()
    content_b64 = base64.b64encode(raw).decode()
    print(f"[gh-upload] file size={len(raw)}B  b64_len={len(content_b64)}")

    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    api_url = f'https://api.github.com/repos/{repo}/contents/{repo_path}'
    print(f"[gh-upload] GET {api_url}")

    existing, err = http_get(api_url, headers)
    if err:
        print(f"[gh-upload] GET error: {err}")
    sha = (existing or {}).get('sha', '')
    print(f"[gh-upload] existing_sha={sha[:10] + '...' if sha else 'none'}")

    payload = {'message': message, 'content': content_b64}
    if sha:
        payload['sha'] = sha

    print(f"[gh-upload] PUT {api_url}")
    result, err = http_put(api_url, headers, payload)
    if err:
        print(f"[gh-upload] PUT ERROR: {err}")
        sys.exit(1)

    commit_sha = (result or {}).get('commit', {}).get('sha', '')[:7]
    print(f"[gh-upload] SUCCESS commit={commit_sha}")


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
