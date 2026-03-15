import { platformConfigs } from "./platforms";

/**
 * Given a URL and a detected platform slug, determine which content tab
 * best matches the URL based on path patterns.
 * Returns the matching tab name or null if no specific tab detected.
 */
export function detectContentTab(
  url: string,
  platformSlug: string
): string | null {
  const lower = url.toLowerCase();
  const platform = platformConfigs[platformSlug];
  if (!platform) return null;

  let detected: string | null = null;

  switch (platformSlug) {
    case "instagram":
      if (lower.includes("/reel/") || lower.includes("/reels/"))
        detected = "Reels";
      else if (lower.includes("/stories/")) detected = "Stories";
      else if (lower.includes("/p/")) detected = "Photos";
      else if (lower.includes("/tv/")) detected = "IGTV";
      else if (lower.includes("/live/")) detected = "Live";
      break;

    case "youtube":
      if (lower.includes("/shorts/")) detected = "Shorts";
      else if (lower.includes("/live/") || lower.includes("?live"))
        detected = "Live";
      else detected = "Long-form Video";
      break;

    case "facebook":
      if (lower.includes("/reel/") || lower.includes("/reels/"))
        detected = "Reels";
      else if (
        lower.includes("/stories/") ||
        lower.includes("/story.php")
      )
        detected = "Stories";
      else if (lower.includes("/photo") || lower.includes("/photos"))
        detected = "Photos";
      else detected = "Videos";
      break;

    case "tiktok":
      if (lower.includes("/live/")) detected = "Live";
      else if (lower.includes("/photo/")) detected = "Photos";
      else if (
        lower.includes("/story/") ||
        lower.includes("/stories/")
      )
        detected = "Stories";
      else detected = "Short Video";
      break;

    case "snapchat":
      if (lower.includes("/spotlight/")) detected = "Spotlight";
      else if (
        lower.includes("/story/") ||
        lower.includes("/stories/")
      )
        detected = "Stories";
      break;

    case "twitter":
      if (lower.includes("/photo/")) detected = "Images";
      else detected = "Videos";
      break;

    case "linkedin":
      if (
        lower.includes("/video/") ||
        lower.includes("/posts/") ||
        lower.includes("/feed/")
      )
        detected = "Video";
      else if (lower.includes("/document/")) detected = "Documents";
      break;

    case "pinterest":
      break;

    case "reddit":
      break;

    case "tumblr":
      break;

    case "soundcloud":
      if (lower.includes("/sets/")) detected = "Playlists";
      else detected = "Audio Tracks";
      break;

    case "telegram":
      break;

    case "threads":
      break;

    case "twitch":
      if (lower.includes("/clip/") || lower.includes("/clips/"))
        detected = "Clips";
      else if (lower.includes("/videos/")) detected = "VODs";
      break;

    case "vimeo":
      break;

    case "scribd":
      if (lower.includes("/audiobook/")) detected = "Audiobooks";
      else if (
        lower.includes("/document/") ||
        lower.includes("/doc/")
      )
        detected = "Docs";
      else detected = "PDFs";
      break;

    case "slideshare":
      break;

    default:
      break;
  }

  // Validate that the detected tab actually exists in the platform's tab list
  if (detected && platform.tabs.includes(detected)) {
    return detected;
  }

  return null;
}
