"use client";

import { CheckCircle } from "lucide-react";
import SectionHeader from "./SectionHeader";
import { useTranslation } from "@/lib/i18n";

const expectKeys = [
  { titleKey: "expect.i1Title", descKey: "expect.i1Desc" },
  { titleKey: "expect.i2Title", descKey: "expect.i2Desc" },
  { titleKey: "expect.i3Title", descKey: "expect.i3Desc" },
  { titleKey: "expect.i4Title", descKey: "expect.i4Desc" },
  { titleKey: "expect.i5Title", descKey: "expect.i5Desc" },
  { titleKey: "expect.i6Title", descKey: "expect.i6Desc" },
];

export default function WhatToExpect() {
  const { t } = useTranslation();

  return (
    <section className="w-full max-w-[1152px] mx-auto px-4 md:px-8 lg:px-0">
      <SectionHeader
        title={t("expect.title")}
        subtitle={t("expect.subtitle")}
        subtitleWidth="max-w-[480px]"
      />

      <div className="mt-10 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-8">
        {expectKeys.map((e) => (
          <div key={e.titleKey} className="flex gap-4">
            <CheckCircle className="h-6 w-6 text-primary shrink-0 mt-0.5" />
            <div>
              <h3 className="text-[16px] font-semibold text-[#2d2d2d] mb-1">
                {t(e.titleKey)}
              </h3>
              <p className="text-[14px] leading-[22px] text-[#606060]">
                {t(e.descKey)}
              </p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
