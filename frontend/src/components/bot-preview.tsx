"use client";

import type { PlatformPreview, PreviewScreen } from "@/lib/builder";
import { useTranslations } from "@/i18n/provider";
import { AppIcon } from "@/lib/icons";
import { platformBrand } from "@/lib/platform-brand";
import { PlatformIcon } from "@/components/platform-icon";

function ScreenBubble({ screen, accent }: { screen: PreviewScreen; accent: string }) {
  const { message } = screen;

  return (
    <div className="space-y-2">
      <p className="text-xs uppercase tracking-wide text-muted">{screen.title}</p>

      {screen.user_says ? (
        <div className="flex justify-end">
          <span
            className="max-w-[80%] rounded-2xl px-3 py-2 text-sm text-white"
            style={{ background: accent }}
          >
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
                      className="rounded-md border px-2 py-1 text-xs"
                      style={
                        message.layout === "inline"
                          ? { borderColor: accent, color: accent }
                          : undefined
                      }
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
      {previews.map((preview) => {
        const brand = platformBrand(preview.platform);
        return (
          <section
            key={preview.platform}
            className="card space-y-4"
            style={{ borderTopColor: brand.color, borderTopWidth: 3 }}
          >
            <header className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="icon-badge h-8 w-8" style={{ background: brand.bg }}>
                  <PlatformIcon slug={preview.platform} size={16} />
                </span>
                <h3 className="font-medium">{preview.display_name}</h3>
              </div>
              {!preview.capabilities_verified ? (
                <span className="rounded-md border border-line px-2 py-0.5 text-xs text-muted">
                  {t("builder.preview.provisional")}
                </span>
              ) : null}
            </header>

            {preview.warnings.length > 0 ? (
              <ul className="space-y-1 rounded-lg border border-line p-3 text-xs text-muted">
                {preview.warnings.map((warning) => (
                  <li key={warning} className="flex items-start gap-1.5">
                    <AppIcon name="triangle-alert" size={12} className="mt-0.5 shrink-0" />
                    {warning}
                  </li>
                ))}
              </ul>
            ) : null}

            <div className="space-y-4">
              {preview.screens.map((screen) => (
                <ScreenBubble key={screen.key} screen={screen} accent={brand.color} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
