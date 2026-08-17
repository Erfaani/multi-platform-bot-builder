"use client";

import { useTranslations } from "@/i18n/provider";

export function SupportStatusBadge({ status }: { status: string }) {
  const t = useTranslations();
  const tone =
    status === "CLOSED" || status === "RESOLVED"
      ? "text-muted border-line"
      : status === "WAITING_FOR_CUSTOMER"
        ? "text-amber-600 border-amber-600/40"
        : "text-accent border-accent/40";
  return (
    <span className={`rounded-md border px-2 py-0.5 text-xs ${tone}`}>
      {t(`support.status.${status}`)}
    </span>
  );
}
