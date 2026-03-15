"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import UrlInput from "@/components/UrlInput";
import ContentPreview from "@/components/ContentPreview";
import { detectContentTab } from "@/lib/url-tab-detect";
import { useTranslation } from "@/lib/i18n";
import HowItWorks from "@/components/sections/HowItWorks";
import PlatformOverview from "@/components/sections/PlatformOverview";
import WhyChooseUs from "@/components/sections/WhyChooseUs";
import MoreReasons from "@/components/sections/MoreReasons";
import ComparisonTable from "@/components/sections/ComparisonTable";
import PlatformGrid from "@/components/sections/PlatformGrid";
import OurPurpose from "@/components/sections/OurPurpose";
import PowerfulFeatures from "@/components/sections/PowerfulFeatures";
import TrustBanner from "@/components/sections/TrustBanner";
import Benefits from "@/components/sections/Benefits";
import WhatToExpect from "@/components/sections/WhatToExpect";
import FAQ from "@/components/sections/FAQ";
import ReviewForm from "@/components/sections/ReviewForm";

export default function Home() {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(false);
  const { t } = useTranslation();

  const handleUrlSubmit = (url: string) => {
    setIsLoading(true);
    // Detect platform from URL and redirect
    const platformMap: Record<string, string> = {
      // Social media
      "instagram.com": "instagram",
      "youtube.com": "youtube",
      "youtu.be": "youtube",
      "tiktok.com": "tiktok",
      "twitter.com": "twitter",
      "x.com": "twitter",
      "facebook.com": "facebook",
      "fb.com": "facebook",
      "snapchat.com": "snapchat",
      "linkedin.com": "linkedin",
      "pinterest.com": "pinterest",
      "pin.it": "pinterest",
      "reddit.com": "reddit",
      "tumblr.com": "tumblr",
      "twitch.tv": "twitch",
      "vimeo.com": "vimeo",
      "vk.com": "vk",
      "soundcloud.com": "soundcloud",
      "t.me": "telegram",
      "telegram.org": "telegram",
      "threads.net": "threads",
      "threads.com": "threads",
      // Document / publication platforms
      "scribd.com": "scribd",
      "slideshare.net": "slideshare",
      "issuu.com": "issuu",
      "calameo.com": "calameo",
      "yumpu.com": "yumpu",
      "slideserve.com": "slideserve",
    };

    let detectedPlatform = "";
    for (const [domain, platform] of Object.entries(platformMap)) {
      if (url.includes(domain)) {
        detectedPlatform = platform;
        break;
      }
    }

    if (detectedPlatform) {
      const detectedTab = detectContentTab(url, detectedPlatform);
      const params = new URLSearchParams({ url });
      if (detectedTab) params.set("tab", detectedTab);
      router.push(`/platform/${detectedPlatform}?${params.toString()}`);
    } else {
      // Default: stay on the page
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col items-center">
      {/* Hero section */}
      <div className="flex flex-col items-center px-4 md:px-8 pt-16 md:pt-20 pb-20 md:pb-24">
        <div className="flex flex-col items-center gap-3 max-w-[1000px] mb-10 w-full">
          <h1 className="text-[24px] sm:text-[32px] font-semibold text-[#2D2D2D] text-center leading-normal w-full">
            {t("hero.title")}
          </h1>
          <p className="text-text-secondary text-[16px] sm:text-[20px] font-medium text-center max-w-[431px] leading-[24px] sm:leading-[28px]">
            {t("hero.subtitle")}
          </p>
        </div>

        {/* URL Input */}
        <div className="w-full max-w-[696px] mb-6">
          <UrlInput onSubmit={handleUrlSubmit} isLoading={isLoading} />
        </div>

        {/* Content Preview Placeholder */}
        <ContentPreview isEmpty />
      </div>

      {/* Landing page sections */}
      <div className="flex flex-col items-center gap-16 md:gap-20 w-full pb-20 md:pb-24">
        <div id="faq">
          <FAQ />
        </div>
        <HowItWorks />
        <PlatformOverview />
        <WhyChooseUs />
        <MoreReasons />
        <ComparisonTable />
        <PlatformGrid />
        <OurPurpose />
        <PowerfulFeatures />
        <TrustBanner />
        <Benefits />
        <WhatToExpect />
        <div id="reviews">
          <ReviewForm />
        </div>
      </div>
    </div>
  );
}
