import { Manrope } from "next/font/google";
import localFont from "next/font/local";

/** English/Latin brand typeface. Self-hosted via `next/font` — downloaded once at
 * build time, served from this origin, never fetched from a runtime CDN
 * (SECURITY.md, I18N.md §3). */
export const manrope = Manrope({
  subsets: ["latin"],
  variable: "--font-latin",
  display: "swap",
});

/** Persian brand typeface. Not in next/font/google's bundled snapshot, so the
 * variable font file is vendored directly (OFL-licensed, from Google's own fonts
 * repository) and loaded the same self-hosted way via next/font/local. */
export const estedad = localFont({
  src: "./fonts/Estedad-Variable.ttf",
  weight: "100 900",
  variable: "--font-persian",
  display: "swap",
});
