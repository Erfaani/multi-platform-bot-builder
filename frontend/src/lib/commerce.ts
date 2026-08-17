/** Product catalogue, orders and table reservations (Phase 7 commerce module). */

import type { Locale } from "@/i18n/config";
import { apiFetch } from "./api";
import type { MoneyView } from "./builder";

export interface ProductCategoryView {
  id: number;
  name: string;
  sort_order: number;
  is_active: boolean;
}

export interface ProductView {
  id: number;
  category_id: number | null;
  name: string;
  description: string;
  price: MoneyView;
  stock: number | null;
  is_active: boolean;
  sort_order: number;
}

export interface BusinessOrderItemView {
  product_name: string;
  unit_price_minor: number;
  currency: string;
  quantity: number;
}

export interface BusinessOrderView {
  id: string;
  status: "PENDING" | "CONFIRMED" | "CANCELLED" | "COMPLETED";
  subtotal: MoneyView;
  contact_name: string;
  delivery_address: string;
  notes: string;
  items: BusinessOrderItemView[];
  created_at: string;
}

export interface TableReservationView {
  id: string;
  party_size: number;
  starts_at: string;
  status: "CONFIRMED" | "CANCELLED" | "COMPLETED";
  notes: string;
  contact_name: string;
  created_at: string;
}

export const commerceApi = {
  categories: (botId: string, locale: Locale) =>
    apiFetch<ProductCategoryView[]>(`/bots/${botId}/product-categories/`, { locale }),

  createCategory: (botId: string, name: string, locale: Locale) =>
    apiFetch<ProductCategoryView>(`/bots/${botId}/product-categories/`, {
      method: "POST",
      body: { name },
      locale,
    }),

  deleteCategory: (botId: string, categoryId: number, locale: Locale) =>
    apiFetch<void>(`/bots/${botId}/product-categories/${categoryId}/`, { method: "DELETE", locale }),

  products: (botId: string, locale: Locale) => apiFetch<ProductView[]>(`/bots/${botId}/products/`, { locale }),

  createProduct: (
    botId: string,
    payload: { name: string; price_minor: number; category_id?: number | null },
    locale: Locale,
  ) => apiFetch<ProductView>(`/bots/${botId}/products/`, { method: "POST", body: payload, locale }),

  deleteProduct: (botId: string, productId: number, locale: Locale) =>
    apiFetch<void>(`/bots/${botId}/products/${productId}/`, { method: "DELETE", locale }),

  orders: (botId: string, locale: Locale) =>
    apiFetch<BusinessOrderView[]>(`/bots/${botId}/business-orders/`, { locale }),

  cancelOrder: (botId: string, orderId: string, locale: Locale) =>
    apiFetch<BusinessOrderView>(`/bots/${botId}/business-orders/${orderId}/cancel/`, {
      method: "POST",
      locale,
    }),

  reservations: (botId: string, locale: Locale) =>
    apiFetch<TableReservationView[]>(`/bots/${botId}/table-reservations/`, { locale }),

  cancelReservation: (botId: string, reservationId: string, locale: Locale) =>
    apiFetch<TableReservationView>(`/bots/${botId}/table-reservations/${reservationId}/cancel/`, {
      method: "POST",
      locale,
    }),
};
