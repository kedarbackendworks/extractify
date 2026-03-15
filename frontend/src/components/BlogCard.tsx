"use client";

import Image from "next/image";
import Link from "next/link";
import { useTranslation } from "@/lib/i18n";

export interface BlogCardProps {
  slug: string;
  title: string;
  description: string;
  date: string;
  image: string;
}

export default function BlogCard({
  slug,
  title,
  description,
  date,
  image,
}: BlogCardProps) {
  const { t } = useTranslation();
  return (
    <div className="flex w-full flex-col gap-3 overflow-hidden rounded-2xl bg-white p-3">
      {/* Thumbnail */}
      <div className="relative h-[200px] w-full overflow-hidden rounded-xl bg-[#c8c8c8]">
        <Image
          src={image}
          alt={title}
          fill
          className="object-cover"
          sizes="(max-width: 768px) 100vw, 316px"
          unoptimized
        />
      </div>

      {/* Text content */}
      <div className="flex flex-col gap-2">
        <h3 className="text-base font-semibold text-foreground">{title}</h3>
        <p className="text-sm font-medium leading-5 text-[#606060]">
          {description}
        </p>
      </div>

      {/* Date */}
      <p className="text-sm font-medium text-[#808080]">{date}</p>

      {/* Read More button */}
      <Link
        href={`/blogs/${slug}`}
        className="flex h-10 w-full items-center justify-center rounded-full border border-primary text-sm font-medium text-primary transition-colors hover:bg-primary hover:text-white"
      >
        {t("blog.readMore")}
      </Link>
    </div>
  );
}
