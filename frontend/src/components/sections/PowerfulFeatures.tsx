"use client";

import { Zap, Globe, UserX, DollarSign, Shield, Infinity } from "lucide-react";
import SectionHeader from "./SectionHeader";
import { useTranslation } from "@/lib/i18n";

const featureIcons = [
  <Zap key="zap" className="h-6 w-6 text-primary" />,
  <Globe key="globe" className="h-6 w-6 text-primary" />,
  <UserX key="userx" className="h-6 w-6 text-primary" />,
  <DollarSign key="dollar" className="h-6 w-6 text-primary" />,
  <Shield key="shield" className="h-6 w-6 text-primary" />,
  <Infinity key="infinity" className="h-6 w-6 text-primary" />,
];

const featureKeys = [
  { titleKey: "features.f1Title", descKey: "features.f1Desc" },
  { titleKey: "features.f2Title", descKey: "features.f2Desc" },
  { titleKey: "features.f3Title", descKey: "features.f3Desc" },
  { titleKey: "features.f4Title", descKey: "features.f4Desc" },
  { titleKey: "features.f5Title", descKey: "features.f5Desc" },
  { titleKey: "features.f6Title", descKey: "features.f6Desc" },
];

export default function PowerfulFeatures() {
  const { t } = useTranslation();

  return (
    <section className="w-full max-w-[1152px] mx-auto px-4 md:px-8 lg:px-0">
      <SectionHeader
        title={t("features.title")}
        subtitle={t("features.subtitle")}
        subtitleWidth="max-w-[480px]"
      />

      <div className="mt-10 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
        {featureKeys.map((f, i) => (
          <div
            key={f.titleKey}
            className="bg-white rounded-2xl shadow-[2px_2px_6px_0px_rgba(211,211,211,0.25)] px-10 py-6 flex flex-col gap-3"
          >
            <div className="w-10 h-10 rounded-lg bg-[#ece8f5] flex items-center justify-center">
              {featureIcons[i]}
            </div>
            <h3 className="text-[16px] font-semibold text-[#2d2d2d]">
              {t(f.titleKey)}
            </h3>
            <p className="text-[14px] leading-[22px] text-[#606060]">
              {t(f.descKey)}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
