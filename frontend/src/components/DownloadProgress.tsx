"use client";

import { useTranslation } from "@/lib/i18n";

interface DownloadProgressProps {
  /** Elapsed time in seconds */
  elapsedSeconds: number;
  /** Estimated time remaining in seconds */
  estimatedRemainingSeconds?: number;
  /** Downloaded bytes so far */
  downloadedBytes?: number;
  /** Total file size in bytes */
  totalBytes?: number;
  /** Called when user clicks the download button */
  onDownload?: () => void;
  /** Whether the download button should be active */
  downloadReady?: boolean;
}

export default function DownloadProgress({
  elapsedSeconds,
  estimatedRemainingSeconds,
  downloadedBytes,
  totalBytes,
  onDownload,
  downloadReady = false,
}: DownloadProgressProps) {
  const { t } = useTranslation();
  const downloadedMB = downloadedBytes ? (downloadedBytes / (1024 * 1024)).toFixed(2) : null;
  const totalMB = totalBytes ? (totalBytes / (1024 * 1024)).toFixed(2) : null;
  const progressPercent = downloadedBytes && totalBytes ? Math.min((downloadedBytes / totalBytes) * 100, 100) : 0;

  return (
    <div className="flex items-center justify-center rounded-[12px] border border-border bg-card p-3 sm:p-5">
      <div className="flex flex-col sm:flex-row flex-1 gap-3 items-start">
        {/* Envelope icon */}
        <div className="shrink-0 size-10 flex items-center justify-center hidden sm:flex">
          <svg width="40" height="40" viewBox="0 0 72 72" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect width="72" height="72" rx="8" fill="#F3F4F6" />
            <path d="M20 28L36 38L52 28V46C52 47.1 51.1 48 50 48H22C20.9 48 20 47.1 20 46V28Z" fill="#D1D5DB" />
            <path d="M52 28L36 38L20 28V26C20 24.9 20.9 24 22 24H50C51.1 24 52 24.9 52 26V28Z" fill="#E5E7EB" />
            <path d="M36 16L40 24H32L36 16Z" fill="#EF4444" />
            <path d="M33 16L37 24H29L33 16Z" fill="#DC2626" opacity="0.7" />
          </svg>
        </div>

        {/* Content */}
        <div className="flex flex-1 flex-col gap-3 items-start justify-center w-full">
          <p className="text-[14px] sm:text-[16px] font-medium text-foreground">
            {t("download.waiting").replace("{seconds}", String(estimatedRemainingSeconds ?? elapsedSeconds))}
          </p>

          {/* Progress bar */}
          <div className="relative h-[6px] w-full">
            <div className="absolute inset-0 rounded-[14px] bg-progress-track border-[0.5px] border-[#e2e2e2]" />
            <div
              className="absolute top-0 left-0 h-[6px] rounded-[14px] bg-green transition-all duration-300"
              style={{ width: `${progressPercent}%` }}
            />
          </div>

          {/* Size info */}
          {downloadedMB && totalMB && (
            <p className="text-[14px] font-medium text-text-hint">
              {t("download.sizeProgress").replace("{downloaded}", downloadedMB!).replace("{total}", totalMB!)}
            </p>
          )}

          {/* Download button */}
          {downloadReady && onDownload && (
            <button
              type="button"
              onClick={onDownload}
              className="flex items-center justify-center rounded-[33px] bg-primary px-4 py-2 text-[14px] font-medium text-white hover:opacity-90 transition-opacity"
            >
              {t("download.button")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
