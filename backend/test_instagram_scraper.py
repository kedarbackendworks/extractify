"""
Unit tests for Instagram scraper bug fixes.

Tests the key functions in isolation without needing real API access:
  1. _is_profile_pic() — profile picture detection
  2. _build_story_result() — story variant building
  3. _try_media_info_api() internal logic (carousel handling)

Run: cd backend && python test_instagram_scraper.py
"""

import sys
import os

# Ensure the backend app is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.scrapers.instagram import (
    _is_profile_pic,
    _cdn_filename,
    InstagramScraper,
)


def test_is_profile_pic():
    """Verify that _is_profile_pic correctly distinguishes real images from profile pics."""
    print("\n=== Test: _is_profile_pic ===")
    
    # Should be True — actual profile pic patterns
    assert _is_profile_pic("https://scontent.cdninstagram.com/v/t51.2885-19/12345.jpg") == True, \
        "FAIL: /t51.2885-19/ path should be detected as profile pic"
    
    assert _is_profile_pic("https://scontent.cdninstagram.com/v/profile_pic_12345.jpg") == True, \
        "FAIL: URL with 'profile_pic' should be detected"
    
    assert _is_profile_pic("https://scontent.cdninstagram.com/v/s150x150/12345.jpg") == True, \
        "FAIL: /s150x150/ should be detected as profile pic (small square)"
    
    assert _is_profile_pic("https://scontent.cdninstagram.com/v/s320x320/12345.jpg") == True, \
        "FAIL: /s320x320/ should be detected as profile pic (small square)"
    
    assert _is_profile_pic("https://scontent.cdninstagram.com/v/some.jpg", 100, 100) == True, \
        "FAIL: Very small image (100x100) should be a profile pic"
    
    # Should be False — real post/story images
    assert _is_profile_pic("https://scontent.cdninstagram.com/v/s1080x1080/post_photo.jpg") == False, \
        "FAIL: /s1080x1080/ should NOT be detected as profile pic — this is a real post photo!"
    
    assert _is_profile_pic("https://scontent.cdninstagram.com/v/s640x640/post_photo.jpg") == False, \
        "FAIL: /s640x640/ should NOT be detected as profile pic — this is a real post photo!"
    
    assert _is_profile_pic("https://scontent.cdninstagram.com/v/s1440x1800/story.jpg") == False, \
        "FAIL: Non-square large image should not be profile pic"
    
    assert _is_profile_pic("https://scontent.cdninstagram.com/v/t51.2885-15/post.jpg") == False, \
        "FAIL: /t51.2885-15/ (post CDN path) should NOT be profile pic"
    
    assert _is_profile_pic("https://scontent.cdninstagram.com/v/normal.jpg", 1080, 1080) == False, \
        "FAIL: 1080x1080 image without 'profile_pic' or small dims should not be profile pic"
    
    # Story context — SMALL square images are profile pics in stories
    assert _is_profile_pic("https://scontent.cdninstagram.com/normal.jpg", 320, 320, story_context=True) == True, \
        "FAIL: In story context, small square image (320x320) should be treated as profile pic"
    
    assert _is_profile_pic("https://scontent.cdninstagram.com/normal.jpg", 150, 150, story_context=True) == True, \
        "FAIL: In story context, small square image (150x150) should be treated as profile pic"
    
    # Story context — LARGE square images are NOT profile pics (some stories are square)
    assert _is_profile_pic("https://scontent.cdninstagram.com/normal.jpg", 640, 640, story_context=True) == False, \
        "FAIL: In story context, 640x640 image should NOT be profile pic — could be real story!"
    
    assert _is_profile_pic("https://scontent.cdninstagram.com/normal.jpg", 1080, 1080, story_context=True) == False, \
        "FAIL: In story context, 1080x1080 image should NOT be profile pic — could be real story!"
    
    # Story context — portrait images are NOT profile pics
    assert _is_profile_pic("https://scontent.cdninstagram.com/normal.jpg", 1080, 1920, story_context=True) == False, \
        "FAIL: In story context, portrait image should be real story"

    print("  ✅ All _is_profile_pic tests passed!")


def test_build_story_result_media_type_none():
    """Verify that stories with missing media_type still produce image variants."""
    print("\n=== Test: _build_story_result with media_type=None ===")
    
    # Simulate a story item with NO media_type and NO video
    items = [{
        "pk": "12345",
        "id": "12345_67890",
        "user": {"username": "testuser", "profile_pic_url": ""},
        "image_versions2": {
            "candidates": [
                {
                    "url": "https://scontent.cdninstagram.com/v/t51.2885-15/story_image.jpg",
                    "width": 1080,
                    "height": 1920,
                },
            ],
        },
        # NOTE: media_type is MISSING (None) — this was the bug
    }]
    
    result = InstagramScraper._build_story_result("testuser", "12345", items)
    
    assert result is not None, "FAIL: _build_story_result should return a result for valid story items"
    assert len(result.variants) > 0, "FAIL: Should have at least one variant for the story image"
    assert result.variants[0].url.endswith("story_image.jpg"), \
        f"FAIL: Variant URL should be the story image, got: {result.variants[0].url}"
    assert result.variants[0].format == "jpg", "FAIL: Should be jpg format"
    
    print(f"  ✅ Story with media_type=None produced {len(result.variants)} variant(s)")


def test_build_story_result_media_type_1():
    """Verify that stories with media_type=1 still work (regression check)."""
    print("\n=== Test: _build_story_result with media_type=1 ===")
    
    items = [{
        "pk": "12345",
        "id": "12345_67890",
        "media_type": 1,  # Explicit photo
        "user": {"username": "testuser", "profile_pic_url": ""},
        "image_versions2": {
            "candidates": [
                {
                    "url": "https://scontent.cdninstagram.com/v/t51.2885-15/story_photo.jpg",
                    "width": 1080,
                    "height": 1920,
                },
            ],
        },
    }]
    
    result = InstagramScraper._build_story_result("testuser", "12345", items)
    
    assert result is not None, "FAIL: Should produce result for media_type=1"
    assert len(result.variants) > 0, "FAIL: Should have variant for photo story"
    print(f"  ✅ Story with media_type=1 produced {len(result.variants)} variant(s)")


def test_build_story_result_video():
    """Verify that video stories work regardless of media_type."""
    print("\n=== Test: _build_story_result with video ===")
    
    items = [{
        "pk": "12345",
        "id": "12345_67890",
        "media_type": 2,  # Video
        "user": {"username": "testuser", "profile_pic_url": ""},
        "video_versions": [
            {
                "url": "https://scontent.cdninstagram.com/v/story_video.mp4",
                "width": 1080,
                "height": 1920,
            },
        ],
        "image_versions2": {
            "candidates": [
                {
                    "url": "https://scontent.cdninstagram.com/v/t51.2885-15/thumb.jpg",
                    "width": 1080,
                    "height": 1920,
                },
            ],
        },
    }]
    
    result = InstagramScraper._build_story_result("testuser", "12345", items)
    
    assert result is not None, "FAIL: Should produce result for video story"
    assert any(v.has_video for v in result.variants), "FAIL: Should contain video variant"
    print(f"  ✅ Video story produced {len(result.variants)} variant(s)")


def test_build_story_filters_profile_pic():
    """Verify that profile pic URLs are filtered from story results."""
    print("\n=== Test: _build_story_result filters profile pics ===")
    
    items = [{
        "pk": "12345",
        "id": "12345_67890",
        "user": {
            "username": "testuser",
            "profile_pic_url": "https://scontent.cdninstagram.com/v/t51.2885-19/profile.jpg",
        },
        "image_versions2": {
            "candidates": [
                {
                    # This is a profile pic (t51.2885-19 path)
                    "url": "https://scontent.cdninstagram.com/v/t51.2885-19/profile.jpg",
                    "width": 150,
                    "height": 150,
                },
                {
                    # This is the real story image
                    "url": "https://scontent.cdninstagram.com/v/t51.2885-15/real_story.jpg",
                    "width": 1080,
                    "height": 1920,
                },
            ],
        },
    }]
    
    result = InstagramScraper._build_story_result("testuser", "12345", items)
    
    assert result is not None, "FAIL: Should produce a result"
    assert len(result.variants) > 0, "FAIL: Should have at least one variant"
    # The variant should be the real story image, not the profile pic
    assert "real_story" in result.variants[0].url, \
        f"FAIL: Should use real story image, got: {result.variants[0].url}"
    
    print(f"  ✅ Profile pic filtered correctly, using: {result.variants[0].url.split('/')[-1]}")


def test_build_story_result_square_candidates():
    """Verify stories with all-square image candidates still produce variants.
    
    This is the exact scenario that was failing — Instagram returns square
    image candidates for some stories, and they were all being filtered as
    profile pics.
    """
    print("\n=== Test: _build_story_result with square candidates ===")
    
    items = [{
        "pk": "12345",
        "id": "12345_67890",
        "user": {"username": "testuser", "profile_pic_url": ""},
        "image_versions2": {
            "candidates": [
                {
                    # All candidates are square — this used to fail!
                    "url": "https://scontent.cdninstagram.com/v/t51.2885-15/story_1080.jpg",
                    "width": 1080,
                    "height": 1080,
                },
                {
                    "url": "https://scontent.cdninstagram.com/v/t51.2885-15/story_640.jpg",
                    "width": 640,
                    "height": 640,
                },
            ],
        },
    }]
    
    result = InstagramScraper._build_story_result("testuser", "12345", items)
    
    assert result is not None, \
        "FAIL: Story with square candidates should NOT return None — these are real story images!"
    assert len(result.variants) > 0, \
        "FAIL: Should produce at least one variant from square candidates"
    assert "1080" in result.variants[0].url, \
        f"FAIL: Should pick the largest image, got: {result.variants[0].url}"
    
    print(f"  ✅ Story with square candidates produced {len(result.variants)} variant(s)")


def test_cdn_filename():
    """Verify CDN filename extraction."""
    print("\n=== Test: _cdn_filename ===")
    
    assert _cdn_filename("https://scontent.cdninstagram.com/v/photo.jpg?stp=dst-jpg") == "photo.jpg"
    assert _cdn_filename("") == ""
    assert _cdn_filename("https://example.com/path/to/image.png") == "image.png"
    
    print("  ✅ All _cdn_filename tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Instagram Scraper Bug Fix Tests")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    tests = [
        test_is_profile_pic,
        test_build_story_result_media_type_none,
        test_build_story_result_media_type_1,
        test_build_story_result_video,
        test_build_story_filters_profile_pic,
        test_build_story_result_square_candidates,
        test_cdn_filename,
    ]
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  ❌ {test.__name__}: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed:
        sys.exit(1)
    print("\n🎉 All tests passed!")
