"""Debug explicitly using parse_og_tags to see exactly why it fails for Pinterest."""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def main():
    from app.utils.browser import get_page_content
    from app.services.scrapers.helpers import parse_og_tags
    import re
    
    url = "https://www.pinterest.com/pin/chalkboard-calendar--633387443245752/"
    html = await get_page_content(url)
    
    print("=== Raw HTML Search ===")
    matches = re.finditer(r'<meta[^>]*og:image[^>]*>', html)
    for m in matches:
        print(f"Match: {m.group(0)}")
        
    print("\n=== extract_og_tags Output ===")
    res = parse_og_tags(html, default_title="Pin", default_type="image")
    print(f"Title: {res.title}")
    print(f"Variants: {len(res.variants)}")
    for v in res.variants:
        print(f"  - {v.url}")

asyncio.run(main())
