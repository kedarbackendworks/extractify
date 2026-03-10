"use client";

import {
  Instagram,
  Youtube,
  Twitter,
  Facebook,
  Linkedin,
  Music,
  Send,
  MessageCircle,
  Tv,
  Camera,
  Globe,
  FileText,
  Presentation,
  BookOpen,
} from "lucide-react";
import SectionHeader from "./SectionHeader";
import { useTranslation } from "@/lib/i18n";

const platforms = [
  { name: "Facebook", icon: <Facebook className="h-8 w-8" style={{ color: "#1877F2" }} /> },
  { name: "YouTube", icon: <Youtube className="h-8 w-8" style={{ color: "#FF0000" }} /> },
  { name: "Instagram", icon: <Instagram className="h-8 w-8" style={{ color: "#E1306C" }} /> },
  { name: "Twitter / X", icon: <Twitter className="h-8 w-8" style={{ color: "#1DA1F2" }} /> },
  { name: "TikTok", icon: <Music className="h-8 w-8" style={{ color: "#010101" }} /> },
  { name: "Snapchat", icon: <Camera className="h-8 w-8" style={{ color: "#FFFC00" }} /> },
  { name: "LinkedIn", icon: <Linkedin className="h-8 w-8" style={{ color: "#0A66C2" }} /> },
  { name: "Pinterest", icon: <Globe className="h-8 w-8" style={{ color: "#E60023" }} /> },
  { name: "Reddit", icon: <MessageCircle className="h-8 w-8" style={{ color: "#FF4500" }} /> },
  { name: "Tumblr", icon: <Globe className="h-8 w-8" style={{ color: "#35465C" }} /> },
  { name: "Twitch", icon: <Tv className="h-8 w-8" style={{ color: "#9146FF" }} /> },
  { name: "Vimeo", icon: <Tv className="h-8 w-8" style={{ color: "#1AB7EA" }} /> },
  { name: "VK", icon: <Globe className="h-8 w-8" style={{ color: "#4680C2" }} /> },
  { name: "SoundCloud", icon: <Music className="h-8 w-8" style={{ color: "#FF5500" }} /> },
  { name: "Telegram", icon: <Send className="h-8 w-8" style={{ color: "#0088CC" }} /> },
  { name: "Threads", icon: <MessageCircle className="h-8 w-8" style={{ color: "#000000" }} /> },
  { name: "Scribd", icon: <FileText className="h-8 w-8" style={{ color: "#1A7BBA" }} /> },
  { name: "SlideShare", icon: <Presentation className="h-8 w-8" style={{ color: "#0077B5" }} /> },
  { name: "Issuu", icon: <BookOpen className="h-8 w-8" style={{ color: "#F36D5D" }} /> },
  { name: "Calameo", icon: <BookOpen className="h-8 w-8" style={{ color: "#3D6DAA" }} /> },
  { name: "Yumpu", icon: <FileText className="h-8 w-8" style={{ color: "#D6113F" }} /> },
  { name: "SlideServe", icon: <Presentation className="h-8 w-8" style={{ color: "#4A90D9" }} /> },
];

export default function PlatformGrid() {
  const { t } = useTranslation();

  return (
    <section className="w-full max-w-[1152px] mx-auto px-4 md:px-8 lg:px-0">
      <SectionHeader
        title={t("platformGrid.title")}
        subtitle={t("platformGrid.subtitle")}
        subtitleWidth="max-w-[381px]"
      />

      <div className="mt-10 grid grid-cols-3 md:grid-cols-8 lg:grid-cols-11 gap-y-5 md:gap-y-8 gap-x-0 md:gap-x-4 justify-items-center">
        {platforms.map((p) => (
          <div key={p.name} className="flex flex-col items-center gap-2 w-[80px]">
            <div className="w-6 h-6 md:w-14 md:h-14 md:rounded-xl md:bg-white md:shadow-[2px_2px_6px_0px_rgba(211,211,211,0.25)] flex items-center justify-center">
              {p.icon}
            </div>
            <span className="text-[14px] md:text-[11px] text-[#404040] text-center leading-tight">
              {p.name}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
