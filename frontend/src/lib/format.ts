/**
 * The single place values become strings on the client (I18N.md §4).
 * Mirrors backend/apps/core/formatting.py — keep the two in step.
 */

import type { Locale } from "@/i18n/config";

export interface Money {
  amount_minor: number;
  currency: string;
  formatted?: string;
}

export interface CurrencyMeta {
  code: string;
  symbol: string;
  exponent: number;
  display_unit: string;
  display_divisor: number;
}

const PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹";

export function toPersianDigits(value: string): string {
  return value.replace(/\d/g, (digit) => PERSIAN_DIGITS[Number(digit)]);
}

export function formatNumber(value: number, locale: Locale, decimals = 0): string {
  return new Intl.NumberFormat(locale === "fa" ? "fa-IR" : "en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

/**
 * Prefer the server's `formatted` string when present — the backend is the
 * authority on money rendering, including the Toman rule (ADR-0004).
 */
export function formatMoney(
  money: Money,
  locale: Locale,
  meta?: CurrencyMeta,
): string {
  if (money.formatted) return money.formatted;
  if (!meta) return `${money.amount_minor} ${money.currency}`;

  const major = money.amount_minor / 10 ** meta.exponent;

  // Toman is a display unit of IRR, never a currency of its own.
  if (meta.display_divisor > 1 && meta.display_unit && locale === "fa") {
    return `${formatNumber(major / meta.display_divisor, locale)} تومان`;
  }

  const decimals = meta.exponent <= 2 ? meta.exponent : 2;
  const number = formatNumber(major, locale, decimals);
  return meta.symbol ? `${meta.symbol}${number}` : `${number} ${money.currency}`;
}

/** Dates are stored UTC; `fa` renders Jalali. Conversion is display-only. */
export function formatDate(iso: string, locale: Locale): string {
  const date = new Date(iso);
  return new Intl.DateTimeFormat(locale === "fa" ? "fa-IR-u-ca-persian" : "en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(date);
}
