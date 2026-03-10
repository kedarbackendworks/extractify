"use client";

import { Check } from "lucide-react";
import { useTranslation } from "@/lib/i18n";

const trustPointKeys = [
  "trust.check1",
  "trust.check2",
  "trust.check3",
  "trust.check4",
  "trust.check5",
  "trust.check6",
  "trust.check7",
  "trust.check8",
];

export default function TrustBanner() {
  const { t } = useTranslation();

  return (
    <section className="w-full bg-[#f4f1f8]">
      <div className="max-w-[1152px] mx-auto px-4 md:px-8 lg:px-0 py-16">
        <div className="flex flex-col lg:flex-row gap-10 items-start">
          {/* Left: Text */}
          <div className="flex-1 space-y-4">
            <h2 className="text-[24px] font-semibold text-[#2d2d2d]">
              {t("trust.heading")}
            </h2>
            <p className="text-[16px] leading-[28px] text-[#404040] max-w-[480px]">
              {t("trust.description")}
            </p>
            <button className="mt-4 px-8 py-3 bg-primary text-white text-[14px] font-medium rounded-full hover:bg-primary/90 transition-colors">
              {t("trust.learnMore")}
            </button>
          </div>

          {/* Right: Checklist */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-4 shrink-0">
            {trustPointKeys.map((key) => (
              <div key={key} className="flex items-start gap-3">
                <span className="mt-0.5 inline-flex items-center justify-center w-5 h-5 rounded-full bg-green-100 shrink-0">
                  <Check className="h-3 w-3 text-green-600" />
                </span>
                <span className="text-[14px] leading-[22px] text-[#404040]">
                  {t(key)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
