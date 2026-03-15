"""Test Pinterest scraper with both image and video pins."""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def main():
    from app.services.scrapers.pinterest import PinterestScraper, _upgrade_pinimg_url
    
    scraper = PinterestScraper()
    
    # Test _extract_pin_id
    print("=== Pin ID Extraction ===")
    test_urls = [
        "https://www.pinterest.com/pin/633387443245752/",
        "https://www.pinterest.com/pin/chalkboard-calendar--633387443245752/",
        "https://www.pinterest.com/pin/12345678901234/",
    ]
    for url in test_urls:
        pid = scraper._extract_pin_id(url)
        print(f"  {url} → {pid}")
    
    # Test _upgrade_pinimg_url
    print("\n=== Image URL Upgrade ===")
    test_imgs = [
        "https://i.pinimg.com/736x/1d/e6/8d/1de68dcc17f64d6ba4a1711e04320c7b.jpg",
        "https://i.pinimg.com/236x/1d/e6/8d/1de68dcc17f64d6ba4a1711e04320c7b.jpg",
        "https://i.pinimg.com/originals/1d/e6/8d/1de68dcc17f64d6ba4a1711e04320c7b.jpg",
    ]
    for url in test_imgs:
        upgraded = _upgrade_pinimg_url(url)
        changed = " (upgraded!)" if upgraded != url else ""
        print(f"  {url.split('/')[-1]}: .../{'/'.join(upgraded.split('/')[3:5])}/...{changed}")
    
    # Test actual scraping
    print("\n=== Full Scrape Test ===")
    url = "https://www.pinterest.com/pin/chalkboard-calendar--633387443245752/"
    print(f"\nScraping: {url}")
    try:
        result = await scraper.scrape(url)
        print(f"  Title: {result.title}")
        print(f"  Content type: {result.content_type}")
        print(f"  Thumbnail: {result.thumbnail_url[:80] if result.thumbnail_url else 'None'}")
        print(f"  Variants ({len(result.variants)}):")
        for v in result.variants:
            print(f"    - {v.label} ({v.format}): video={v.has_video}")
            print(f"      URL: {v.url[:100]}")
        
        # Verify image quality
        for v in result.variants:
            if v.format in ("jpg", "png", "webp", "gif"):
                if "/originals/" in v.url:
                    print(f"  ✅ Image uses /originals/ quality")
                elif "/736x/" in v.url or "/236x/" in v.url:
                    print(f"  ❌ Image still uses low-quality URL!")
                else:
                    print(f"  ⚠️ Unknown image quality: {v.url[:50]}")
    except Exception as e:
        print(f"  FAILED: {e}")
        import traceback
        traceback.print_exc()

asyncio.run(main())
