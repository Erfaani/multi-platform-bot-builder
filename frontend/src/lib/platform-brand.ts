/**
 * Visual identity for Telegram/Bale — frontend-only by design. `Platform` is a bare
 * enum on the backend (`apps/platforms/constants.py`) with no color/logo field, and it
 * should stay that way: brand color is presentation, not a modelling concern the API
 * needs to own.
 */

export interface PlatformBrand {
  label: string;
  /** Brand accent, `rgb()`-ready — used for borders, badges, and preview chrome. */
  color: string;
  bg: string;
  icon: string;
}

// Both verified against each platform's own asset: Telegram's brand blue from its
// official logo (simple-icons' Telegram entry), Bale's teal-green from the app-icon
// mark in the logo SVG served at bale.ai/logo/bale_logo.svg. `icon` is only the
// generic-fallback lucide name now — the real call sites render the actual brand mark
// via `PlatformIcon` (`components/platform-icon.tsx`), not this string.
export const PLATFORM_BRANDS: Record<string, PlatformBrand> = {
  telegram: {
    label: "Telegram",
    color: "#26A5E4",
    bg: "#26A5E415",
    icon: "send",
  },
  bale: {
    label: "Bale",
    color: "#00B894",
    bg: "#00B89415",
    icon: "message-circle",
  },
};

const FALLBACK_BRAND: PlatformBrand = {
  label: "Platform",
  color: "#6B7280",
  bg: "#6B728015",
  icon: "smartphone",
};

export function platformBrand(slug: string): PlatformBrand {
  return PLATFORM_BRANDS[slug] ?? FALLBACK_BRAND;
}
