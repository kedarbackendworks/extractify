"use client";

import Image from "next/image";
import SectionHeader from "./SectionHeader";
import { useTranslation } from "@/lib/i18n";

export default function OurPurpose() {
  const { t } = useTranslation();

  return (
    <section className="w-full max-w-[1152px] mx-auto px-4 md:px-8 lg:px-0">
      <SectionHeader
        title={t("ourPurpose.title")}
        subtitle={t("ourPurpose.subtitle")}
        subtitleWidth="max-w-[372px]"
      />

      <div className="mt-10 flex flex-col lg:flex-row gap-8 lg:gap-10 items-center">
        {/* Left: Text */}
        <div className="flex-1 space-y-4 text-[16px] leading-[28px] text-[#404040]">
          <p>{t("ourPurpose.p1")}</p>
          <p>{t("ourPurpose.p2")}</p>
        </div>

        {/* Right: Image */}
        <div className="shrink-0 w-[180px] h-[197px] lg:w-[360px] lg:h-[360px] relative">
          <Image
            src="/purpose-target.svg"
            alt="Our purpose illustration"
            fill
            className="object-contain"
            unoptimized
          />
        </div>
      </div>
    </section>
  );
}
