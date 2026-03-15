"use client";

import { useState, use, useEffect, useRef, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { notFound } from "next/navigation";
import UrlInput from "@/components/UrlInput";
import ContentTabs from "@/components/ContentTabs";
import ContentPreview from "@/components/ContentPreview";
import CloudflareCheck from "@/components/CloudflareCheck";
import DownloadProgress from "@/components/DownloadProgress";
import { platformConfigs } from "@/lib/platforms";
import { detectContentTab } from "@/lib/url-tab-detect";
import Hls from "hls.js";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

/** Build a proxied download URL through our backend to bypass CORS/origin blocks.
 *  Local API URLs (e.g. /api/files/...) are served directly from the backend. */
function getProxyDownloadUrl(remoteUrl: string, title?: string): string {
  // If the URL is already a local backend route, serve it directly
  if (remoteUrl.startsWith("/api/")) {
    return `${API_BASE_URL}${remoteUrl}`;
  }
  const params = new URLSearchParams({
    url: remoteUrl,
    filename: (title || "download").replace(/[^\w\s\-.]/g, "").slice(0, 80) || "download",
  });
  return `${API_BASE_URL}/api/download?${params.toString()}`;
}

/** Build a proxied stream URL for inline playback (video/audio preview). */
function getProxyStreamUrl(remoteUrl: string): string {
  if (remoteUrl.startsWith("/api/")) {
    return `${API_BASE_URL}${remoteUrl}`;
  }
  const params = new URLSearchParams({ url: remoteUrl });
  return `${API_BASE_URL}/api/stream?${params.toString()}`;
}

interface Variant {
  label: string;
  format: string;
  quality?: string;
  file_size_bytes?: number;
  download_url?: string;
  has_video?: boolean;
  has_audio?: boolean;
}

interface ExtractedContent {
  title?: string;
  description?: string;
  author?: string;
  thumbnail_url?: string;
  duration_seconds?: number;
  page_count?: number;
  content_type: string;
  variants: Variant[];
}

interface JobResponse {
  id: string;
  status: "pending" | "processing" | "completed" | "failed";
  error_message?: string;
  extracted?: ExtractedContent;
}

interface PlatformPageProps {
  params: Promise<{ slug: string }>;
}

const VIDEO_CONTENT_TYPES = new Set(["video", "reel", "short", "story"]);
const AUDIO_CONTENT_TYPES = new Set(["audio", "podcast", "music", "track"]);
const TEXT_CONTENT_TYPES = new Set(["text"]);
const PLAYABLE_VIDEO_FORMATS = new Set(["mp4", "webm", "mov", "m4v"]);
const PLAYABLE_AUDIO_FORMATS = new Set(["mp3", "ogg", "opus", "wav", "m4a", "aac", "flac"]);
const IMAGE_FORMATS = new Set(["jpg", "jpeg", "png", "webp", "gif", "bmp", "svg"]);
const DOCUMENT_CONTENT_TYPES = new Set(["pdf", "document", "presentation"]);

/** Platforms that should show the Cloudflare bot verification before extraction */
const DOCUMENT_PLATFORMS = new Set([
  "scribd", "slideshare", "issuu", "calameo", "yumpu", "slideserve",
]);

function isHlsUrl(url?: string): boolean {
  if (!url) return false;
  const lower = url.toLowerCase();
  return lower.includes(".m3u8") || lower.includes("/manifest/") || lower.includes("playlist/index.m3u8");
}

function pickBestAudioVariant(content: ExtractedContent | null): Variant | null {
  if (!content?.variants?.length) return null;
  return content.variants.find((v) => {
    if (!v.download_url || !v.has_audio) return false;
    const fmt = (v.format || "").toLowerCase();
    return PLAYABLE_AUDIO_FORMATS.has(fmt) || isHlsUrl(v.download_url);
  }) || null;
}

function pickBestPreviewVariant(content: ExtractedContent | null): Variant | null {
  if (!content?.variants?.length) return null;

  const usable = content.variants.filter((variant) => Boolean(variant.download_url));
  if (!usable.length) return null;

  const isVideoContent = VIDEO_CONTENT_TYPES.has((content.content_type || "").toLowerCase());
  if (!isVideoContent) return usable[0] || null;

  const withVideoAndAudio = usable.find((variant) => {
    const format = (variant.format || "").toLowerCase();
    return variant.has_video === true && variant.has_audio === true && PLAYABLE_VIDEO_FORMATS.has(format);
  });
  if (withVideoAndAudio) return withVideoAndAudio;

  const withVideoOnly = usable.find((variant) => {
    const format = (variant.format || "").toLowerCase();
    return variant.has_video === true && PLAYABLE_VIDEO_FORMATS.has(format);
  });
  if (withVideoOnly) return withVideoOnly;

  const notAudioOnlyLabel = usable.find((variant) => !variant.label.toLowerCase().startsWith("audio-"));
  if (notAudioOnlyLabel) return notAudioOnlyLabel;

  return usable[0] || null;
}

export default function PlatformPage({ params }: PlatformPageProps) {
  const { slug } = use(params);
  const searchParams = useSearchParams();
  const initialUrl = searchParams.get("url") || "";

  const platform = platformConfigs[slug];

  if (!platform) {
    notFound();
  }

  // Determine the best initial tab: query param > URL detection > first tab
  const queryTab = searchParams.get("tab");
  const detectedTab = initialUrl ? detectContentTab(initialUrl, slug) : null;
  const startTab =
    queryTab && platform.tabs.includes(queryTab)
      ? queryTab
      : detectedTab && platform.tabs.includes(detectedTab)
        ? detectedTab
        : platform.tabs[0];

  const [activeTab, setActiveTab] = useState(startTab);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [downloadResult, setDownloadResult] = useState<ExtractedContent | null>(null);
  const [selectedVariant, setSelectedVariant] = useState<Variant | null>(null);
  const [botVerified, setBotVerified] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [pendingUrl, setPendingUrl] = useState<string | null>(null);
  const hasTriggeredRef = useRef(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const hlsRef = useRef<Hls | null>(null);
  const hlsAudioRef = useRef<Hls | null>(null);

  const handleUrlSubmit = useCallback(async (url: string) => {
    // Auto-detect the correct tab from the URL
    const autoTab = detectContentTab(url, slug);
    const effectiveTab = autoTab || activeTab;
    if (autoTab) {
      setActiveTab(autoTab);
    }

    // For document platforms, require bot verification first
    if (DOCUMENT_PLATFORMS.has(slug) && !botVerified) {
      setPendingUrl(url);
      return;
    }

    setIsLoading(true);
    setErrorMessage(null);
    setDownloadResult(null);
    setSelectedVariant(null);

    try {
      const createResp = await fetch(`${API_BASE_URL}/api/extract`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url,
          platform: slug,
          tab: effectiveTab,
        }),
      });

      if (!createResp.ok) {
        const errText = await createResp.text();
        throw new Error(errText || "Failed to create extraction job");
      }

      const createJob: JobResponse = await createResp.json();
      const jobId = createJob.id;

      let retries = 0;
      const maxRetries = 30;

      while (retries < maxRetries) {
        const pollResp = await fetch(`${API_BASE_URL}/api/extract/${jobId}`);
        if (!pollResp.ok) {
          throw new Error("Failed to fetch extraction status");
        }

        const polledJob: JobResponse = await pollResp.json();

        if (polledJob.status === "completed") {
          setDownloadResult(polledJob.extracted || null);
          setSelectedVariant(pickBestPreviewVariant(polledJob.extracted || null));
          setIsLoading(false);
          return;
        }

        if (polledJob.status === "failed") {
          throw new Error(polledJob.error_message || "Extraction failed");
        }

        retries += 1;
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }

      throw new Error("Extraction timed out. Please try again.");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Something went wrong");
      setIsLoading(false);
    }
  }, [slug, activeTab, botVerified]);

  // If URL came from the homepage, auto-trigger (once)
  useEffect(() => {
    if (initialUrl && !hasTriggeredRef.current) {
      hasTriggeredRef.current = true;
      void handleUrlSubmit(initialUrl);
    }
  }, [initialUrl, handleUrlSubmit]);

  // Auto-submit pending URL after bot verification
  useEffect(() => {
    if (botVerified && pendingUrl) {
      const url = pendingUrl;
      setPendingUrl(null);
      void handleUrlSubmit(url);
    }
  }, [botVerified, pendingUrl, handleUrlSubmit]);

  // Elapsed seconds timer while loading
  useEffect(() => {
    if (!isLoading) {
      setElapsedSeconds(0);
      return;
    }
    const interval = setInterval(() => {
      setElapsedSeconds((s) => s + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, [isLoading]);

  const isDocumentPlatform = DOCUMENT_PLATFORMS.has(slug);

  const isVideoContentType = VIDEO_CONTENT_TYPES.has((downloadResult?.content_type || "").toLowerCase());
  const isAudioContentType = AUDIO_CONTENT_TYPES.has((downloadResult?.content_type || "").toLowerCase());
  const isTextContentType = TEXT_CONTENT_TYPES.has((downloadResult?.content_type || "").toLowerCase());
  const hasSelectedDownload = Boolean(selectedVariant?.download_url);
  // If the selected variant is actually an image format (e.g. story thumbnail),
  // show an <img> instead of <video>, regardless of content_type.
  const selectedFormat = (selectedVariant?.format || "").toLowerCase();
  const isVideoContent = isVideoContentType && !IMAGE_FORMATS.has(selectedFormat);
  const isPdfContent = selectedFormat === "pdf";
  const audioVariant = isAudioContentType ? pickBestAudioVariant(downloadResult) : null;
  const isAudioContent = Boolean(audioVariant?.download_url);

  // For PDF variants, resolve the actual URL for preview/download
  const resolvedDownloadUrl = selectedVariant?.download_url
    ? selectedVariant.download_url.startsWith("/api/")
      ? `${API_BASE_URL}${selectedVariant.download_url}`
      : selectedVariant.download_url
    : null;

  const rawPreviewUrl =
    selectedVariant?.download_url ||
    downloadResult?.thumbnail_url ||
    null;
  // Proxy all CDN URLs through the backend to bypass cross-origin / referrer blocks
  const previewUrl = rawPreviewUrl ? getProxyStreamUrl(rawPreviewUrl) : null;

  // Video HLS/source setup
  useEffect(() => {
    const videoEl = videoRef.current;
    if (!videoEl) return;

    if (!isVideoContent || !hasSelectedDownload || !selectedVariant?.download_url) {
      if (hlsRef.current) {
        hlsRef.current.destroy();
        hlsRef.current = null;
      }
      return;
    }

    const mediaUrl = selectedVariant.download_url;
    const hlsUrl = isHlsUrl(mediaUrl);

    if (hlsRef.current) {
      hlsRef.current.destroy();
      hlsRef.current = null;
    }

    if (hlsUrl && Hls.isSupported()) {
      const hls = new Hls();
      hls.loadSource(mediaUrl);
      hls.attachMedia(videoEl);
      hlsRef.current = hls;
      return () => {
        hls.destroy();
        hlsRef.current = null;
      };
    }

    videoEl.src = getProxyStreamUrl(mediaUrl);
    return () => {
      if (hlsRef.current) {
        hlsRef.current.destroy();
        hlsRef.current = null;
      }
    };
  }, [isVideoContent, hasSelectedDownload, selectedVariant?.download_url]);

  // Audio HLS/source setup
  useEffect(() => {
    const audioEl = audioRef.current;
    if (!audioEl) return;

    if (!isAudioContent || !audioVariant?.download_url) {
      if (hlsAudioRef.current) {
        hlsAudioRef.current.destroy();
        hlsAudioRef.current = null;
      }
      return;
    }

    const mediaUrl = audioVariant.download_url;

    if (hlsAudioRef.current) {
      hlsAudioRef.current.destroy();
      hlsAudioRef.current = null;
    }

    if (isHlsUrl(mediaUrl) && Hls.isSupported()) {
      const hls = new Hls();
      hls.loadSource(mediaUrl);
      hls.attachMedia(audioEl);
      hlsAudioRef.current = hls;
      return () => {
        hls.destroy();
        hlsAudioRef.current = null;
      };
    }

    audioEl.src = getProxyStreamUrl(mediaUrl);
    return () => {
      if (hlsAudioRef.current) {
        hlsAudioRef.current.destroy();
        hlsAudioRef.current = null;
      }
    };
  }, [isAudioContent, audioVariant?.download_url]);

  const fileSizeText =
    selectedVariant?.file_size_bytes
      ? `${(selectedVariant.file_size_bytes / (1024 * 1024)).toFixed(2)} MB`
      : undefined;

  return (
    <div className="flex flex-col items-center px-4 pt-16 pb-24">
      {/* Header with platform icon */}
      <div className="flex flex-col items-center gap-3 max-w-[855px] mb-10 w-full">
        <div className="flex items-center gap-3">
          <span className="shrink-0">{platform.icon}</span>
          <h1 className="text-[24px] sm:text-[32px] font-semibold text-foreground text-center leading-normal">
            {platform.title}
          </h1>
        </div>
        <p className="text-text-secondary text-[16px] sm:text-[20px] font-medium text-center max-w-[431px] leading-[24px] sm:leading-[28px]">
          {platform.description}
        </p>
      </div>

      {/* Content type tabs */}
      <div className="mb-10">
        <ContentTabs
          tabs={platform.tabs}
          activeTab={activeTab}
          onTabChange={setActiveTab}
        />
      </div>

      {/* URL Input */}
      <div className="mb-5 w-full flex justify-center">
        <UrlInput onSubmit={handleUrlSubmit} isLoading={isLoading} initialValue={initialUrl} elapsedSeconds={isLoading ? elapsedSeconds : undefined} />
      </div>

      {/* Cloudflare bot verification - shown for document platforms */}
      {isDocumentPlatform && (pendingUrl || !botVerified) && !downloadResult && (
        <div className="mb-5">
          <CloudflareCheck
            onVerified={() => setBotVerified(true)}
            verified={botVerified}
          />
        </div>
      )}

      {/* Content Preview / Result */}
      {downloadResult ? (
        <div className="w-full max-w-[1238px] flex flex-col lg:flex-row gap-8">
          {/* Preview area */}
          <div className="flex-1 min-h-[414px] rounded-[20px] border border-border bg-card overflow-hidden flex items-center justify-center">
            {isTextContentType ? (
              <div className="w-full h-full min-h-[414px] bg-[#1a1a2e] p-6 overflow-auto">
                <div className="mb-3 flex items-center gap-2">
                  <svg className="w-5 h-5 text-primary" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z" />
                  </svg>
                  <span className="text-white/80 text-sm font-medium">Text Content</span>
                </div>
                <pre className="whitespace-pre-wrap break-words text-white/90 text-base leading-7 font-sans">
                  {downloadResult.description || "No text content available."}
                </pre>
              </div>
            ) : isPdfContent && resolvedDownloadUrl ? (
              <iframe
                src={resolvedDownloadUrl}
                title={downloadResult.title || "PDF Preview"}
                className="w-full h-full min-h-[600px]"
                style={{ border: "none" }}
              />
            ) : isAudioContent ? (
              <div className="w-full h-full min-h-[414px] flex flex-col bg-[#1a1a2e]">
                {/* Cover art */}
                <div className="flex-1 flex items-center justify-center overflow-hidden">
                  {downloadResult.thumbnail_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={getProxyStreamUrl(downloadResult.thumbnail_url)}
                      alt={downloadResult.title || "Cover"}
                      className="w-full h-full object-contain"
                    />
                  ) : (
                    <div className="w-32 h-32 rounded-full bg-primary/20 flex items-center justify-center">
                      <svg className="w-16 h-16 text-primary" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z" />
                      </svg>
                    </div>
                  )}
                </div>
                {/* Audio player */}
                <div className="p-4 bg-black/40">
                  <audio
                    ref={audioRef}
                    controls
                    className="w-full"
                    preload="metadata"
                  />
                </div>
              </div>
            ) : previewUrl ? (
              isVideoContent && hasSelectedDownload ? (
                <video
                  ref={videoRef}
                  src={isHlsUrl(rawPreviewUrl || undefined) ? undefined : (previewUrl || undefined)}
                  controls
                  playsInline
                  className="w-full h-full min-h-[414px] max-h-[500px] object-contain bg-black"
                />
              ) : (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={previewUrl}
                  alt={downloadResult.title || "Preview"}
                  className="w-full h-full min-h-[414px] max-h-[500px] object-contain bg-black"
                />
              )
            ) : (
              <div className="w-full h-full min-h-[414px] bg-[#525659] flex items-center justify-center">
                <p className="text-white/60 text-sm">No Preview Available</p>
              </div>
            )}
          </div>

          {/* Details sidebar */}
          <div className="lg:w-[478px] flex flex-col gap-4">
            <h2 className="text-[20px] font-semibold text-foreground leading-7">
              {downloadResult.title || "Extracted Content"}
            </h2>
            <p className="text-[16px] font-medium text-text-muted leading-7">
              {downloadResult.description || "No description available."}
            </p>

            {downloadResult.variants?.length > 1 && (
              <select
                className="h-11 rounded-lg border border-border bg-card px-3 text-sm text-foreground"
                value={selectedVariant?.download_url || ""}
                onChange={(e) => {
                  const next = downloadResult.variants.find(
                    (variant) => variant.download_url === e.target.value
                  );
                  setSelectedVariant(next || null);
                }}
              >
                {downloadResult.variants.map((variant, index) => (
                  <option key={`${variant.label}-${index}`} value={variant.download_url || ""}>
                    {variant.label} ({variant.format})
                  </option>
                ))}
              </select>
            )}

            <div className="flex flex-col gap-2">
              {fileSizeText && (
                <p className="text-[14px] font-medium text-text-muted">
                  File size : {fileSizeText}
                </p>
              )}
              {(selectedVariant?.format || downloadResult.content_type) && (
                <p className="text-[14px] font-medium text-text-muted">
                  File type : {selectedVariant?.format || downloadResult.content_type}
                </p>
              )}
            </div>
            <a
              href={
                hasSelectedDownload
                  ? getProxyDownloadUrl(selectedVariant!.download_url!, downloadResult?.title)
                  : "#"
              }
              download
              className={`flex items-center justify-center w-full h-[40px] rounded-[33px] text-white text-[16px] font-medium transition-opacity ${
                hasSelectedDownload ? "bg-primary hover:opacity-90" : "bg-primary/50 pointer-events-none"
              }`}
            >
              {hasSelectedDownload ? "Download" : "No downloadable stream found"}
            </a>
          </div>
        </div>
      ) : isLoading ? (
        <div className="w-full max-w-[680px] flex flex-col gap-5">
          {isDocumentPlatform && (
            <DownloadProgress
              elapsedSeconds={elapsedSeconds}
              downloadedBytes={undefined}
              totalBytes={undefined}
            />
          )}
          <ContentPreview isEmpty={false}>
            <div className="flex flex-col items-center gap-4">
              <svg
                className="h-10 w-10 animate-spin text-primary"
                viewBox="0 0 24 24"
                fill="none"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                />
              </svg>
              <p className="text-muted text-base font-medium">
                Processing your request...
              </p>
            </div>
          </ContentPreview>
        </div>
      ) : (
        <ContentPreview isEmpty />
      )}

      {errorMessage && (
        <p className="mt-4 text-sm text-red-500 text-center max-w-[680px]">
          {errorMessage}
        </p>
      )}
    </div>
  );
}
