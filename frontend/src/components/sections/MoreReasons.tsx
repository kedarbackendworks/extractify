"use client";

import SectionHeader from "./SectionHeader";
import { useTranslation } from "@/lib/i18n";

const reasonKeys = [
  { num: "01", titleKey: "moreReasons.r1Title", descKey: "moreReasons.r1Desc" },
  { num: "02", titleKey: "moreReasons.r2Title", descKey: "moreReasons.r2Desc" },
  { num: "03", titleKey: "moreReasons.r3Title", descKey: "moreReasons.r3Desc" },
  { num: "04", titleKey: "moreReasons.r4Title", descKey: "moreReasons.r4Desc" },
  { num: "05", titleKey: "moreReasons.r5Title", descKey: "moreReasons.r5Desc" },
  { num: "06", titleKey: "moreReasons.r6Title", descKey: "moreReasons.r6Desc" },
];

export default function MoreReasons() {
  const { t } = useTranslation();

  return (
    <section className="w-full max-w-[1152px] mx-auto px-4 md:px-8 lg:px-0">
      <SectionHeader
        title={t("moreReasons.title")}
        subtitle={t("moreReasons.subtitle")}
        subtitleWidth="max-w-[614px]"
      />

      <div className="mt-10 grid grid-cols-1 md:grid-cols-2 gap-x-20 gap-y-8">
        {reasonKeys.map((r) => (
          <div key={r.num} className="flex gap-3">
            <span className="text-[34px] font-semibold text-primary/40 leading-none shrink-0">
              {r.num}
            </span>
            <div>
              <h3 className="text-[16px] font-semibold text-[#2d2d2d] mb-2">
                {t(r.titleKey)}
              </h3>
              <p className="text-[16px] leading-[24px] text-[#606060] max-w-[468px]">
                {t(r.descKey)}
              </p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
