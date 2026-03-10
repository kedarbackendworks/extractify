"use client";

import SectionHeader from "./SectionHeader";
import { useTranslation } from "@/lib/i18n";

export default function PlatformOverview() {
  const { t } = useTranslation();

  const stats = [
    { value: t("platformOverview.stat1Value"), label: t("platformOverview.stat1Label") },
    { value: t("platformOverview.stat2Value"), label: t("platformOverview.stat2Label") },
    { value: t("platformOverview.stat3Value"), label: t("platformOverview.stat3Label") },
    { value: t("platformOverview.stat4Value"), label: t("platformOverview.stat4Label") },
  ];

  return (
    <section className="w-full max-w-[1152px] mx-auto px-4 md:px-8 lg:px-0">
      <SectionHeader
        title={t("platformOverview.title")}
        subtitle={t("platformOverview.subtitle")}
        subtitleWidth="max-w-[519px]"
      />

      <div className="mt-8 md:mt-10 flex flex-col lg:flex-row lg:gap-[155px] items-start justify-center">
        {/* Left: Description */}
        <div className="w-full lg:w-[612px] space-y-[15px] text-[16px] leading-[28px] text-[#404040]">
          <p>{t("platformOverview.p1")}</p>
          <p>{t("platformOverview.p2")}</p>
        </div>

        {/* Right: Stats grid */}
        <div className="grid grid-cols-2 gap-5 shrink-0 mt-4 lg:mt-0">
          {stats.map((s) => (
            <div
              key={s.label}
              className="bg-[#ece8f5] rounded-[12px] p-5 w-[176px] md:w-[184px] h-[123px] flex flex-col items-start justify-center"
            >
              <span className="text-[40px] font-bold text-[#2d2d2d] leading-tight">
                {s.value}
              </span>
              <span className="text-[16px] text-black mt-2">{s.label}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
