import { AppIcon } from "@/lib/icons";
import { BaleIcon } from "./icons/bale-icon";
import { TelegramIcon } from "./icons/telegram-icon";

/** Real brand marks for the two platforms a customer actually chooses between —
 * anything else falls back to the generic lucide icon lookup. */
export function PlatformIcon({
  slug,
  size = 20,
  className,
}: {
  slug: string;
  size?: number;
  className?: string;
}) {
  if (slug === "telegram") return <TelegramIcon size={size} className={className} />;
  if (slug === "bale") return <BaleIcon size={size} className={className} />;
  return <AppIcon name={slug} size={size} className={className} />;
}
