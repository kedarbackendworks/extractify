from app.utils.url_detect import detect_platform


def test_detect_platform_returns_expected_slug_and_category():
    assert detect_platform("https://www.instagram.com/reel/abc") == ("instagram", "social")
    assert detect_platform("https://x.com/someuser/status/1") == ("twitter", "social")
    assert detect_platform("https://www.scribd.com/document/123") == ("scribd", "document")


def test_detect_platform_returns_unknown_for_unmapped_domain():
    assert detect_platform("https://example.org/file") == (None, "unknown")
