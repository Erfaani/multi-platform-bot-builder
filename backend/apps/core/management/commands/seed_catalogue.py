"""Seed the sellable catalogue: features, templates and price lists.

Idempotent. Prices go through `pricing.services.set_price`, so re-running never
rewrites history — an unchanged price is a no-op, a changed one closes the old version
and opens a new one (spec §12).

Amounts here are **examples**. They are configuration, not code: admins change them in
the admin without a deploy (spec §27).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.business_templates.models import BusinessTemplate, TemplateFeature
from apps.features.models import Feature, FeaturePlatformAvailability
from apps.features.registry import all_manifests
from apps.i18n_content.services import set_translations
from apps.platforms.constants import SELLABLE_PLATFORMS
from apps.pricing.models import BillingKind, PriceList
from apps.pricing.services import set_price

# --------------------------------------------------------------------------- features
# slug: (english name, english description, persian name, persian description, sort)
FEATURE_COPY: dict[str, tuple[str, str, str, str, int]] = {
    "business_profile": (
        "Business profile", "Your name, description, logo and identity.",
        "پروفایل کسب‌وکار", "نام، توضیحات، لوگو و هویت کسب‌وکار شما.", 10,
    ),
    "contact": (
        "Contact details", "Phone, email and messaging links.",
        "اطلاعات تماس", "تلفن، ایمیل و راه‌های ارتباطی.", 20,
    ),
    "location": (
        "Location & map", "Address with a tappable map link.",
        "آدرس و نقشه", "آدرس همراه با لینک نقشه.", 30,
    ),
    "working_hours": (
        "Opening hours", "Weekly schedule, holidays and split shifts.",
        "ساعات کاری", "برنامهٔ هفتگی، تعطیلات و شیفت‌های جدا.", 40,
    ),
    "faq": (
        "FAQ", "Answer common questions automatically.",
        "سوالات متداول", "پاسخ خودکار به پرسش‌های پرتکرار.", 50,
    ),
    "custom_menu": (
        "Custom menu", "Add your own buttons and pages.",
        "منوی سفارشی", "افزودن دکمه‌ها و صفحات دلخواه.", 60,
    ),
    "contact_request": (
        "Message form", "Let customers send you a message.",
        "فرم پیام", "دریافت پیام از مشتریان.", 70,
    ),
    "consultation_request": (
        "Consultation requests", "Collect call-back requests with phone numbers.",
        "درخواست مشاوره", "دریافت درخواست تماس همراه شمارهٔ تلفن.", 80,
    ),
    "feedback": (
        "Feedback & ratings", "Collect ratings and comments.",
        "نظرسنجی", "دریافت امتیاز و نظر مشتریان.", 90,
    ),
    "appointment": (
        "Appointment booking", "Services, staff, time slots and confirmations.",
        "رزرو نوبت", "خدمات، کارکنان، زمان‌بندی و تأیید نوبت.", 100,
    ),
    "appointment_reminders": (
        "Appointment reminders", "Automatic reminders before each appointment.",
        "یادآوری نوبت", "یادآوری خودکار پیش از هر نوبت.", 110,
    ),
    "product_catalog": (
        "Product catalogue", "Categories, products, photos and prices.",
        "کاتالوگ محصولات", "دسته‌بندی، محصولات، تصاویر و قیمت‌ها.", 120,
    ),
    "cart_orders": (
        "Cart & orders", "Shopping cart, checkout and order status.",
        "سبد خرید و سفارش", "سبد خرید، تسویه و پیگیری سفارش.", 130,
    ),
    "table_reservation": (
        "Table reservation", "Let guests reserve a table.",
        "رزرو میز", "امکان رزرو میز برای مهمانان.", 140,
    ),
    "food_ordering": (
        "Food ordering", "Menu-based ordering with photos.",
        "سفارش غذا", "سفارش از منو همراه با تصاویر.", 150,
    ),
    "lead_capture": (
        "Lead capture", "Save every enquiry as a lead.",
        "ثبت سرنخ", "ذخیرهٔ هر درخواست به‌عنوان سرنخ فروش.", 160,
    ),
    "crm_pipeline": (
        "CRM pipeline", "Track leads through stages with notes and tags.",
        "خط لولهٔ CRM", "پیگیری سرنخ‌ها در مراحل مختلف با یادداشت و برچسب.", 170,
    ),
    "owner_notifications": (
        "Owner alerts", "Get notified of every booking, order and lead.",
        "اعلان مدیر", "اطلاع از هر رزرو، سفارش و سرنخ.", 180,
    ),
    "customer_broadcast": (
        "Customer broadcasts", "Send announcements to your customers.",
        "اطلاع‌رسانی گروهی", "ارسال پیام و اطلاعیه به مشتریان.", 190,
    ),
    "analytics": (
        "Analytics", "Users, conversations, conversions and trends.",
        "تحلیل و آمار", "کاربران، گفتگوها، نرخ تبدیل و روندها.", 200,
    ),
    "ai_assistant": (
        "AI assistant", "Answers questions from your own business knowledge.",
        "دستیار هوش مصنوعی", "پاسخ به پرسش‌ها بر پایهٔ دانش کسب‌وکار شما.", 210,
    ),
    "ai_knowledge_base": (
        "AI knowledge base", "Upload documents the assistant can learn from.",
        "پایگاه دانش هوش مصنوعی", "بارگذاری اسنادی که دستیار از آن‌ها پاسخ می‌دهد.", 220,
    ),
    "property_listings": (
        "Property listings", "Real-estate listings with photos, price and details.",
        "آگهی‌های ملکی", "آگهی‌های املاک همراه با تصویر، قیمت و جزئیات.", 230,
    ),
    "course_catalog": (
        "Course catalogue", "Courses with schedule, instructor and enrollment.",
        "کاتالوگ دوره‌ها", "دوره‌ها همراه با زمان‌بندی، مدرس و ثبت‌نام.", 240,
    ),
}

# --------------------------------------------------------------------------- templates
# slug: (en name, en description, fa name, fa description, icon, sort,
#        required, defaults, optional extras)
TEMPLATES: dict[str, tuple] = {
    "clinic": (
        "Medical clinic", "Doctors, appointments, services and patient questions.",
        "کلینیک پزشکی", "پزشکان، نوبت‌دهی، خدمات و پرسش‌های بیماران.",
        "stethoscope", 10,
        ["business_profile"],
        ["contact", "location", "working_hours", "faq", "appointment", "appointment_reminders"],
        ["consultation_request", "owner_notifications", "analytics", "ai_assistant",
         "ai_knowledge_base", "lead_capture", "feedback", "custom_menu"],
    ),
    "beauty": (
        "Beauty salon", "Services, specialists, bookings and promotions.",
        "سالن زیبایی", "خدمات، متخصصان، رزرو و تخفیف‌ها.",
        "sparkles", 20,
        ["business_profile"],
        ["contact", "location", "working_hours", "appointment", "appointment_reminders"],
        ["faq", "feedback", "customer_broadcast", "owner_notifications", "analytics",
         "lead_capture", "ai_assistant", "custom_menu"],
    ),
    "restaurant": (
        "Restaurant", "Menu, table reservations and food ordering.",
        "رستوران", "منو، رزرو میز و سفارش غذا.",
        "utensils", 30,
        ["business_profile"],
        ["contact", "location", "working_hours", "product_catalog", "cart_orders",
         "table_reservation"],
        ["food_ordering", "faq", "feedback", "customer_broadcast", "owner_notifications",
         "analytics", "custom_menu"],
    ),
    "shop": (
        "Shop", "Product catalogue, cart and order tracking.",
        "فروشگاه", "کاتالوگ محصولات، سبد خرید و پیگیری سفارش.",
        "shopping-bag", 40,
        ["business_profile"],
        ["contact", "product_catalog", "cart_orders"],
        ["location", "working_hours", "faq", "customer_broadcast", "owner_notifications",
         "analytics", "lead_capture", "ai_assistant", "custom_menu"],
    ),
    "academy": (
        "Academy", "Courses, registration requests and consultations.",
        "آموزشگاه", "دوره‌ها، ثبت‌نام و مشاوره.",
        "graduation-cap", 50,
        ["business_profile"],
        ["contact", "faq", "course_catalog", "consultation_request"],
        ["location", "working_hours", "lead_capture", "crm_pipeline", "owner_notifications",
         "analytics", "ai_assistant", "custom_menu", "product_catalog"],
    ),
    "real_estate": (
        "Real estate", "Property listings, enquiries and agent contact.",
        "املاک", "آگهی‌ها، درخواست بازدید و ارتباط با مشاور.",
        "home", 60,
        ["business_profile"],
        ["contact", "property_listings", "consultation_request", "lead_capture"],
        ["location", "faq", "crm_pipeline", "owner_notifications", "analytics",
         "ai_assistant", "custom_menu", "product_catalog"],
    ),
    "services": (
        "Service business", "Services, pricing, bookings and enquiries.",
        "کسب‌وکار خدماتی", "خدمات، قیمت‌ها، رزرو و درخواست‌ها.",
        "wrench", 70,
        ["business_profile"],
        ["contact", "working_hours", "appointment", "contact_request"],
        ["location", "faq", "appointment_reminders", "lead_capture", "owner_notifications",
         "analytics", "ai_assistant", "feedback", "custom_menu"],
    ),
    "generic": (
        "Generic business", "Start simple and add what you need.",
        "کسب‌وکار عمومی", "ساده شروع کنید و بعداً امکانات اضافه کنید.",
        "box", 80,
        ["business_profile"],
        ["contact", "faq"],
        ["location", "working_hours", "contact_request", "consultation_request", "feedback",
         "appointment", "product_catalog", "cart_orders", "lead_capture",
         "owner_notifications", "analytics", "ai_assistant", "custom_menu"],
    ),
}

# --------------------------------------------------------------------------- prices
#: (slug, currency, country scope, is_default)
PRICE_LISTS = [
    ("usd-international", "USD", [], True),
    ("irr-iran", "IRR", ["IR"], False),
]

#: Example amounts in **minor units**: USD cents, IRR rials (exponent 0).
#: IRR figures are ~10x the Toman number a Persian customer sees.
PRICES: dict[str, dict[str, tuple[int, int]]] = {
    # key: (usd_cents, irr_rials)
    "template.clinic.base": (19900, 89_000_000),
    "template.beauty.base": (17900, 79_000_000),
    "template.restaurant.base": (19900, 89_000_000),
    "template.shop.base": (17900, 79_000_000),
    "template.academy.base": (16900, 74_000_000),
    "template.real_estate.base": (18900, 84_000_000),
    "template.services.base": (14900, 65_000_000),
    "template.generic.base": (9900, 45_000_000),
    "platform.telegram.base": (4900, 22_000_000),
    "platform.bale.base": (4900, 22_000_000),
    "platform.multi.surcharge": (2900, 13_000_000),
}

#: (setup, monthly) per feature, as (usd_cents, irr_rials) pairs.
FEATURE_PRICES: dict[str, tuple[tuple[int, int], tuple[int, int] | None]] = {
    "business_profile": ((0, 0), None),
    "contact": ((0, 0), None),
    "location": ((900, 4_000_000), None),
    "working_hours": ((900, 4_000_000), None),
    "faq": ((1900, 8_500_000), None),
    "custom_menu": ((1900, 8_500_000), None),
    "contact_request": ((1400, 6_000_000), None),
    "consultation_request": ((1900, 8_500_000), None),
    "feedback": ((1400, 6_000_000), None),
    "appointment": ((5900, 26_000_000), (900, 4_000_000)),
    "appointment_reminders": ((2900, 13_000_000), (700, 3_000_000)),
    "product_catalog": ((4900, 22_000_000), (900, 4_000_000)),
    "cart_orders": ((4900, 22_000_000), (900, 4_000_000)),
    "table_reservation": ((3900, 17_000_000), (700, 3_000_000)),
    "food_ordering": ((3900, 17_000_000), (700, 3_000_000)),
    "lead_capture": ((2400, 11_000_000), (500, 2_000_000)),
    "crm_pipeline": ((4900, 22_000_000), (1200, 5_000_000)),
    "owner_notifications": ((1900, 8_500_000), (500, 2_000_000)),
    "customer_broadcast": ((2400, 11_000_000), (900, 4_000_000)),
    "analytics": ((2900, 13_000_000), (900, 4_000_000)),
    "ai_assistant": ((7900, 35_000_000), (2900, 13_000_000)),
    "ai_knowledge_base": ((4900, 22_000_000), (1900, 8_500_000)),
    "property_listings": ((4900, 22_000_000), (900, 4_000_000)),
    "course_catalog": ((4900, 22_000_000), (900, 4_000_000)),
}

HOSTING = (1900, 8_500_000)


class Command(BaseCommand):
    help = "Seed features, templates and price lists (idempotent)."

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        features = self._seed_features()
        self._seed_availability(features)
        self._seed_templates(features)
        self._seed_prices()
        self.stdout.write(self.style.SUCCESS("Catalogue seeded."))

    # -- features ---------------------------------------------------------
    def _seed_features(self) -> dict[str, Feature]:
        manifests = all_manifests()
        created: dict[str, Feature] = {}

        for slug, manifest in manifests.items():
            copy = FEATURE_COPY.get(slug)
            if copy is None:
                self.stdout.write(
                    self.style.WARNING(f"  no catalogue copy for {slug!r}; skipping")
                )
                continue
            name_en, desc_en, name_fa, desc_fa, sort_order = copy

            feature, _ = Feature.objects.update_or_create(
                slug=slug,
                defaults={
                    "category": manifest.category,
                    "icon": manifest.icon,
                    "name": name_en,
                    "description": desc_en,
                    "sort_order": sort_order,
                    "is_active": True,
                },
            )
            set_translations(feature, "name", {"en": name_en, "fa": name_fa})
            set_translations(feature, "description", {"en": desc_en, "fa": desc_fa})
            created[slug] = feature

        self.stdout.write(f"  features: {len(created)}")
        return created

    def _seed_availability(self, features: dict[str, Feature]) -> None:
        """Record capability-driven availability as explicit rows.

        The capability gate is computed live from the adapters; these rows exist so an
        operator can *additionally* withdraw a feature from a channel without a deploy.
        """
        from apps.platforms.registry import capabilities_for

        manifests = all_manifests()
        count = 0
        for slug, feature in features.items():
            manifest = manifests[slug]
            for platform in SELLABLE_PLATFORMS:
                missing = manifest.platform_requirements.unmet_on(capabilities_for(platform))
                FeaturePlatformAvailability.objects.update_or_create(
                    feature=feature,
                    platform=platform,
                    defaults={
                        "is_available": not missing,
                        "degradation_note": (
                            f"Not supported on this platform: {', '.join(missing)}."
                            if missing
                            else ""
                        ),
                    },
                )
                count += 1
        self.stdout.write(f"  availability rows: {count}")

    # -- templates --------------------------------------------------------
    def _seed_templates(self, features: dict[str, Feature]) -> None:
        for slug, spec in TEMPLATES.items():
            (
                name_en, desc_en, name_fa, desc_fa, icon, sort_order,
                required, defaults, optional,
            ) = spec

            template, _ = BusinessTemplate.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": name_en,
                    "description": desc_en,
                    "icon": icon,
                    "sort_order": sort_order,
                    "is_active": True,
                },
            )
            set_translations(template, "name", {"en": name_en, "fa": name_fa})
            set_translations(template, "description", {"en": desc_en, "fa": desc_fa})

            order = 0
            for group, is_required, is_default in (
                (required, True, True),
                (defaults, False, True),
                (optional, False, False),
            ):
                for feature_slug in group:
                    feature = features.get(feature_slug)
                    if feature is None:
                        continue
                    order += 10
                    TemplateFeature.objects.update_or_create(
                        template=template,
                        feature=feature,
                        defaults={
                            "is_required": is_required,
                            "is_default": is_default,
                            "sort_order": order,
                        },
                    )

        self.stdout.write(f"  templates: {len(TEMPLATES)}")

    # -- prices -----------------------------------------------------------
    def _seed_prices(self) -> None:
        lists: dict[str, PriceList] = {}
        for slug, currency, scope, is_default in PRICE_LISTS:
            price_list, _ = PriceList.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": f"{currency} price list",
                    "currency": currency,
                    "country_scope": scope,
                    "is_default": is_default,
                    "is_active": True,
                },
            )
            lists[currency] = price_list

        index = {"USD": 0, "IRR": 1}
        count = 0

        for key, amounts in PRICES.items():
            for currency, price_list in lists.items():
                set_price(
                    price_list=price_list,
                    price_key=key,
                    amount_minor=amounts[index[currency]],
                    billing_kind=BillingKind.ONE_TIME,
                    note="seed",
                )
                count += 1

        for slug, (setup, monthly) in FEATURE_PRICES.items():
            for currency, price_list in lists.items():
                set_price(
                    price_list=price_list,
                    price_key=f"feature.{slug}.setup",
                    amount_minor=setup[index[currency]],
                    billing_kind=BillingKind.ONE_TIME,
                    note="seed",
                )
                count += 1
                if monthly is not None:
                    set_price(
                        price_list=price_list,
                        price_key=f"feature.{slug}.monthly",
                        amount_minor=monthly[index[currency]],
                        billing_kind=BillingKind.RECURRING_MONTHLY,
                        note="seed",
                    )
                    count += 1

        for currency, price_list in lists.items():
            set_price(
                price_list=price_list,
                price_key="hosting.standard.monthly",
                amount_minor=HOSTING[index[currency]],
                billing_kind=BillingKind.RECURRING_MONTHLY,
                note="seed",
            )
            count += 1

        self.stdout.write(f"  price lists: {len(lists)} · live prices: {count}")
