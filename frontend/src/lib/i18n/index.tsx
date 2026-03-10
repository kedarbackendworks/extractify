"use client";

import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from "react";
import en from "./en";
import es from "./es";
import fr from "./fr";
import de from "./de";
import pt from "./pt";
import hi from "./hi";
import ja from "./ja";
import ar from "./ar";
import zh from "./zh";
import ko from "./ko";
import ru from "./ru";
import it from "./it";
import tr from "./tr";
import nl from "./nl";
import pl from "./pl";
import id from "./id";
import th from "./th";
import vi from "./vi";
import uk from "./uk";
import bn from "./bn";

export type Locale =
  | "en" | "es" | "fr" | "de" | "pt" | "hi" | "ja" | "ar"
  | "zh" | "ko" | "ru" | "it" | "tr" | "nl" | "pl" | "id"
  | "th" | "vi" | "uk" | "bn";

export const localeConfig: Record<Locale, { flag: string; label: string; nativeName: string }> = {
  en: { flag: "🇺🇸", label: "EN", nativeName: "English" },
  es: { flag: "🇪🇸", label: "ES", nativeName: "Español" },
  fr: { flag: "🇫🇷", label: "FR", nativeName: "Français" },
  de: { flag: "🇩🇪", label: "DE", nativeName: "Deutsch" },
  pt: { flag: "🇧🇷", label: "PT", nativeName: "Português" },
  hi: { flag: "🇮🇳", label: "HI", nativeName: "हिन्दी" },
  ja: { flag: "🇯🇵", label: "JA", nativeName: "日本語" },
  ar: { flag: "🇸🇦", label: "AR", nativeName: "العربية" },
  zh: { flag: "🇨🇳", label: "ZH", nativeName: "中文" },
  ko: { flag: "🇰🇷", label: "KO", nativeName: "한국어" },
  ru: { flag: "🇷🇺", label: "RU", nativeName: "Русский" },
  it: { flag: "🇮🇹", label: "IT", nativeName: "Italiano" },
  tr: { flag: "🇹🇷", label: "TR", nativeName: "Türkçe" },
  nl: { flag: "🇳🇱", label: "NL", nativeName: "Nederlands" },
  pl: { flag: "🇵🇱", label: "PL", nativeName: "Polski" },
  id: { flag: "🇮🇩", label: "ID", nativeName: "Bahasa Indonesia" },
  th: { flag: "🇹🇭", label: "TH", nativeName: "ไทย" },
  vi: { flag: "🇻🇳", label: "VI", nativeName: "Tiếng Việt" },
  uk: { flag: "🇺🇦", label: "UK", nativeName: "Українська" },
  bn: { flag: "🇧🇩", label: "BN", nativeName: "বাংলা" },
};

const translations: Record<Locale, Record<string, string>> = {
  en, es, fr, de, pt, hi, ja, ar,
  zh, ko, ru, it, tr, nl, pl, id,
  th, vi, uk, bn,
};

interface I18nContextType {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: string) => string;
}

const I18nContext = createContext<I18nContextType>({
  locale: "en",
  setLocale: () => {},
  t: (key: string) => key,
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("en");

  useEffect(() => {
    const saved = localStorage.getItem("locale") as Locale | null;
    if (saved && translations[saved]) {
      setLocaleState(saved);
      document.documentElement.lang = saved;
      document.documentElement.dir = saved === "ar" ? "rtl" : "ltr";
    }
  }, []);

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    localStorage.setItem("locale", l);
    document.documentElement.lang = l;
    document.documentElement.dir = l === "ar" ? "rtl" : "ltr";
  }, []);

  const t = useCallback(
    (key: string): string => {
      return translations[locale]?.[key] || translations.en[key] || key;
    },
    [locale]
  );

  return (
    <I18nContext.Provider value={{ locale, setLocale, t }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useTranslation() {
  return useContext(I18nContext);
}
