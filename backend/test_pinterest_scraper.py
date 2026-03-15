"""Quick test for Pinterest scraper fixes."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.scrapers.pinterest import PinterestScraper, _find_pin_data

print("=== Pinterest Scraper Tests ===\n")

# Test 1: _find_pin_data matches on 'videos' key
data_videos = {"videos": {"video_list": {"V_720P": {"url": "test.mp4"}}}}
assert _find_pin_data(data_videos) is not None, "FAIL: Should match on 'videos' key"
print("  1. _find_pin_data matches 'videos' key")

# Test 2: _find_pin_data matches on 'images' key (existing behavior)
data_images = {"images": {"orig": {"url": "test.jpg"}}}
assert _find_pin_data(data_images) is not None, "FAIL: Should match on 'images' key"
print("  2. _find_pin_data matches 'images' key")

# Test 3: _find_pin_data finds nested pin data with both
data_nested = {"props": {"data": {"pin": {
    "images": {"orig": {"url": "img.jpg"}},
    "videos": {"video_list": {"V_720P": {"url": "vid.mp4", "height": 720}}}
}}}}
result = _find_pin_data(data_nested)
assert result is not None, "FAIL: Should find nested pin data"
assert "videos" in result, "FAIL: Should contain videos"
assert "images" in result, "FAIL: Should contain images"
print("  3. _find_pin_data finds nested data with both images+videos")

# Test 4: _parse_pin_page extracts video from __PWS_DATA__
import json
pws_data = json.dumps({"props": {"data": {"pin": {
    "grid_title": "Test Video Pin",
    "description": "Test description",
    "images": {"orig": {"url": "https://i.pinimg.com/originals/test.jpg"}},
    "videos": {"video_list": {
        "V_720P": {"url": "https://v.pinimg.com/videos/test_720.mp4", "height": 720, "width": 1280},
        "V_480P": {"url": "https://v.pinimg.com/videos/test_480.mp4", "height": 480, "width": 854},
    }}
}}}})
html = f'<html><script id="__PWS_DATA__" type="application/json">{pws_data}</script></html>'
result = PinterestScraper._parse_pin_page(html)
assert result is not None, "FAIL: Should parse pin page"
assert result.content_type == "video", f"FAIL: content_type should be 'video', got '{result.content_type}'"
video_variants = [v for v in result.variants if v.has_video]
assert len(video_variants) >= 2, f"FAIL: Should have >=2 video variants, got {len(video_variants)}"
assert result.title == "Test Video Pin", f"FAIL: title should be 'Test Video Pin', got '{result.title}'"
print(f"  4. _parse_pin_page extracts {len(video_variants)} video variants from __PWS_DATA__")

# Test 5: Ensure image-only pins still work
pws_img = json.dumps({"props": {"data": {"pin": {
    "grid_title": "Image Pin",
    "images": {"orig": {"url": "https://i.pinimg.com/originals/test.jpg"}},
}}}})
html_img = f'<html><script id="__PWS_DATA__" type="application/json">{pws_img}</script></html>'
result_img = PinterestScraper._parse_pin_page(html_img)
assert result_img is not None, "FAIL: Should parse image pin"
assert result_img.content_type == "image", "FAIL: Should be image content_type"
assert len(result_img.variants) >= 1, "FAIL: Should have image variant"
print(f"  5. Image-only pins still work ({len(result_img.variants)} variant)")

# Test 6: JSON-LD video extraction
ld_json = json.dumps({
    "name": "LD Video",
    "video": {"contentUrl": "https://v.pinimg.com/videos/ld_video.mp4"},
    "image": "https://i.pinimg.com/736x/test.jpg"
})
html_ld = f'<html><script type="application/ld+json">{ld_json}</script></html>'
result_ld = PinterestScraper._parse_pin_page(html_ld)
assert result_ld is not None, "FAIL: Should parse JSON-LD"
assert any(v.has_video for v in result_ld.variants), "FAIL: Should have video from JSON-LD"
print(f"  6. JSON-LD video extraction works ({len(result_ld.variants)} variants)")

print("\n🎉 All Pinterest scraper tests passed!")
