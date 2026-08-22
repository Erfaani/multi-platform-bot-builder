/** Telegram Mini App client — no JWT, no session cookie. Every call carries Telegram's
 * own `initData` string, verified fresh server-side each time
 * (`apps.miniapp.services.verify_init_data`). Reuses the exact same view types the
 * owner dashboard already uses, since the backend serializes with the identical
 * serializers. */

import { API_BASE } from "./api";
import type { AppointmentServiceView, BusinessProfileView, FaqEntryView, SlotView, StaffMemberView } from "./bots";
import type { CourseOfferingView, ProductView, PropertyListingView } from "./commerce";

export interface MiniAppContent {
  bot_name: string;
  business: BusinessProfileView;
  faq?: FaqEntryView[];
  products?: ProductView[];
  properties?: PropertyListingView[];
  courses?: CourseOfferingView[];
  appointment_services?: AppointmentServiceView[];
  staff?: StaffMemberView[];
}

export class MiniAppError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function post<T>(instanceId: string, path: string, body: Record<string, unknown>): Promise<T> {
  const response = await fetch(`${API_BASE}/miniapp/${instanceId}/${path}/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new MiniAppError(response.status, data?.error?.message ?? "Something went wrong.");
  }
  return response.json();
}

export const miniAppApi = {
  content: (instanceId: string, initData: string) =>
    post<MiniAppContent>(instanceId, "content", { init_data: initData }),

  appointmentSlots: (instanceId: string, initData: string, service: number, staff: number, date: string) =>
    post<SlotView[]>(instanceId, "appointment-slots", { init_data: initData, service, staff, date }),

  book: (instanceId: string, initData: string, service: number, staff: number, startsAt: string) =>
    post(instanceId, "book", { init_data: initData, service, staff, starts_at: startsAt }),
};
