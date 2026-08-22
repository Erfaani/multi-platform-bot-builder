/**
 * Renders the icon keys the backend already sends on business templates and features
 * (each app's manifest.py, e.g. `icon="stethoscope"`) — lucide-icon names, unused by
 * the frontend until now.
 *
 * Statically imported (not `lucide-react/dynamic`) for every icon currently in use, so
 * the icon is present in the server-rendered HTML instead of popping in after hydration.
 * A key the static map doesn't recognise (a future manifest using a new icon before this
 * map is updated) falls back to `lucide-react/dynamic`'s runtime lookup rather than
 * breaking the page.
 */

import { forwardRef } from "react";
import { DynamicIcon } from "lucide-react/dynamic";
import {
  BarChart,
  Bell,
  BellRing,
  Book,
  BookOpen,
  Box,
  Building,
  Calendar,
  Check,
  ChefHat,
  Clock,
  GraduationCap,
  Handshake,
  HelpCircle,
  Home,
  Kanban,
  List,
  MapPin,
  Megaphone,
  MessageCircle,
  MessageSquare,
  Package,
  Phone,
  Send,
  ShoppingBag,
  ShoppingCart,
  Smartphone,
  Sparkles,
  Star,
  Stethoscope,
  TriangleAlert,
  UserPlus,
  Utensils,
  Wrench,
  X,
  type LucideProps,
} from "lucide-react";

const KNOWN_ICONS: Record<string, React.ComponentType<LucideProps>> = {
  "bar-chart": BarChart,
  bell: Bell,
  "bell-ring": BellRing,
  book: Book,
  "book-open": BookOpen,
  box: Box,
  building: Building,
  calendar: Calendar,
  check: Check,
  "chef-hat": ChefHat,
  clock: Clock,
  "graduation-cap": GraduationCap,
  handshake: Handshake,
  "help-circle": HelpCircle,
  home: Home,
  kanban: Kanban,
  list: List,
  "map-pin": MapPin,
  megaphone: Megaphone,
  "message-circle": MessageCircle,
  "message-square": MessageSquare,
  package: Package,
  phone: Phone,
  send: Send,
  "shopping-bag": ShoppingBag,
  "shopping-cart": ShoppingCart,
  smartphone: Smartphone,
  sparkles: Sparkles,
  star: Star,
  stethoscope: Stethoscope,
  "triangle-alert": TriangleAlert,
  "user-plus": UserPlus,
  utensils: Utensils,
  wrench: Wrench,
  x: X,
};

export interface DynamicIconProps extends LucideProps {
  name: string;
}

export const AppIcon = forwardRef<SVGSVGElement, DynamicIconProps>(function AppIcon(
  { name, ...props },
  ref,
) {
  const Known = KNOWN_ICONS[name];
  if (Known) return <Known ref={ref} {...props} />;

  // Unrecognised key (a manifest icon added after this static map was last updated):
  // resolved at runtime instead of breaking the page. `Box` renders immediately as a
  // placeholder while the real icon loads, then DynamicIcon swaps it in.
  // `name` is typed as a huge literal union of lucide's own icon set — that's exactly
  // what we can't verify at compile time for a string arriving from backend data, which
  // is the whole reason this fallback path exists.
  return (
    <DynamicIcon
      ref={ref}
      name={name as Parameters<typeof DynamicIcon>[0]["name"]}
      fallback={() => <Box {...props} />}
      {...props}
    />
  );
});
