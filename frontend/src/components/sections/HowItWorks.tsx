"use client";

import { Copy, ClipboardPaste, Download } from "lucide-react";
import SectionHeader from "./SectionHeader";
import { useTranslation } from "@/lib/i18n";

const stepIcons = [
  <Copy key="copy" className="h-6 w-6 text-primary" />,
  <ClipboardPaste key="paste" className="h-6 w-6 text-primary" />,
  <Download key="download" className="h-6 w-6 text-primary" />,
];

export default function HowItWorks() {
  const { t } = useTranslation();

  const steps = [
    {
      num: 1,
      icon: stepIcons[0],
      title: t("howItWorks.step1Title"),
      bullets: [t("howItWorks.step1_1"), t("howItWorks.step1_2"), t("howItWorks.step1_3")],
    },
    {
      num: 2,
      icon: stepIcons[1],
      title: t("howItWorks.step2Title"),
      bullets: [t("howItWorks.step2_1"), t("howItWorks.step2_2"), t("howItWorks.step2_3")],
    },
    {
      num: 3,
      icon: stepIcons[2],
      title: t("howItWorks.step3Title"),
      bullets: [t("howItWorks.step3_1"), t("howItWorks.step3_2"), t("howItWorks.step3_3")],
    },
  ];

  return (
    <section className="w-full max-w-[1152px] mx-auto px-4 md:px-8 lg:px-0">
      <SectionHeader
        title={t("howItWorks.title")}
        subtitle={t("howItWorks.subtitle")}
        subtitleWidth="max-w-[340px]"
      />

      {/* Step indicators */}
      <div className="flex items-center justify-center mt-5 md:mt-8 mb-5 md:mb-10 max-w-[252px] md:max-w-[768px] mx-auto">
        {steps.map((step, i) => (
          <div key={step.num} className="flex items-center flex-1 last:flex-none">
            <div className="w-8 h-8 md:w-10 md:h-10 rounded-full bg-[#ece8f5] flex items-center justify-center text-[#2d2d2d] text-[24px] md:text-[20px] font-semibold shrink-0">
              {step.num}
            </div>
            {i < steps.length - 1 && (
              <div className="flex-1 h-px bg-[#c9c0dc] mx-[14px] md:mx-3" />
            )}
          </div>
        ))}
      </div>

      {/* Step cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 md:gap-3 lg:gap-6">
        {steps.map((step, idx) => (
          <div
            key={step.num}
            className={`bg-[#ece8f5] rounded-[20px] px-5 py-5 md:p-10 md:h-[295px] md:w-[340px] flex flex-col gap-5 ${
              idx < 2 ? "min-h-[215px]" : "min-h-[239px]"
            }`}
          >
            <div className="w-12 h-12 rounded-xl bg-white flex items-center justify-center">
              {step.icon}
            </div>
            <h3 className="text-[16px] font-semibold text-[#2d2d2d]">
              {step.title}
            </h3>
            <ul className="list-disc list-inside space-y-1 md:space-y-2 text-[16px] leading-[24px] text-[#404040]">
              {step.bullets.map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
