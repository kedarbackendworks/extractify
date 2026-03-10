"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import SectionHeader from "./SectionHeader";
import { useTranslation } from "@/lib/i18n";

const faqKeys = [
  { qKey: "faq.q1", aKey: "faq.a1" },
  { qKey: "faq.q2", aKey: "faq.a2" },
  { qKey: "faq.q3", aKey: "faq.a3" },
  { qKey: "faq.q4", aKey: "faq.a4" },
  { qKey: "faq.q5", aKey: "faq.a5" },
  { qKey: "faq.q6", aKey: "faq.a6" },
];

export default function FAQ() {
  const [openIndex, setOpenIndex] = useState<number>(0);
  const { t } = useTranslation();

  return (
    <section className="w-full max-w-[1152px] mx-auto px-4 md:px-8 lg:px-0">
      <SectionHeader
        title={t("faq.title")}
        subtitle={t("faq.subtitle")}
        subtitleWidth="max-w-[480px]"
      />

      <div className="mt-10 max-w-[372px] md:max-w-[768px] mx-auto flex flex-col divide-y divide-[#e8e8e8]">
        {faqKeys.map((faq, i) => (
          <div key={faq.qKey} className="py-5">
            <button
              onClick={() => setOpenIndex(openIndex === i ? -1 : i)}
              className="w-full flex items-center justify-between text-left gap-4"
            >
              <span
                className={`text-[16px] font-semibold transition-colors ${
                  openIndex === i ? "text-primary" : "text-[#2d2d2d]"
                }`}
              >
                {t(faq.qKey)}
              </span>
              <ChevronDown
                className={`h-5 w-5 shrink-0 text-[#606060] transition-transform ${
                  openIndex === i ? "rotate-180" : ""
                }`}
              />
            </button>
            <div
              className={`overflow-hidden transition-all duration-300 ${
                openIndex === i ? "max-h-[300px] mt-3" : "max-h-0"
              }`}
            >
              <p className="text-[14px] leading-[24px] text-[#606060]">
                {t(faq.aKey)}
              </p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
