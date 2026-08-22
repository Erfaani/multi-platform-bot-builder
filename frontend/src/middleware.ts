import { NextResponse, type NextRequest } from "next/server";
import { DEFAULT_LOCALE, LOCALES, isLocale } from "@/i18n/config";

const LOCALE_COOKIE = "locale";

/**
 * Every page lives under an explicit /{locale}/ prefix. Resolution order matches
 * the backend (I18N.md §2): URL → cookie → Accept-Language → default.
 */
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const hasLocale = LOCALES.some(
    (locale) => pathname === `/${locale}` || pathname.startsWith(`/${locale}/`),
  );
  if (hasLocale) return NextResponse.next();

  const cookieLocale = request.cookies.get(LOCALE_COOKIE)?.value;
  const headerLocale = request.headers
    .get("accept-language")
    ?.split(",")[0]
    ?.split("-")[0];

  const locale =
    (cookieLocale && isLocale(cookieLocale) && cookieLocale) ||
    (headerLocale && isLocale(headerLocale) && headerLocale) ||
    DEFAULT_LOCALE;

  const url = request.nextUrl.clone();
  url.pathname = `/${locale}${pathname === "/" ? "" : pathname}`;
  return NextResponse.redirect(url);
}

export const config = {
  // `miniapp` is excluded: it's a standalone Telegram Mini App route (its own root
  // layout, no `[locale]` prefix — see `app/miniapp/[instanceId]/layout.tsx`) that
  // resolves its own language from Telegram's `initDataUnsafe.user.language_code`
  // instead of a URL segment.
  matcher: ["/((?!api|_next|favicon.ico|miniapp|.*\\..*).*)"],
};
