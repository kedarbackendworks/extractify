"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "@/lib/i18n";

interface TableOfContentsProps {
  sections: { heading: string }[];
}

export default function TableOfContents({ sections }: TableOfContentsProps) {
  const [activeId, setActiveId] = useState("");
  const { t } = useTranslation();

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveId(entry.target.id);
          }
        }
      },
      { rootMargin: "-80px 0px -60% 0px", threshold: 0.1 }
    );

    sections.forEach((_, i) => {
      const el = document.getElementById(`section-${i}`);
      if (el) observer.observe(el);
    });

    return () => observer.disconnect();
  }, [sections]);

  const handleClick = (index: number) => {
    const el = document.getElementById(`section-${index}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  return (
    <div className="flex flex-col gap-[19px]">
      <h3 className="text-xl font-semibold text-foreground">{t("toc.heading")}</h3>
      <nav className="flex flex-col">
        {sections.map((section, i) => {
          const isActive = activeId === `section-${i}`;
          return (
            <button
              key={i}
              onClick={() => handleClick(i)}
              className={`border-l-[3px] py-2.5 pl-5 text-left text-sm leading-[22px] transition-colors ${
                isActive
                  ? "border-primary text-primary"
                  : "border-transparent text-[#1b1b1f] hover:text-primary hover:border-primary/40"
              }`}
            >
              {section.heading}
            </button>
          );
        })}
      </nav>
    </div>
  );
}
