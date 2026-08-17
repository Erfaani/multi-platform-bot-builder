/** Orders, payments and notifications. */

import type { Locale } from "@/i18n/config";
import { API_BASE, apiFetch, tokenStore } from "./api";
import type { MoneyView } from "./builder";

export interface OrderItemView {
  price_key: string;
  label: string;
  feature_slug: string;
  quantity: number;
  billing_kind: "ONE_TIME" | "RECURRING_MONTHLY";
  unit_amount: MoneyView;
  amount: MoneyView;
}

export interface OrderEventView {
  from_status: string;
  to_status: string;
  actor_type: string;
  reason: string;
  created_at: string;
}

export interface OrderPaymentSummary {
  id: string;
  status: string;
  method: string;
  rejection_reason: string;
  submitted_at: string | null;
}

export interface OrderView {
  id: string;
  number: number;
  status: string;
  kind: "NEW" | "ADDON";
  target_bot: string | null;
  template: string;
  platforms: string[];
  features: string[];
  business_snapshot: Record<string, unknown>;
  currency: string;
  items: OrderItemView[];
  events: OrderEventView[];
  subtotal_once: MoneyView;
  subtotal_recurring: MoneyView;
  discount: MoneyView;
  discount_reason: string;
  total: MoneyView;
  available_actions: string[];
  payment: OrderPaymentSummary | null;
  placed_at: string | null;
  paid_at: string | null;
  created_at: string;
}

export interface OrderSummary {
  id: string;
  number: number;
  status: string;
  currency: string;
  total: MoneyView;
  created_at: string;
}

export interface PaymentMethodView {
  id: string;
  kind: "MANUAL_CARD" | "MANUAL_CRYPTO" | "GATEWAY";
  name: string;
  currency: string;
  network: string;
  minimum_amount: MoneyView;
  requires_transaction_hash: boolean;
}

export interface InstructionField {
  label: string;
  value: string;
  copyable?: boolean;
}

export interface PaymentView {
  id: string;
  order: string;
  order_number: number;
  status: string;
  method: PaymentMethodView;
  amount: MoneyView;
  tx_hash: string;
  instructions: {
    headline: string;
    fields: InstructionField[];
    notes: string[];
    copyable: string;
  };
  proof: {
    requires_file: boolean;
    requires_tx_hash: boolean;
    optional_fields: string[];
    receipts: number;
  };
  rejection_reason: string;
  submitted_at: string | null;
}

export interface NotificationView {
  id: string;
  event_type: string;
  title: string;
  body: string;
  link: string;
  is_read: boolean;
  created_at: string;
}

interface Paginated<T> {
  count: number;
  results: T[];
}

export const checkoutApi = {
  placeOrder: (quoteId: string, locale: Locale) =>
    apiFetch<OrderView>("/orders/", {
      method: "POST",
      body: { quote: quoteId },
      locale,
    }),

  orders: (locale: Locale) => apiFetch<Paginated<OrderSummary>>("/orders/", { locale }),

  order: (id: string, locale: Locale) => apiFetch<OrderView>(`/orders/${id}/`, { locale }),

  cancelOrder: (id: string, reason: string, locale: Locale) =>
    apiFetch<OrderView>(`/orders/${id}/cancel/`, {
      method: "POST",
      body: { reason },
      locale,
    }),

  paymentMethods: (orderId: string, locale: Locale) =>
    apiFetch<PaymentMethodView[]>(`/orders/${orderId}/payment-methods/`, { locale }),

  startPayment: (orderId: string, methodId: string, locale: Locale) =>
    apiFetch<PaymentView>("/payments/", {
      method: "POST",
      body: { order: orderId, payment_method: methodId },
      locale,
    }),

  payment: (id: string, locale: Locale) => apiFetch<PaymentView>(`/payments/${id}/`, { locale }),

  notifications: (locale: Locale) =>
    apiFetch<Paginated<NotificationView>>("/notifications/", { locale }),

  unreadCount: () => apiFetch<{ unread: number }>("/notifications/unread-count/"),

  markRead: (id: string) =>
    apiFetch<NotificationView>(`/notifications/${id}/read/`, { method: "POST" }),

  markAllRead: () => apiFetch<{ marked: number }>("/notifications/read-all/", { method: "POST" }),
};

/**
 * Proof upload is multipart, so it bypasses `apiFetch` (which sets a JSON
 * content-type). The browser must set its own multipart boundary.
 */
export async function submitProof(
  paymentId: string,
  payload: { file?: File | null; tx_hash?: string; sender_wallet?: string; payer_note?: string },
  locale: Locale,
): Promise<PaymentView> {
  const form = new FormData();
  if (payload.file) form.append("file", payload.file);
  if (payload.tx_hash) form.append("tx_hash", payload.tx_hash);
  if (payload.sender_wallet) form.append("sender_wallet", payload.sender_wallet);
  if (payload.payer_note) form.append("payer_note", payload.payer_note);

  const headers: Record<string, string> = { "Accept-Language": locale };
  if (tokenStore.access) headers["Authorization"] = `Bearer ${tokenStore.access}`;
  if (tokenStore.tenant) headers["X-Tenant"] = tokenStore.tenant;

  const response = await fetch(`${API_BASE}/payments/${paymentId}/proof/`, {
    method: "POST",
    headers,
    body: form,
  });

  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const { ApiError } = await import("./api");
    throw new ApiError(
      response.status,
      body?.error ?? { code: "error.unexpected", message: "Upload failed." },
    );
  }
  return body as PaymentView;
}
