import asyncio, httpx
from app.services.scrapers.soundcloud import SoundCloudScraper, _HEADERS, _SC_API_BASE
from urllib.parse import quote

async def test():
    sc = SoundCloudScraper()
    cid = await sc._get_client_id()
    
    urls = [
        "https://soundcloud.com/neffexmusic/sets/copyright-free",
        "https://soundcloud.com/neffexmusic/sets/neffex-copyright-free",
        "https://soundcloud.com/edmsauce/sets/best-of-2024",
    ]
    
    for url in urls:
        api_url = f"{_SC_API_BASE}/resolve?url={quote(url, safe='')}&client_id={cid}"
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=_HEADERS) as client:
            resp = await client.get(api_url)
            print(f"{url}")
            print(f"  status={resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                kind = data.get("kind")
                title = data.get("title")
                tracks = data.get("tracks", [])
                print(f"  kind={kind} title={title} tracks={len(tracks)}")
                if tracks:
                    t = tracks[0]
                    has_media = bool(t.get("media", {}).get("transcodings"))
                    print(f"  first_track_has_transcodings={has_media}")
                    print(f"  first_track_id={t.get('id')}")
            print()

asyncio.run(test())
