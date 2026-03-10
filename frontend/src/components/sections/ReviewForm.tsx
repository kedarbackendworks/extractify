"use client";

import { useState } from "react";
import { Star } from "lucide-react";
import SectionHeader from "./SectionHeader";
import { useTranslation } from "@/lib/i18n";

export default function ReviewForm() {
  const [rating, setRating] = useState(0);
  const [hoveredRating, setHoveredRating] = useState(0);
  const { t } = useTranslation();

  return (
    <section className="w-full max-w-[1152px] mx-auto px-4 md:px-8 lg:px-0">
      <SectionHeader
        title={t("reviewForm.title")}
        subtitle={t("reviewForm.subtitle")}
        subtitleWidth="max-w-[372px]"
      />

      <div className="mt-10 max-w-[372px] md:max-w-[620px] mx-auto bg-[#ece8f5] rounded-[20px] p-6 md:p-10">
        <h3 className="text-[20px] font-semibold text-[#2d2d2d] mb-6">
          {t("reviewForm.heading")}
        </h3>

        <form className="flex flex-col gap-5" onSubmit={(e) => e.preventDefault()}>
          <div className="grid grid-cols-2 gap-4">
            <input
              type="text"
              placeholder={t("reviewForm.name")}
              className="w-full px-4 py-3 rounded-xl bg-white text-[14px] text-[#2d2d2d] placeholder:text-[#aaaaaa] outline-none focus:ring-2 focus:ring-primary/30"
            />
            <input
              type="email"
              placeholder={t("reviewForm.email")}
              className="w-full px-4 py-3 rounded-xl bg-white text-[14px] text-[#2d2d2d] placeholder:text-[#aaaaaa] outline-none focus:ring-2 focus:ring-primary/30"
            />
          </div>

          <textarea
            placeholder={t("reviewForm.placeholder")}
            rows={4}
            className="w-full px-4 py-3 rounded-xl bg-white text-[14px] text-[#2d2d2d] placeholder:text-[#aaaaaa] outline-none focus:ring-2 focus:ring-primary/30 resize-none"
          />

          {/* Star Rating */}
          <div className="flex items-center gap-2">
            <span className="text-[14px] text-[#404040] mr-2">{t("reviewForm.rating")}</span>
            {[1, 2, 3, 4, 5].map((star) => (
              <button
                key={star}
                type="button"
                onClick={() => setRating(star)}
                onMouseEnter={() => setHoveredRating(star)}
                onMouseLeave={() => setHoveredRating(0)}
              >
                <Star
                  className={`h-6 w-6 transition-colors ${
                    star <= (hoveredRating || rating)
                      ? "fill-yellow-400 text-yellow-400"
                      : "text-[#ccc]"
                  }`}
                />
              </button>
            ))}
          </div>

          <button
            type="submit"
            className="self-start px-10 py-3 bg-primary text-white text-[14px] font-medium rounded-[33px] hover:bg-primary/90 transition-colors"
          >
            {t("reviewForm.submit")}
          </button>
        </form>
      </div>
    </section>
  );
}
