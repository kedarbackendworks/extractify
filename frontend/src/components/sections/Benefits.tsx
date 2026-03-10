"use client";

import { Download, Smartphone, Film, Shield, Zap, Globe } from "lucide-react";
import SectionHeader from "./SectionHeader";
import { useTranslation } from "@/lib/i18n";

const benefitIcons = [
  <Download key="dl" className="h-6 w-6 text-primary" />,
  <Smartphone key="sm" className="h-6 w-6 text-primary" />,
  <Film key="film" className="h-6 w-6 text-primary" />,
  <Shield key="shield" className="h-6 w-6 text-primary" />,
  <Zap key="zap" className="h-6 w-6 text-primary" />,
  <Globe key="globe" className="h-6 w-6 text-primary" />,
];

const benefitKeys = [
  { titleKey: "benefits.b1Title", descKey: "benefits.b1Desc" },
  { titleKey: "benefits.b2Title", descKey: "benefits.b2Desc" },
  { titleKey: "benefits.b3Title", descKey: "benefits.b3Desc" },
  { titleKey: "benefits.b4Title", descKey: "benefits.b4Desc" },
  { titleKey: "benefits.b5Title", descKey: "benefits.b5Desc" },
  { titleKey: "benefits.b6Title", descKey: "benefits.b6Desc" },
];

export default function Benefits() {
  const { t } = useTranslation();

  const renderCard = (index: number) => (
    <div
      key={benefitKeys[index].titleKey}
      className="bg-white rounded-2xl shadow-[2px_2px_6px_0px_rgba(211,211,211,0.25)] p-8 flex flex-col gap-4"
    >
      <div className="w-10 h-10 rounded-lg bg-[#ece8f5] flex items-center justify-center">
        {benefitIcons[index]}
      </div>
      <h3 className="text-[16px] font-semibold text-[#2d2d2d]">
        {t(benefitKeys[index].titleKey)}
      </h3>
      <p className="text-[14px] leading-[22px] text-[#606060]">
        {t(benefitKeys[index].descKey)}
      </p>
    </div>
  );

  return (
    <section className="w-full max-w-[1152px] mx-auto px-4 md:px-8 lg:px-0">
      <SectionHeader
        title={t("benefits.title")}
        subtitle={t("benefits.subtitle")}
        subtitleWidth="max-w-[480px]"
      />

      <div className="mt-10 grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="flex flex-col gap-6">
          {[0, 1].map(renderCard)}
        </div>
        <div className="flex flex-col gap-6">
          {[2, 3].map(renderCard)}
        </div>
        <div className="flex flex-col gap-6">
          {[4, 5].map(renderCard)}
        </div>
      </div>
    </section>
  );
}
