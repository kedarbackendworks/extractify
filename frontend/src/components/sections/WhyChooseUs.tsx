"use client";

import { Zap, Lock, CreditCard, MonitorSmartphone } from "lucide-react";
import SectionHeader from "./SectionHeader";
import { useTranslation } from "@/lib/i18n";

const featureIcons = [
  <Zap key="zap" className="h-6 w-6 text-primary" />,
  <Lock key="lock" className="h-6 w-6 text-primary" />,
  <CreditCard key="card" className="h-6 w-6 text-primary" />,
  <MonitorSmartphone key="monitor" className="h-6 w-6 text-primary" />,
];

const featureKeys = [
  { titleKey: "whyChooseUs.f1Title", descKey: "whyChooseUs.f1Desc" },
  { titleKey: "whyChooseUs.f2Title", descKey: "whyChooseUs.f2Desc" },
  { titleKey: "whyChooseUs.f3Title", descKey: "whyChooseUs.f3Desc" },
  { titleKey: "whyChooseUs.f4Title", descKey: "whyChooseUs.f4Desc" },
];

export default function WhyChooseUs() {
  const { t } = useTranslation();

  return (
    <section className="w-full max-w-[1152px] mx-auto px-4 md:px-8 lg:px-0">
      <SectionHeader
        title={t("whyChooseUs.title")}
        subtitle={t("whyChooseUs.subtitle")}
        subtitleWidth="max-w-[614px]"
      />

      <div className="mt-10 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        {featureKeys.map((f, i) => (
          <div
            key={f.titleKey}
            className="bg-[#ece8f5] rounded-[20px] min-h-[350px] p-5 flex flex-col items-center text-center gap-4"
          >
            <div className="w-12 h-12 rounded-xl bg-white flex items-center justify-center">
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
