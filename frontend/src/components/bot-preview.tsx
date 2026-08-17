"use client";

import type { PlatformPreview, PreviewScreen } from "@/lib/builder";
import { useTranslations } from "@/i18n/provider";

function ScreenBubble({ screen }: { screen: PreviewScreen }) {
  const { message } = screen;

  return (
    <div className="space-y-2">
      <p className="text-xs uppercase tracking-wide text-muted">{screen.title}</p>

      {screen.user_says ? (
        <div className="flex justify-end">
          <span className="max-w-[80%] rounded-2xl bg-accent px-3 py-2 text-sm text-white">
            {screen.user_says}
          </span>
        </div>
      ) : null}

      <div className="flex justify-start">
        <div className="max-w-[85%] space-y-2 rounded-2xl border border-line px-3 py-2">
          <p className="whitespace-pre-line text-sm">{message.text}</p>

          {message.buttons.length > 0 ? (
            <div className="space-y-1">
              {message.buttons.map((row, rowIndex) => (
                <div key={rowIndex} className="flex flex-wrap gap-1">
                  {row.map((label) => (
                    <span
                      key={label}
                      className={`rounded-md px-2 py-1 text-xs ${
                        message.layout === "inline"
                          ? "border border-accent text-accent"
                          : "border border-line text-muted"
                      }`}
                    >
                      {label}
                    </span>
                  ))}
                </div>
              ))}
            </div>
          ) : null}

          {message.expects ? (
            <p className="text-xs italic text-muted">…awaiting {message.expects}</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function BotPreview({ previews }: { previews: PlatformPreview[] }) {
  const t = useTranslations();

  if (previews.length === 0) {
    return <p className="text-sm text-muted">{t("common.loading")}</p>;
  }

  return (
    <div className="grid gap-6 md:grid-cols-2">
      {previews.map((preview) => (
        <section key={preview.platform} className="card space-y-4">
          <header className="flex items-center justify-between gap-2">
            <h3 className="font-medium">{preview.display_name}</h3>
            {!preview.capabilities_verified ? (
              <span className="rounded-md border border-line px-2 py-0.5 text-xs text-muted">
                {t("builder.preview.provisional")}
              </span>
            ) : null}
          </header>

          {preview.warnings.length > 0 ? (
            <ul className="space-y-1 rounded-lg border border-line p-3 text-xs text-muted">
              {preview.warnings.map((warning) => (
                <li key={warning}>• {warning}</li>
              ))}
            </ul>
          ) : null}

          <div className="space-y-4">
            {preview.screens.map((screen) => (
              <ScreenBubble key={screen.key} screen={screen} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
