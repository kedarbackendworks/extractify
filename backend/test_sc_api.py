"""Test SoundCloud API v2 direct extraction."""
import httpx
import re
import json

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA}

def get_client_id():
    """Extract client_id from SoundCloud's JS bundles."""
    resp = httpx.get("https://soundcloud.com", headers=HEADERS, follow_redirects=True, timeout=15)
    print(f"Homepage status: {resp.status_code}")
    
    # Find JS bundle URLs
    scripts = re.findall(r'src="(https://a-v2\.sndcdn\.com/assets/[^"]+\.js)"', resp.text)
    print(f"Found {len(scripts)} JS bundles")
    
    # Search the last few bundles (client_id is usually in the app bundles at the end)
    for script_url in reversed(scripts):
        try:
            js_resp = httpx.get(script_url, headers=HEADERS, timeout=10)
            # Look for client_id pattern
            match = re.search(r'client_id\s*[:=]\s*"([a-zA-Z0-9]{32})"', js_resp.text)
            if match:
                cid = match.group(1)
                print(f"Found client_id: {cid} (from {script_url[-50:]})")
                return cid
        except Exception as e:
            print(f"  Failed to fetch {script_url[-50:]}: {e}")
            continue
    
    return None

def resolve_track(client_id, track_url):
    """Resolve a track URL using the API v2."""
    api_url = f"https://api-v2.soundcloud.com/resolve?url={track_url}&client_id={client_id}"
    resp = httpx.get(api_url, headers=HEADERS, follow_redirects=True, timeout=15)
    print(f"Resolve status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"  Response: {resp.text[:300]}")
        return None
    data = resp.json()
    
    print(f"Title: {data.get('title')}")
    print(f"Duration: {data.get('duration')}ms = {data.get('duration', 0) / 1000:.1f}s")
    print(f"Full Duration: {data.get('full_duration')}ms")
    print(f"Kind: {data.get('kind')}")
    print(f"Policy: {data.get('policy')}")
    
    # Show raw media key
    media = data.get("media", {})
    print(f"Media keys: {list(media.keys()) if media else 'NO MEDIA KEY'}")
    
    # Check for policy/monetization flags
    for key in ['policy', 'monetization_model', 'track_authorization', 'access']:
        if key in data:
            val = data[key]
            if isinstance(val, str):
                print(f"  {key}: {val[:100]}")
            else:
                print(f"  {key}: {val}")
    
    transcodings = media.get("transcodings", [])
    print(f"\nTranscodings ({len(transcodings)}):")
    
    for t in transcodings:
        fmt = t.get("format", {})
        protocol = fmt.get("protocol")
        mime = fmt.get("mime_type")
        quality = t.get("quality")
        preset = t.get("preset")
        snip = t.get("snipped", False)
        stream_url = t.get("url")
        print(f"  protocol={protocol} mime={mime} quality={quality} preset={preset} snipped={snip}")
        print(f"    stream_url={stream_url[:120] if stream_url else 'None'}")
        
        # Fetch actual stream URL
        if stream_url and not snip:
            try:
                track_auth = data.get("track_authorization", "")
                stream_resp = httpx.get(
                    f"{stream_url}?client_id={client_id}&track_authorization={track_auth}",
                    headers=HEADERS, follow_redirects=True, timeout=10
                )
                if stream_resp.status_code == 200:
                    stream_data = stream_resp.json()
                    actual_url = stream_data.get("url", "")
                    print(f"    actual_url={actual_url[:200]}")
                    print(f"    is_m3u8={'m3u8' in actual_url}")
                else:
                    print(f"    stream fetch failed: {stream_resp.status_code}")
            except Exception as e:
                print(f"    stream fetch error: {e}")
    
    return data

if __name__ == "__main__":
    cid = get_client_id()
    if cid:
        # Test with multiple tracks - include free/indie tracks
        urls = [
            "https://soundcloud.com/nocopyrightsounds/ncs-release-elektronomia-sky-high",
            "https://soundcloud.com/unknownbrain/superhero-feat-chris-linton",
            "https://soundcloud.com/neffexmusic/grateful",
        ]
        for url in urls:
            print("\n" + "="*60)
            print(f"Testing: {url}")
            try:
                resolve_track(cid, url)
            except Exception as e:
                print(f"Error: {e}")
    else:
        print("Failed to get client_id")
