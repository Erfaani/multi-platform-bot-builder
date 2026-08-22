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

export interface ImageView {
  id: number;
  url: string;
  sort_order: number;
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
  images: ImageView[];
}

export type PropertyListingType = "SALE" | "RENT";
export type PropertyType = "APARTMENT" | "HOUSE" | "LAND" | "COMMERCIAL" | "OTHER";

export interface PropertyListingView {
  id: number;
  title: string;
  description: string;
  listing_type: PropertyListingType;
  property_type: PropertyType;
  bedrooms: number | null;
  bathrooms: number | null;
  area_sqm: number | null;
  address: string;
  price: MoneyView;
  is_active: boolean;
  sort_order: number;
  images: ImageView[];
}

export interface CourseOfferingView {
  id: number;
  title: string;
  description: string;
  instructor_name: string;
  price: MoneyView;
  starts_at: string | null;
  duration_label: string;
  capacity: number | null;
  enrolled_count: number;
  is_active: boolean;
  sort_order: number;
  thumbnail_url: string;
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

  updateCategory: (
    botId: string,
    categoryId: number,
    payload: Partial<{ name: string; sort_order: number; is_active: boolean }>,
    locale: Locale,
  ) =>
    apiFetch<ProductCategoryView>(`/bots/${botId}/product-categories/${categoryId}/`, {
      method: "PATCH",
      body: payload,
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

  updateProduct: (
    botId: string,
    productId: number,
    payload: Partial<{
      name: string;
      description: string;
      price_minor: number;
      category_id: number | null;
      stock: number | null;
      is_active: boolean;
    }>,
    locale: Locale,
  ) =>
    apiFetch<ProductView>(`/bots/${botId}/products/${productId}/`, {
      method: "PATCH",
      body: payload,
      locale,
    }),

  deleteProduct: (botId: string, productId: number, locale: Locale) =>
    apiFetch<void>(`/bots/${botId}/products/${productId}/`, { method: "DELETE", locale }),

  addProductImage: (botId: string, productId: number, file: File, locale: Locale) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch<ImageView>(`/bots/${botId}/products/${productId}/images/`, {
      method: "POST",
      body: form,
      locale,
    });
  },

  deleteProductImage: (botId: string, imageId: number, locale: Locale) =>
    apiFetch<void>(`/bots/${botId}/product-images/${imageId}/`, { method: "DELETE", locale }),

  // -- property listings ------------------------------------------------------

  properties: (botId: string, locale: Locale) =>
    apiFetch<PropertyListingView[]>(`/bots/${botId}/properties/`, { locale }),

  createProperty: (
    botId: string,
    payload: {
      title: string;
      listing_type: PropertyListingType;
      property_type: PropertyType;
      price_minor: number;
      bedrooms?: number | null;
      bathrooms?: number | null;
      area_sqm?: number | null;
      address?: string;
      description?: string;
    },
    locale: Locale,
  ) => apiFetch<PropertyListingView>(`/bots/${botId}/properties/`, { method: "POST", body: payload, locale }),

  updateProperty: (
    botId: string,
    propertyId: number,
    payload: Partial<{
      title: string;
      listing_type: PropertyListingType;
      property_type: PropertyType;
      price_minor: number;
      bedrooms: number | null;
      bathrooms: number | null;
      area_sqm: number | null;
      address: string;
      description: string;
      is_active: boolean;
    }>,
    locale: Locale,
  ) =>
    apiFetch<PropertyListingView>(`/bots/${botId}/properties/${propertyId}/`, {
      method: "PATCH",
      body: payload,
      locale,
    }),

  deleteProperty: (botId: string, propertyId: number, locale: Locale) =>
    apiFetch<void>(`/bots/${botId}/properties/${propertyId}/`, { method: "DELETE", locale }),

  addPropertyImage: (botId: string, propertyId: number, file: File, locale: Locale) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch<ImageView>(`/bots/${botId}/properties/${propertyId}/images/`, {
      method: "POST",
      body: form,
      locale,
    });
  },

  deletePropertyImage: (botId: string, imageId: number, locale: Locale) =>
    apiFetch<void>(`/bots/${botId}/property-images/${imageId}/`, { method: "DELETE", locale }),

  // -- courses ------------------------------------------------------------------

  courses: (botId: string, locale: Locale) =>
    apiFetch<CourseOfferingView[]>(`/bots/${botId}/courses/`, { locale }),

  createCourse: (
    botId: string,
    payload: {
      title: string;
      price_minor: number;
      instructor_name?: string;
      duration_label?: string;
      capacity?: number | null;
      description?: string;
    },
    locale: Locale,
  ) => apiFetch<CourseOfferingView>(`/bots/${botId}/courses/`, { method: "POST", body: payload, locale }),

  updateCourse: (
    botId: string,
    courseId: number,
    payload: Partial<{
      title: string;
      price_minor: number;
      instructor_name: string;
      duration_label: string;
      capacity: number | null;
      description: string;
      is_active: boolean;
    }>,
    locale: Locale,
  ) =>
    apiFetch<CourseOfferingView>(`/bots/${botId}/courses/${courseId}/`, {
      method: "PATCH",
      body: payload,
      locale,
    }),

  deleteCourse: (botId: string, courseId: number, locale: Locale) =>
    apiFetch<void>(`/bots/${botId}/courses/${courseId}/`, { method: "DELETE", locale }),

  setCourseThumbnail: (botId: string, courseId: number, file: File, locale: Locale) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch<CourseOfferingView>(`/bots/${botId}/courses/${courseId}/thumbnail/`, {
      method: "POST",
      body: form,
      locale,
    });
  },

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
