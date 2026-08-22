"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { mediaUrl } from "@/lib/api";
import type { AppointmentServiceView, SlotView, StaffMemberView } from "@/lib/bots";
import type { CourseOfferingView, ProductView, PropertyListingView } from "@/lib/commerce";
import { MiniAppError, miniAppApi, type MiniAppContent } from "@/lib/miniapp";

type Locale = "en" | "fa";

/** Deliberately not the website's full i18n system — this surface is small and lives
 * outside the `[locale]` route tree entirely (see the layout's own docstring), so a
 * light inline dictionary keeps it self-contained rather than pulling in the whole
 * `IntlProvider`/message-JSON machinery for a couple dozen strings. */
const STRINGS = {
  en: {
    openInTelegram: "Open this from your Telegram bot to continue.",
    loading: "Loading…",
    networkError: "Couldn't load this — please try again.",
    faq: "FAQ",
    products: "Products",
    properties: "Properties",
    courses: "Courses",
    bookAppointment: "Book an appointment",
    selectService: "Choose a service",
    selectStaff: "Choose who you'd like to see",
    selectDate: "Choose a date",
    noSlots: "No times available that day — try another date.",
    selectTime: "Choose a time",
    confirm: "Confirm booking",
    booking: "Booking…",
    booked: "You're booked! See you then.",
    bookAnother: "Book another",
    back: "Back",
    instructor: "Instructor",
    forSale: "For sale",
    forRent: "For rent",
  },
  fa: {
    openInTelegram: "برای ادامه، این را از داخل ربات تلگرام خود باز کنید.",
    loading: "در حال بارگذاری…",
    networkError: "بارگذاری انجام نشد — دوباره تلاش کنید.",
    faq: "سوالات متداول",
    products: "محصولات",
    properties: "املاک",
    courses: "دوره‌ها",
    bookAppointment: "رزرو نوبت",
    selectService: "خدمت را انتخاب کنید",
    selectStaff: "فرد مورد نظر را انتخاب کنید",
    selectDate: "تاریخ را انتخاب کنید",
    noSlots: "زمانی در آن روز موجود نیست — تاریخ دیگری را امتحان کنید.",
    selectTime: "زمان را انتخاب کنید",
    confirm: "تأیید نوبت",
    booking: "در حال ثبت…",
    booked: "نوبت شما ثبت شد! می‌بینمتان.",
    bookAnother: "رزرو نوبت دیگر",
    back: "بازگشت",
    instructor: "مدرس",
    forSale: "برای فروش",
    forRent: "برای اجاره",
  },
} as const;

type Strings = Record<keyof (typeof STRINGS)["en"], string>;

interface TelegramWebApp {
  ready: () => void;
  expand: () => void;
  initData: string;
  initDataUnsafe?: { user?: { language_code?: string } };
  themeParams?: Record<string, string>;
  colorScheme?: "light" | "dark";
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

export default function MiniAppPage() {
  const params = useParams<{ instanceId: string }>();
  const [tg, setTg] = useState<TelegramWebApp | null>(null);
  const [locale, setLocale] = useState<Locale>("en");
  const [content, setContent] = useState<MiniAppContent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [booking, setBooking] = useState(false);

  useEffect(() => {
    const webApp = window.Telegram?.WebApp;
    // The real telegram-web-app.js script creates this object on any site, inside
    // Telegram or not — it only leaves `initData` genuinely populated when Telegram
    // itself opened the page. An empty string is the real "not in Telegram" signal.
    if (!webApp || !webApp.initData) {
      setError("open_in_telegram");
      return;
    }
    webApp.ready();
    webApp.expand();
    setTg(webApp);
    setLocale(webApp.initDataUnsafe?.user?.language_code === "fa" ? "fa" : "en");
  }, []);

  useEffect(() => {
    if (!tg || !params?.instanceId) return;
    miniAppApi
      .content(params.instanceId, tg.initData)
      .then(setContent)
      .catch((err) => setError(err instanceof MiniAppError ? err.message : "network"));
  }, [tg, params?.instanceId]);

  const t = STRINGS[locale];
  const dir = locale === "fa" ? "rtl" : "ltr";

  if (error === "open_in_telegram") {
    return (
      <div dir={dir} className="flex min-h-screen items-center justify-center p-6 text-center text-sm text-muted">
        {t.openInTelegram}
      </div>
    );
  }
  if (error) {
    return (
      <div dir={dir} className="flex min-h-screen items-center justify-center p-6 text-center text-sm text-red-500">
        {t.networkError}
      </div>
    );
  }
  if (!content || !tg) {
    return (
      <div dir={dir} className="flex min-h-screen items-center justify-center p-6 text-sm text-muted">
        {t.loading}
      </div>
    );
  }

  return (
    <div dir={dir} className="mx-auto max-w-lg space-y-4 p-4 pb-10">
      <Header content={content} />

      {content.faq?.length ? <FaqSection items={content.faq} title={t.faq} /> : null}

      {content.products?.length ? (
        <Section title={t.products}>
          <ProductGrid items={content.products} />
        </Section>
      ) : null}

      {content.properties?.length ? (
        <Section title={t.properties}>
          <PropertyGrid items={content.properties} t={t} />
        </Section>
      ) : null}

      {content.courses?.length ? (
        <Section title={t.courses}>
          <CourseGrid items={content.courses} t={t} />
        </Section>
      ) : null}

      {content.appointment_services?.length ? (
        <Section title={t.bookAppointment}>
          <BookingFlow
            instanceId={params.instanceId}
            initData={tg.initData}
            services={content.appointment_services}
            staff={content.staff ?? []}
            t={t}
            busy={booking}
            setBusy={setBooking}
          />
        </Section>
      ) : null}
    </div>
  );
}

function Header({ content }: { content: MiniAppContent }) {
  const business = content.business;
  return (
    <header className="card space-y-1 text-center">
      <h1 className="text-xl font-semibold">{business.display_name || content.bot_name}</h1>
      {business.description ? <p className="text-sm text-muted">{business.description}</p> : null}
      <div className="flex flex-wrap justify-center gap-x-3 gap-y-1 pt-1 text-xs text-muted" dir="ltr">
        {business.phone ? <span>{business.phone}</span> : null}
        {business.email ? <span>{business.email}</span> : null}
      </div>
    </header>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="card space-y-3">
      <h2 className="font-medium">{title}</h2>
      {children}
    </section>
  );
}

function FaqSection({ items, title }: { items: MiniAppContent["faq"]; title: string }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <Section title={title}>
      <ul className="space-y-1">
        {(items ?? []).map((entry) => (
          <li key={entry.id} className="border-b border-line pb-2 last:border-0">
            <button
              type="button"
              onClick={() => setOpen(open === entry.id ? null : entry.id)}
              className="w-full text-start text-sm font-medium"
            >
              {entry.question}
            </button>
            {open === entry.id ? <p className="mt-1 text-sm text-muted">{entry.answer}</p> : null}
          </li>
        ))}
      </ul>
    </Section>
  );
}

function ProductGrid({ items }: { items: ProductView[] }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {items.map((product) => (
        <div key={product.id} className="space-y-1 rounded-lg border border-line p-2 text-sm">
          {product.images[0] ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={mediaUrl(product.images[0].url)}
              alt=""
              className="aspect-square w-full rounded-md object-cover"
            />
          ) : (
            <div className="aspect-square w-full rounded-md bg-line" />
          )}
          <p className="font-medium">{product.name}</p>
          <p className="text-muted">{product.price.formatted}</p>
        </div>
      ))}
    </div>
  );
}

function PropertyGrid({ items, t }: { items: PropertyListingView[]; t: Strings }) {
  return (
    <div className="space-y-3">
      {items.map((listing) => (
        <div key={listing.id} className="space-y-1 rounded-lg border border-line p-2 text-sm">
          {listing.images[0] ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={mediaUrl(listing.images[0].url)}
              alt=""
              className="aspect-video w-full rounded-md object-cover"
            />
          ) : null}
          <p className="font-medium">{listing.title}</p>
          <p className="text-muted">
            {listing.price.formatted} · {listing.listing_type === "SALE" ? t.forSale : t.forRent}
          </p>
          {listing.address ? <p className="text-xs text-muted">{listing.address}</p> : null}
        </div>
      ))}
    </div>
  );
}

function CourseGrid({ items, t }: { items: CourseOfferingView[]; t: Strings }) {
  return (
    <div className="space-y-3">
      {items.map((course) => (
        <div key={course.id} className="flex items-center gap-3 rounded-lg border border-line p-2 text-sm">
          {course.thumbnail_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={mediaUrl(course.thumbnail_url)}
              alt=""
              className="h-14 w-14 shrink-0 rounded-md object-cover"
            />
          ) : null}
          <div>
            <p className="font-medium">{course.title}</p>
            <p className="text-muted">
              {course.price.formatted}
              {course.instructor_name ? ` · ${t.instructor}: ${course.instructor_name}` : ""}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

type BookingStep = "service" | "staff" | "date" | "slot" | "done";

function BookingFlow({
  instanceId,
  initData,
  services,
  staff,
  t,
  busy,
  setBusy,
}: {
  instanceId: string;
  initData: string;
  services: AppointmentServiceView[];
  staff: StaffMemberView[];
  t: Strings;
  busy: boolean;
  setBusy: (v: boolean) => void;
}) {
  const [step, setStep] = useState<BookingStep>("service");
  const [service, setService] = useState<AppointmentServiceView | null>(null);
  const [pickedStaff, setPickedStaff] = useState<StaffMemberView | null>(null);
  const [date, setDate] = useState("");
  const [slots, setSlots] = useState<SlotView[]>([]);
  const [error, setError] = useState<string | null>(null);

  const eligibleStaff = service ? staff.filter((s) => s.service_ids.includes(service.id)) : staff;

  function pickService(picked: AppointmentServiceView) {
    setService(picked);
    if (eligibleStaffFor(picked).length === 1) {
      setPickedStaff(eligibleStaffFor(picked)[0]);
      setStep("date");
    } else {
      setStep("staff");
    }
  }

  function eligibleStaffFor(svc: AppointmentServiceView) {
    return staff.filter((s) => s.service_ids.includes(svc.id));
  }

  async function loadSlots(day: string) {
    if (!service || !pickedStaff) return;
    setError(null);
    try {
      const result = await miniAppApi.appointmentSlots(instanceId, initData, service.id, pickedStaff.id, day);
      setSlots(result);
      setStep("slot");
    } catch (err) {
      setError(err instanceof MiniAppError ? err.message : t.networkError);
    }
  }

  async function book(slot: SlotView) {
    if (!service || !pickedStaff) return;
    setBusy(true);
    setError(null);
    try {
      await miniAppApi.book(instanceId, initData, service.id, pickedStaff.id, slot.starts_at);
      setStep("done");
    } catch (err) {
      setError(err instanceof MiniAppError ? err.message : t.networkError);
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setService(null);
    setPickedStaff(null);
    setDate("");
    setSlots([]);
    setError(null);
    setStep("service");
  }

  return (
    <div className="space-y-3">
      {error ? <p className="text-sm text-red-500">{error}</p> : null}

      {step === "service" ? (
        <div className="space-y-2">
          <p className="text-sm text-muted">{t.selectService}</p>
          {services.map((svc) => (
            <button
              key={svc.id}
              type="button"
              onClick={() => pickService(svc)}
              className="w-full rounded-lg border border-line p-2 text-start text-sm hover:border-accent"
            >
              {svc.name} · {svc.duration_minutes}min{svc.price ? ` · ${svc.price.formatted}` : ""}
            </button>
          ))}
        </div>
      ) : null}

      {step === "staff" ? (
        <div className="space-y-2">
          <p className="text-sm text-muted">{t.selectStaff}</p>
          {eligibleStaff.map((member) => (
            <button
              key={member.id}
              type="button"
              onClick={() => {
                setPickedStaff(member);
                setStep("date");
              }}
              className="w-full rounded-lg border border-line p-2 text-start text-sm hover:border-accent"
            >
              {member.name}
            </button>
          ))}
        </div>
      ) : null}

      {step === "date" ? (
        <div className="space-y-2">
          <p className="text-sm text-muted">{t.selectDate}</p>
          <input
            type="date"
            className="field"
            value={date}
            onChange={(event) => setDate(event.target.value)}
            min={new Date().toISOString().slice(0, 10)}
          />
          <button
            type="button"
            disabled={!date}
            onClick={() => loadSlots(date)}
            className="btn-primary w-full"
          >
            {t.selectTime}
          </button>
        </div>
      ) : null}

      {step === "slot" ? (
        <div className="space-y-2">
          {slots.length === 0 ? (
            <p className="text-sm text-muted">{t.noSlots}</p>
          ) : (
            <div className="grid grid-cols-3 gap-2">
              {slots.map((slot) => (
                <button
                  key={slot.starts_at}
                  type="button"
                  disabled={busy}
                  onClick={() => book(slot)}
                  className="rounded-lg border border-line p-2 text-xs hover:border-accent"
                >
                  {new Date(slot.starts_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                </button>
              ))}
            </div>
          )}
        </div>
      ) : null}

      {step === "done" ? (
        <div className="space-y-2 text-center">
          <p className="text-sm">{t.booked}</p>
          <button type="button" onClick={reset} className="btn-ghost">
            {t.bookAnother}
          </button>
        </div>
      ) : null}

      {step !== "service" && step !== "done" ? (
        <button
          type="button"
          onClick={() => {
            if (step === "staff") setStep("service");
            else if (step === "date") setStep(eligibleStaffFor(service!).length === 1 ? "service" : "staff");
            else if (step === "slot") setStep("date");
          }}
          className="text-xs text-muted underline"
        >
          {t.back}
        </button>
      ) : null}
    </div>
  );
}
