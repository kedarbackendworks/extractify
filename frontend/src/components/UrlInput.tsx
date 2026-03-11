"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "@/lib/i18n";

interface UrlInputProps {
  onSubmit: (url: string) => void;
  isLoading?: boolean;
  initialValue?: string;
  elapsedSeconds?: number;
}

/**
 * Normalise a user-entered string into a proper URL.
 * – Prepend "https://" when the protocol is missing.
 */
function normalizeUrl(raw: string): string {
  let cleaned = raw.trim();
  if (!cleaned) return "";

  // Decode common percent-encoded URLs (sometimes users paste encoded values)
  for (let i = 0; i < 2; i += 1) {
    try {
      const decoded = decodeURIComponent(cleaned);
      if (decoded === cleaned) break;
      cleaned = decoded;
    } catch {
      break;
    }
  }

  if (!/^https?:\/\//i.test(cleaned)) {
    cleaned = "https://" + cleaned;
  }
  return cleaned;
}

export default function UrlInput({ onSubmit, isLoading = false, initialValue = "", elapsedSeconds }: UrlInputProps) {
  const [url, setUrl] = useState(initialValue);
  const { t } = useTranslation();

  // Keep in sync when parent changes initialValue (e.g. query-param redirect)
  useEffect(() => {
    if (initialValue) setUrl(initialValue);
  }, [initialValue]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const normalized = normalizeUrl(url);
    if (normalized) {
      setUrl(normalized); // show the full URL back in the input
      onSubmit(normalized);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col sm:flex-row w-full max-w-[696px] gap-2 px-2">
      <input
        type="text"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder={t("input.placeholder")}
        className="w-full sm:flex-1 h-[52px] rounded-[40px] border border-border bg-card px-4 text-[16px] font-medium text-foreground placeholder:text-muted outline-none focus:border-primary transition-colors min-w-0"
      />
      <button
        type="submit"
        disabled={isLoading || !url.trim()}
        className="flex items-center justify-center rounded-[33px] bg-primary px-4 h-[52px] text-white text-[16px] font-medium hover:opacity-90 transition-opacity disabled:opacity-60 disabled:cursor-not-allowed shrink-0 gap-1 w-full sm:w-auto"
      >
        {isLoading ? (
          <div className="flex items-center gap-1">
            <svg
              className="h-6 w-6 animate-spin text-white"
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
            <span>{t("input.processing")}</span>
            {elapsedSeconds !== undefined && (
              <span>{elapsedSeconds}s</span>
            )}
          </div>
        ) : (
          t("input.download")
        )}
      </button>
    </form>
  );
}
