import Script from "next/script";

export const metadata = {
  title: "Botiva",
};

/** Deliberately its own root — not nested under `[locale]/layout.tsx` — so a Telegram
 * Mini App gets a clean, full-screen shell instead of the website's own header, footer
 * and JWT-based `AuthProvider`. Telegram supplies its own chrome (back button, close
 * button); duplicating the website's nav on top of that would waste the little screen
 * space a Mini App has. `globals.css` is already loaded app-wide by `app/layout.tsx`
 * (a thin `return children` pass-through above this), so every shared `.card`/
 * `.btn-primary` class still works here unchanged. */
export default function MiniAppLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-surface text-ink">
        <Script src="https://telegram.org/js/telegram-web-app.js" strategy="beforeInteractive" />
        {children}
      </body>
    </html>
  );
}
