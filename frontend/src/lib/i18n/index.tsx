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

export const localeConfig: Record<Locale, { flagCode: string; label: string; nativeName: string }> = {
  en: { flagCode: "us", label: "EN", nativeName: "English" },
  es: { flagCode: "es", label: "ES", nativeName: "Español" },
  fr: { flagCode: "fr", label: "FR", nativeName: "Français" },
  de: { flagCode: "de", label: "DE", nativeName: "Deutsch" },
  pt: { flagCode: "br", label: "PT", nativeName: "Português" },
  hi: { flagCode: "in", label: "HI", nativeName: "हिन्दी" },
  ja: { flagCode: "jp", label: "JA", nativeName: "日本語" },
  ar: { flagCode: "sa", label: "AR", nativeName: "العربية" },
  zh: { flagCode: "cn", label: "ZH", nativeName: "中文" },
  ko: { flagCode: "kr", label: "KO", nativeName: "한국어" },
  ru: { flagCode: "ru", label: "RU", nativeName: "Русский" },
  it: { flagCode: "it", label: "IT", nativeName: "Italiano" },
  tr: { flagCode: "tr", label: "TR", nativeName: "Türkçe" },
  nl: { flagCode: "nl", label: "NL", nativeName: "Nederlands" },
  pl: { flagCode: "pl", label: "PL", nativeName: "Polski" },
  id: { flagCode: "id", label: "ID", nativeName: "Bahasa Indonesia" },
  th: { flagCode: "th", label: "TH", nativeName: "ไทย" },
  vi: { flagCode: "vn", label: "VI", nativeName: "Tiếng Việt" },
  uk: { flagCode: "ua", label: "UK", nativeName: "Українська" },
  bn: { flagCode: "bd", label: "BN", nativeName: "বাংলা" },
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
