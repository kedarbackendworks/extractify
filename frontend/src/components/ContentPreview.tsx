"use client";

import { useTranslation } from "@/lib/i18n";

interface ContentPreviewProps {
  children?: React.ReactNode;
  isEmpty?: boolean;
}

export default function ContentPreview({
  children,
  isEmpty = true,
}: ContentPreviewProps) {
  const { t } = useTranslation();

  return (
    <div className="w-full max-w-[680px] min-h-[280px] sm:min-h-[414px] rounded-[20px] border border-border bg-card overflow-hidden flex items-center justify-center">
      {isEmpty ? (
        <p className="text-muted text-base font-medium text-center px-4 max-w-[302px] leading-7">
          {t("preview.empty")}
        </p>
      ) : (
        children
      )}
    </div>
  );
}
