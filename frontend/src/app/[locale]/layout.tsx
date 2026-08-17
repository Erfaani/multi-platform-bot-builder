import { notFound } from "next/navigation";
import { IntlProvider } from "@/i18n/provider";
import { directionOf, isLocale, LOCALES, type Locale } from "@/i18n/config";
import { AuthProvider } from "@/lib/auth";
import { SiteHeader } from "@/components/site-header";

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
    <html lang={locale} dir={dir} suppressHydrationWarning>
      <body className={locale === "fa" ? "font-persian" : "font-sans"}>
        <IntlProvider locale={locale} messages={MESSAGES[locale]}>
          <AuthProvider>
            <div className="mx-auto flex min-h-screen max-w-5xl flex-col px-4">
              <SiteHeader />
              <main className="flex-1 py-10">{children}</main>
              <footer className="border-t border-line py-6 text-sm text-muted">
                Bot Builder Platform — Phase 1
              </footer>
            </div>
          </AuthProvider>
        </IntlProvider>
      </body>
    </html>
  );
}
