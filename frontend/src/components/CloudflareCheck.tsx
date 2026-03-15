"use client";

import { useState, useCallback } from "react";
import { useTranslation } from "@/lib/i18n";

interface CloudflareCheckProps {
  onVerified: () => void;
  verified?: boolean;
}

export default function CloudflareCheck({ onVerified, verified = false }: CloudflareCheckProps) {
  const [checked, setChecked] = useState(verified);
  const [verifying, setVerifying] = useState(false);
  const { t } = useTranslation();

  const handleCheck = useCallback(() => {
    if (checked || verifying) return;
    setVerifying(true);
    // Simulate a brief verification delay
    setTimeout(() => {
      setChecked(true);
      setVerifying(false);
      onVerified();
    }, 800);
  }, [checked, verifying, onVerified]);

  return (
    <div className="flex items-center gap-2 rounded-[12px] border border-border bg-card p-5">
      <div className="flex items-center gap-2">
        {/* Checkbox */}
        <button
          type="button"
          onClick={handleCheck}
          className="flex items-center justify-center size-6 shrink-0"
          aria-label={t("cloudflare.verify")}
        >
          {checked ? (
            <span className="flex items-center justify-center size-[18px] rounded-[4px] bg-green">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z" fill="white" />
              </svg>
            </span>
          ) : verifying ? (
            <span className="flex items-center justify-center size-[18px]">
              <svg className="animate-spin size-4 text-text-muted" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            </span>
          ) : (
            <span className="block size-[18px] rounded-[4px] border-2 border-[#c4c4c4] bg-white cursor-pointer" />
          )}
        </button>
        <span className="text-[16px] font-medium text-text-muted whitespace-nowrap">
          {t("cloudflare.verify")}
        </span>
      </div>
      {/* Cloudflare logo */}
      <div className="h-8 w-20 shrink-0 ml-auto flex items-center">
        <svg viewBox="0 0 120 40" className="h-full w-full" fill="none" xmlns="http://www.w3.org/2000/svg">
          <text x="30" y="32" fontFamily="Inter, sans-serif" fontSize="11" fontWeight="600" fill="#606060" letterSpacing="0.5">CLOUDFLARE</text>
          <g transform="translate(0, 8) scale(0.7)">
            <path d="M33.8 25.5c.2-.7.1-1.3-.2-1.7-.3-.4-.8-.6-1.4-.6l-18.6-.2c-.1 0-.2 0-.2-.1-.1-.1 0-.2 0-.3.1-.2.3-.4.5-.4l18.7-.2c1.4-.1 2.9-1.2 3.4-2.6l.7-1.8c0-.1.1-.2 0-.3-1-4.8-5.2-8.3-10.2-8.3-4.6 0-8.4 3-9.9 7.1-.9-.7-2.1-1-3.3-.9-2.1.3-3.8 2-4 4.1-.1.6 0 1.2.1 1.8C5 21.2 1.5 24.8 1.5 29.3c0 .4 0 .8.1 1.2 0 .1.1.2.2.2h31.8c.2 0 .3-.1.4-.3l.8-2.2c.3-.7.2-1.4 0-2.1z" fill="#F6821F"/>
            <path d="M37.1 21.3h-.3l-.2.7c-.2.7-.1 1.3.2 1.7.3.4.8.6 1.4.6l3.2.2c.1 0 .2 0 .2.1.1.1 0 .2 0 .3-.1.2-.3.4-.5.4l-3.3.2c-1.4.1-2.9 1.2-3.4 2.6l-.2.5c0 .1 0 .2.1.2h11.1c.2 0 .3-.1.3-.3.3-1 .5-2 .5-3.1 0-5.3-4.3-9.6-9.6-9.6-.5 0-.9 0-1.4.1" fill="#FBAD41"/>
          </g>
        </svg>
      </div>
    </div>
  );
}
