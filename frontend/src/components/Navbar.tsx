"use client";

import Link from "next/link";
import { useState, useRef, useEffect } from "react";
import { ChevronDown } from "lucide-react";
import { socialPlatforms, documentPlatforms } from "@/lib/platforms";
import { useTranslation, localeConfig, type Locale } from "@/lib/i18n";

export default function Navbar() {
  const [platformsOpen, setPlatformsOpen] = useState(false);
  const [langOpen, setLangOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const langRef = useRef<HTMLDivElement>(null);
  const { t, locale, setLocale } = useTranslation();

  // Close on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node)
      ) {
        setPlatformsOpen(false);
      }
      if (
        langRef.current &&
        !langRef.current.contains(e.target as Node)
      ) {
        setLangOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <header className="sticky top-0 z-50 w-full bg-primary-light shadow-[0px_1px_6px_0px_rgba(170,170,170,0.25)]">
      <div className="mx-auto flex max-w-[1440px] items-center justify-between px-4 md:px-16 py-5">
        {/* Logo */}
        <Link href="/" className="text-primary font-semibold text-[32px] leading-none">
          Logo
        </Link>

        {/* Nav items */}
        <nav className="flex items-center gap-4">
          <Link
            href="/blogs"
            className="hidden md:flex items-center justify-center rounded-[33px] py-2 text-foreground text-[16px] font-medium hover:text-primary transition-colors"
          >
            {t("nav.blogs")}
          </Link>
          <Link
            href="/#faq"
            className="hidden md:flex items-center justify-center rounded-[33px] py-2 text-foreground text-[16px] font-medium hover:text-primary transition-colors"
          >
            {t("nav.faq")}
          </Link>
          <Link
            href="/#reviews"
            className="hidden md:flex items-center justify-center rounded-[33px] py-2 text-foreground text-[16px] font-medium hover:text-primary transition-colors"
          >
            {t("nav.review")}
          </Link>

          <div className="flex items-center gap-3">
            {/* Language selector */}
            <div className="relative" ref={langRef}>
              <button
                onClick={() => setLangOpen(!langOpen)}
                className="flex items-center justify-center gap-2 rounded-[33px] border border-border-light bg-card px-2.5 py-2 sm:px-3"
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={`https://flagcdn.com/w40/${localeConfig[locale].flagCode}.png`} alt={localeConfig[locale].label} className="w-5 h-auto rounded-[2px]" />
                <span className="text-foreground text-base sm:text-lg font-semibold">{localeConfig[locale].label}</span>
                <ChevronDown className={`h-4 w-4 transition-transform ${langOpen ? "rotate-180" : ""}`} />
              </button>

              {langOpen && (
                <div className="fixed left-4 right-4 sm:absolute sm:left-auto sm:right-0 top-[72px] sm:top-full z-50 mt-0 sm:mt-2 max-h-[60vh] overflow-y-auto overscroll-contain rounded-xl border border-border bg-card py-2 shadow-lg sm:w-56">
                  {(Object.keys(localeConfig) as Locale[]).map((code) => (
                    <button
                      key={code}
                      onClick={() => { setLocale(code); setLangOpen(false); }}
                      className={`flex w-full items-center gap-2 px-3 py-2 text-sm font-medium transition-colors hover:bg-background sm:gap-3 sm:px-4 ${
                        locale === code ? "text-primary bg-background" : "text-foreground"
                      }`}
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={`https://flagcdn.com/w40/${localeConfig[code].flagCode}.png`} alt={localeConfig[code].label} className="w-5 h-auto rounded-[2px]" />
                      <span className="truncate text-left">{localeConfig[code].nativeName}</span>
                      <span className="ml-auto text-xs text-muted">{localeConfig[code].label}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Platforms dropdown */}
            <div className="relative" ref={dropdownRef}>
              <button
                onClick={() => setPlatformsOpen(!platformsOpen)}
                className="flex items-center gap-1 rounded-[33px] border border-border-light bg-card px-4 py-2 text-foreground text-[16px] font-medium hover:border-primary transition-colors"
              >
                {t("nav.platforms")}
                <ChevronDown
                  className={`h-5 w-5 transition-transform ${platformsOpen ? "rotate-180" : ""}`}
                />
              </button>

              {platformsOpen && (
                <div className="absolute right-0 top-full mt-2 w-[calc(100vw-2rem)] max-w-[520px] rounded-2xl border border-border bg-card p-5 shadow-lg">
                  {/* Social Media */}
                  <p className="text-xs font-semibold uppercase tracking-wider text-muted mb-2">
                    {t("nav.socialMedia")}
                  </p>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-1 mb-4">
                    {socialPlatforms.map((p) => (
                      <Link
                        key={p.slug}
                        href={`/platform/${p.slug}`}
                        className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm font-medium text-foreground hover:bg-background hover:text-primary transition-colors"
                        onClick={() => setPlatformsOpen(false)}
                      >
                        <span
                          className="h-2 w-2 rounded-full shrink-0"
                          style={{ backgroundColor: p.color }}
                        />
                        {p.name}
                      </Link>
                    ))}
                  </div>

                  <hr className="border-border mb-4" />

                  {/* Document Platforms */}
                  <p className="text-xs font-semibold uppercase tracking-wider text-muted mb-2">
                    {t("nav.documents")}
                  </p>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-1">
                    {documentPlatforms.map((p) => (
                      <Link
                        key={p.slug}
                        href={`/platform/${p.slug}`}
                        className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm font-medium text-foreground hover:bg-background hover:text-primary transition-colors"
                        onClick={() => setPlatformsOpen(false)}
                      >
                        <span
                          className="h-2 w-2 rounded-full shrink-0"
                          style={{ backgroundColor: p.color }}
                        />
                        {p.name}
                      </Link>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </nav>
      </div>
    </header>
  );
}
