import { notFound } from "next/navigation";
import { IntlProvider } from "@/i18n/provider";
import { directionOf, isLocale, LOCALES, type Locale } from "@/i18n/config";
import { AuthProvider } from "@/lib/auth";
import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";
import { estedad, manrope } from "@/fonts";

import en from "@/i18n/messages/en.json";
import fa from "@/i18n/messages/fa.json";

const MESSAGES: Record<Locale, Record<string, string>> = { en, fa };

export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();

  const dir = directionOf(locale);

  return (
    <html
      lang={locale}
      dir={dir}
      suppressHydrationWarning
      className={`${manrope.variable} ${estedad.variable}`}
    >
      <body className={locale === "fa" ? "font-persian" : "font-sans"}>
        <IntlProvider locale={locale} messages={MESSAGES[locale]}>
          <AuthProvider>
            <div className="flex min-h-screen flex-col">
              <SiteHeader />
              <main className="flex-1">
                <div className="mx-auto w-full max-w-6xl px-4 py-10 sm:px-6">{children}</div>
              </main>
              <SiteFooter />
            </div>
          </AuthProvider>
        </IntlProvider>
      </body>
    </html>
  );
}
