"use client";

import SectionHeader from "./SectionHeader";
import { useTranslation } from "@/lib/i18n";

const rowKeys = [
  { featureKey: "comparison.r1Feature", usKey: "comparison.r1Us", themKey: "comparison.r1Them" },
  { featureKey: "comparison.r2Feature", usKey: "comparison.r2Us", themKey: "comparison.r2Them" },
  { featureKey: "comparison.r3Feature", usKey: "comparison.r3Us", themKey: "comparison.r3Them" },
  { featureKey: "comparison.r4Feature", usKey: "comparison.r4Us", themKey: "comparison.r4Them" },
  { featureKey: "comparison.r5Feature", usKey: "comparison.r5Us", themKey: "comparison.r5Them" },
];

export default function ComparisonTable() {
  const { t } = useTranslation();

  return (
    <section className="w-full max-w-[1152px] mx-auto px-4 md:px-8 lg:px-0">
      <SectionHeader
        title={t("comparison.title")}
        subtitle={t("comparison.subtitle")}
        subtitleWidth="max-w-[570px]"
      />

      <div className="mt-10 overflow-x-auto">
        <table className="w-full max-w-[372px] md:max-w-[880px] mx-auto border-collapse table-fixed md:table-auto min-w-[372px] md:min-w-[760px]">
          <thead>
            <tr className="bg-white border-b border-[#e5e0ef]">
              <th className="text-left text-[13px] md:text-[14px] font-medium text-[#2d2d2d] py-3 md:py-4 px-3 md:px-4 w-1/3">
                {t("comparison.features")}
              </th>
              <th className="text-left text-[13px] md:text-[14px] font-medium text-primary py-3 md:py-4 px-3 md:px-4 w-1/3 border-x border-[#d7c9f6] bg-[#f9f5ff]">
                {t("comparison.us")}
              </th>
              <th className="text-left text-[13px] md:text-[14px] font-medium text-[#2d2d2d] py-3 md:py-4 px-3 md:px-4 w-1/3">
                {t("comparison.others")}
              </th>
            </tr>
          </thead>
          <tbody>
            {rowKeys.map((row) => (
              <tr key={row.featureKey} className="bg-white border-b border-[#e5e0ef]">
                <td className="text-[13px] md:text-[14px] text-[#404040] py-4 md:py-5 px-3 md:px-4 align-middle">
                  {t(row.featureKey)}
                </td>
                <td className="py-4 md:py-5 px-3 md:px-4 border-x border-[#d7c9f6] bg-[#f9f5ff] align-middle">
                  <span className="text-[13px] md:text-[14px] text-[#404040] break-words">{t(row.usKey)}</span>
                </td>
                <td className="py-4 md:py-5 px-3 md:px-4 align-middle">
                  <span className="text-[13px] md:text-[14px] text-[#404040] break-words">{t(row.themKey)}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
