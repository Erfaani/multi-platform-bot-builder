"use client";

import { useTranslations } from "@/i18n/provider";

/** The customer-visible journey. Internal states collapse into these steps. */
const JOURNEY = ["PENDING_PAYMENT", "PAYMENT_REVIEW", "PAID", "PROVISIONING", "ACTIVE"] as const;

const COLLAPSE: Record<string, (typeof JOURNEY)[number]> = {
  PENDING_PAYMENT: "PENDING_PAYMENT",
  PAYMENT_REJECTED: "PENDING_PAYMENT",
  RECEIPT_SUBMITTED: "PAYMENT_REVIEW",
  PAYMENT_REVIEW: "PAYMENT_REVIEW",
  PAID: "PAID",
  PROVISIONING: "PROVISIONING",
  CONFIGURING: "PROVISIONING",
  DEPLOYING: "PROVISIONING",
  ACTIVE: "ACTIVE",
};

export function OrderStatusBadge({ status }: { status: string }) {
  const t = useTranslations();
  const tone =
    status === "ACTIVE" || status === "PAID"
      ? "text-green-600 border-green-600/40"
      : status === "PAYMENT_REJECTED" || status === "FAILED"
        ? "text-red-500 border-red-500/40"
        : status === "CANCELLED"
          ? "text-muted border-line"
          : "text-accent border-accent/40";

  return (
    <span className={`rounded-md border px-2 py-0.5 text-xs ${tone}`}>
      {t(`order.status.${status}`)}
    </span>
  );
}

export function OrderProgress({ status }: { status: string }) {
  const t = useTranslations();

  if (status === "CANCELLED" || status === "FAILED") {
    return (
      <p className="text-sm text-muted">{t(`order.status.${status}`)}</p>
    );
  }

  const current = COLLAPSE[status] ?? "PENDING_PAYMENT";
  const currentIndex = JOURNEY.indexOf(current);
  const rejected = status === "PAYMENT_REJECTED";

  return (
    <ol className="flex flex-wrap gap-2 text-xs">
      {JOURNEY.map((step, index) => {
        const done = index < currentIndex;
        const active = index === currentIndex;
        return (
          <li
            key={step}
            className={`rounded-md px-2 py-1 ${
              active
                ? rejected
                  ? "bg-red-500 text-white"
                  : "bg-accent text-white"
                : done
                  ? "border border-accent text-accent"
                  : "border border-line text-muted"
            }`}
          >
            {t(`order.step.${step}`)}
          </li>
        );
      })}
    </ol>
  );
}
