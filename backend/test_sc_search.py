import os
import httpx

cid = os.environ.get("SOUNDCLOUD_CLIENT_ID", "")
if not cid:
    raise SystemExit("Set SOUNDCLOUD_CLIENT_ID env var to run this test")
url = f"https://api-v2.soundcloud.com/search/playlists?q=lofi&client_id={cid}&limit=3"
resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True, timeout=15)
print("Status:", resp.status_code)
if resp.status_code == 200:
    data = resp.json()
    for item in data.get("collection", [])[:3]:
        title = item.get("title")
        purl = item.get("permalink_url")
        tc = item.get("track_count")
        kind = item.get("kind")
        print(f"  title={title}")
        print(f"  permalink_url={purl}")
        print(f"  track_count={tc} kind={kind}")
        
        # Now try to resolve this URL
        resolve_url = f"https://api-v2.soundcloud.com/resolve?url={purl}&client_id={cid}"
        resp2 = httpx.get(resolve_url, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True, timeout=15)
        print(f"  resolve_status={resp2.status_code}")
        if resp2.status_code == 200:
            d2 = resp2.json()
            print(f"  resolved_kind={d2.get('kind')} tracks={len(d2.get('tracks', []))}")
        print()
