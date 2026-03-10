"use client";

import Link from "next/link";
import { useTranslation } from "@/lib/i18n";

const platformLinks = [
  { name: "Instagram", href: "/platform/instagram" },
  { name: "YouTube", href: "/platform/youtube" },
  { name: "TikTok", href: "/platform/tiktok" },
  { name: "Twitter / X", href: "/platform/twitter" },
  { name: "Facebook", href: "/platform/facebook" },
  { name: "Snapchat", href: "/platform/snapchat" },
  { name: "LinkedIn", href: "/platform/linkedin" },
  { name: "Pinterest", href: "/platform/pinterest" },
];

const resourceKeys = [
  { nameKey: "footer.blog", href: "/blogs" },
  { nameKey: "footer.faq", href: "/#faq" },
  { nameKey: "footer.reviews", href: "/#reviews" },
];

const legalKeys = [
  { nameKey: "footer.privacy", href: "/privacy" },
  { nameKey: "footer.terms", href: "/terms" },
];

export default function Footer() {
  const { t } = useTranslation();

  return (
    <footer className="w-full bg-[#1a1a2e] text-white">
      <div className="mx-auto max-w-[1068px] px-6 py-14">
        <div className="flex flex-col md:flex-row gap-12 md:gap-8 justify-between">
          {/* Brand */}
          <div className="max-w-[280px]">
            <h3 className="text-[20px] font-bold text-white mb-3">
              Extractify
            </h3>
            <p className="text-[14px] leading-[24px] text-gray-400">
              {t("footer.description")}
            </p>
            {/* Social icons */}
            <div className="flex gap-3 mt-5">
              {["Twitter", "Facebook", "Instagram", "YouTube"].map((s) => (
                <a
                  key={s}
                  href="#"
                  className="w-9 h-9 rounded-full bg-white/10 flex items-center justify-center text-[12px] text-gray-300 hover:bg-white/20 transition-colors"
                  aria-label={s}
                >
                  {s[0]}
                </a>
              ))}
            </div>
          </div>

          {/* Platforms */}
          <div>
            <h4 className="text-[14px] font-semibold text-white mb-4 uppercase tracking-wide">
              {t("footer.platforms")}
            </h4>
            <ul className="space-y-2">
              {platformLinks.map((l) => (
                <li key={l.name}>
                  <Link
                    href={l.href}
                    className="text-[14px] text-gray-400 hover:text-white transition-colors"
                  >
                    {l.name}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          {/* Resources */}
          <div>
            <h4 className="text-[14px] font-semibold text-white mb-4 uppercase tracking-wide">
              {t("footer.resources")}
            </h4>
            <ul className="space-y-2">
              {resourceKeys.map((l) => (
                <li key={l.nameKey}>
                  <Link
                    href={l.href}
                    className="text-[14px] text-gray-400 hover:text-white transition-colors"
                  >
                    {t(l.nameKey)}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          {/* Legal */}
          <div>
            <h4 className="text-[14px] font-semibold text-white mb-4 uppercase tracking-wide">
              {t("footer.legal")}
            </h4>
            <ul className="space-y-2">
              {legalKeys.map((l) => (
                <li key={l.nameKey}>
                  <Link
                    href={l.href}
                    className="text-[14px] text-gray-400 hover:text-white transition-colors"
                  >
                    {t(l.nameKey)}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* Divider + Copyright */}
        <div className="mt-12 pt-6 border-t border-white/10 flex flex-col sm:flex-row justify-between items-center gap-4">
          <p className="text-[13px] text-gray-500">
            © {new Date().getFullYear()} Extractify. {t("footer.rights")}
          </p>
          <p className="text-[13px] text-gray-500">
            {t("footer.madeWith")}
          </p>
        </div>
      </div>
    </footer>
  );
}
