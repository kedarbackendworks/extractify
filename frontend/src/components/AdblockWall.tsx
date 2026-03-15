"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useTranslation } from "@/lib/i18n";

type DetectionState = "pending" | "blocked" | "rechecking" | "clear";

/**
 * Multi-method adblock detection (works with uBlock Origin, uBlock Origin Lite,
 * AdBlock Plus, AdGuard, and similar extensions):
 *
 * 1. Bait element — insert a realistically-sized div with IDs, classes and
 *    attributes that appear on major cosmetic filter lists (EasyList etc.).
 *    After a short delay, check if the browser has hidden or zero-sized it.
 *
 * 2. Bait script — dynamically inject a <script> tag pointing to a well-known
 *    ad-serving path (pagead2.googlesyndication.com/pagead/js/adsbygoogle.js).
 *    This is blocked by virtually every ad-blocker's network filter rules,
 *    including MV3 declarative net request extensions.
 *
 * 3. Bait fetch — attempt to fetch the local `/ads.js` file. Catches blockers
 *    that broadly match "ads" in first-party paths.
 *
 * All three run in parallel; flag as blocked if *any* trips.
 */
async function detectAdblock(): Promise<boolean> {
  // Method 1 — cosmetic / element hiding filter detection
  const baitElement = (): Promise<boolean> =>
    new Promise((resolve) => {
      // Wrapper hides the bait from the user via clip, but keeps it in-flow
      // so ad-blockers' cosmetic filters will detect and hide/remove it.
      const wrapper = document.createElement("div");
      wrapper.style.cssText =
        "position:absolute;top:0;left:0;width:0;height:0;overflow:hidden;pointer-events:none;z-index:-1;";

      const bait = document.createElement("div");
      // IDs & classes that EasyList / uBlock cosmetic filters target
      bait.id = "ad_banner";
      bait.className =
        "ad-banner adsbox ad-placeholder textad banner_ad pub_300x250";
      bait.setAttribute("data-ad-slot", "1234567890");
      bait.setAttribute("data-ad-client", "ca-pub-1234567890");
      // Standard IAB ad size so filter rules match dimension selectors
      bait.style.cssText =
        "width:300px;height:250px;background:transparent;";

      // Second bait element — targets Google AdSense-specific selectors
      const bait2 = document.createElement("div");
      bait2.className = "adsbygoogle";
      bait2.setAttribute("data-ad-slot", "test");
      bait2.style.cssText =
        "width:728px;height:90px;background:transparent;";

      wrapper.appendChild(bait);
      wrapper.appendChild(bait2);
      document.body.appendChild(wrapper);

      setTimeout(() => {
        let blocked = false;
        for (const el of [bait, bait2]) {
          if (!document.body.contains(wrapper) || !wrapper.contains(el)) {
            // The ad-blocker removed the element from the DOM entirely
            blocked = true;
            break;
          }
          const s = getComputedStyle(el);
          if (
            el.offsetHeight === 0 ||
            el.offsetWidth === 0 ||
            el.clientHeight === 0 ||
            s.display === "none" ||
            s.visibility === "hidden" ||
            s.opacity === "0"
          ) {
            blocked = true;
            break;
          }
        }
        wrapper.remove();
        resolve(blocked);
      }, 200);
    });

  // Method 2 — network request to a well-known third-party ad-serving URL
  // uBlock Origin Lite (MV3) blocks this via declarative net request rules.
  const baitScript = (): Promise<boolean> =>
    new Promise((resolve) => {
      const script = document.createElement("script");
      script.src =
        "https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js";
      script.async = true;
      // If the script loads => no adblocker. If error => blocked.
      script.onload = () => {
        script.remove();
        resolve(false);
      };
      script.onerror = () => {
        script.remove();
        resolve(true);
      };
      document.head.appendChild(script);

      // Safety timeout — if neither fires within 2 s, assume blocked
      setTimeout(() => {
        script.remove();
        resolve(true);
      }, 2000);
    });

  // Method 3 — first-party fetch (catches broad "ads" path filters)
  const baitFetch = async (): Promise<boolean> => {
    try {
      const resp = await fetch("/ads.js", {
        method: "HEAD",
        cache: "no-store",
      });
      return !resp.ok;
    } catch {
      return true;
    }
  };

  const results = await Promise.all([
    baitElement(),
    baitScript(),
    baitFetch(),
  ]);

  return results.some(Boolean);
}

export default function AdblockWall({
  children,
}: {
  children: React.ReactNode;
}) {
  const [state, setState] = useState<DetectionState>("pending");
  const [recheckError, setRecheckError] = useState(false);
  const [shaking, setShaking] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const recheckBtnRef = useRef<HTMLButtonElement>(null);
  const { t } = useTranslation();

  // ── Initial detection (silent — no modal shown) ────────────────────
  useEffect(() => {
    let cancelled = false;
    detectAdblock().then((blocked) => {
      if (!cancelled) setState(blocked ? "blocked" : "clear");
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // ── Body scroll lock & Escape suppression ─────────────────────────
  useEffect(() => {
    if (state !== "blocked") return;

    document.body.style.overflow = "hidden";

    const suppressEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
      }
    };
    document.addEventListener("keydown", suppressEscape, true);

    return () => {
      document.body.style.overflow = "";
      document.removeEventListener("keydown", suppressEscape, true);
    };
  }, [state]);

  // ── Focus trap ────────────────────────────────────────────────────
  useEffect(() => {
    if (state !== "blocked") return;

    const trap = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;

      const dialog = dialogRef.current;
      if (!dialog) return;

      const focusable = dialog.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    document.addEventListener("keydown", trap);

    // Initial focus
    recheckBtnRef.current?.focus();

    return () => document.removeEventListener("keydown", trap);
  }, [state]);

  // ── Recheck handler ───────────────────────────────────────────────
  const handleRecheck = useCallback(async () => {
    setRecheckError(false);
    setShaking(false);
    setState("rechecking");

    const blocked = await detectAdblock();

    if (blocked) {
      setState("blocked");
      setRecheckError(true);
      setShaking(true);
      // Remove shake class after animation ends
      setTimeout(() => setShaking(false), 600);
      // Re-focus the button for accessibility
      setTimeout(() => recheckBtnRef.current?.focus(), 50);
    } else {
      setState("clear");
    }
  }, []);

  // ── Render ────────────────────────────────────────────────────────
  // During initial silent check or when clear, just show children
  if (state === "pending" || state === "clear") return <>{children}</>;

  // Show wall only when blocked or rechecking (user clicked the button)
  return (
    <>
      {children}

      {(state === "blocked" || state === "rechecking") && (
        <div
          className="fixed inset-0 z-[9999] flex items-center justify-center"
          style={{ backdropFilter: "blur(12px)", WebkitBackdropFilter: "blur(12px)" }}
          aria-hidden="true"
        >
          {/* Dark scrim */}
          <div
            className="absolute inset-0"
            style={{ backgroundColor: "rgba(0,0,0,0.85)" }}
          />

          {/* Modal */}
          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="adwall-title"
            className={`relative z-10 mx-4 w-full max-w-md rounded-2xl bg-white px-6 py-10 text-center shadow-2xl sm:px-10 ${
              shaking ? "animate-shake" : ""
            }`}
          >
            {/* Logo / icon placeholder */}
            <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-full bg-primary/10">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                className="h-8 w-8 text-primary"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M12 9v2m0 4h.01M12 3a9 9 0 110 18 9 9 0 010-18z"
                />
              </svg>
            </div>

            <h2
              id="adwall-title"
              className="mb-3 text-xl font-semibold text-foreground sm:text-2xl"
            >
              {t("adblock.title")}
            </h2>

            <p className="mb-2 text-sm leading-relaxed text-text-secondary sm:text-base">
              {t("adblock.message1")}
            </p>
            <p className="mb-8 text-sm leading-relaxed text-text-secondary sm:text-base">
              {t("adblock.message2")}
            </p>

            {/* Error message */}
            {recheckError && (
              <p className="mb-4 text-sm font-medium text-red-600" role="alert">
                {t("adblock.error")}
              </p>
            )}

            {/* CTA button */}
            <button
              ref={recheckBtnRef}
              type="button"
              onClick={handleRecheck}
              disabled={state === "rechecking"}
              className="inline-flex items-center justify-center gap-2 rounded-full bg-primary px-8 py-3 text-base font-medium text-white transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 disabled:opacity-60"
            >
              {state === "rechecking" ? (
                <>
                  <svg
                    className="h-5 w-5 animate-spin"
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
                  {t("adblock.checking")}
                </>
              ) : (
                t("adblock.refresh")
              )}
            </button>
          </div>
        </div>
      )}

    </>
  );
}
