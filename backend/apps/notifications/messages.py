"""Notification copy.

Stored as keys and rendered at read time, so a notification written while the user's
locale was English still reads correctly after they switch to Persian.
"""

from __future__ import annotations

DEFAULT_LOCALE = "en"

MESSAGES: dict[str, dict[str, str]] = {
    "notify.order.placed.title": {
        "en": "Order #{order_number} placed",
        "fa": "سفارش #{order_number} ثبت شد",
    },
    "notify.order.placed.body": {
        "en": "Your order is awaiting payment. Choose a payment method to continue.",
        "fa": "سفارش شما در انتظار پرداخت است. برای ادامه، روش پرداخت را انتخاب کنید.",
    },
    "notify.payment.submitted.title": {
        "en": "Payment proof received",
        "fa": "رسید پرداخت دریافت شد",
    },
    "notify.payment.submitted.body": {
        "en": "We received your proof of payment for order #{order_number} and will review it shortly.",
        "fa": "رسید پرداخت سفارش #{order_number} دریافت شد و به‌زودی بررسی می‌شود.",
    },
    "notify.payment.review.title": {
        "en": "Payment under review",
        "fa": "پرداخت در حال بررسی",
    },
    "notify.payment.review.body": {
        "en": "A member of our finance team is reviewing your payment for order #{order_number}.",
        "fa": "همکاران مالی ما در حال بررسی پرداخت سفارش #{order_number} هستند.",
    },
    "notify.payment.approved.title": {
        "en": "Payment approved",
        "fa": "پرداخت تأیید شد",
    },
    "notify.payment.approved.body": {
        "en": "Your payment for order #{order_number} was approved. We're building your bot now.",
        "fa": "پرداخت سفارش #{order_number} تأیید شد. ساخت ربات شما آغاز شده است.",
    },
    "notify.payment.rejected.title": {
        "en": "Payment could not be verified",
        "fa": "پرداخت تأیید نشد",
    },
    "notify.payment.rejected.body": {
        "en": "We could not verify your payment for order #{order_number}. {reason}",
        "fa": "پرداخت سفارش #{order_number} تأیید نشد. {reason}",
    },
    "notify.provisioning.started.title": {
        "en": "Building your bot",
        "fa": "در حال ساخت ربات شما",
    },
    "notify.provisioning.started.body": {
        "en": "We've started creating and configuring your bot. This usually takes a few minutes.",
        "fa": "ساخت و پیکربندی ربات شما آغاز شد. معمولاً چند دقیقه طول می‌کشد.",
    },
    "notify.bot.ready.title": {"en": "Your bot is ready", "fa": "ربات شما آماده است"},
    "notify.bot.ready.body": {
        "en": "Order #{order_number} is complete and your bot is live.",
        "fa": "سفارش #{order_number} تکمیل شد و ربات شما فعال است.",
    },
    "notify.provisioning.failed.title": {
        "en": "We hit a problem building your bot",
        "fa": "در ساخت ربات مشکلی پیش آمد",
    },
    "notify.provisioning.failed.body": {
        "en": "Order #{order_number} could not be completed. Our team has been alerted.",
        "fa": "سفارش #{order_number} تکمیل نشد. تیم ما در جریان قرار گرفت.",
    },
    "notify.order.cancelled.title": {"en": "Order cancelled", "fa": "سفارش لغو شد"},
    "notify.order.cancelled.body": {
        "en": "Order #{order_number} has been cancelled.",
        "fa": "سفارش #{order_number} لغو شد.",
    },
    "notify.subscription.suspended.title": {
        "en": "Your bot has been suspended",
        "fa": "ربات شما معلق شد",
    },
    "notify.subscription.suspended.body": {
        "en": "Order #{order_number} is suspended. Renew your subscription to reactivate it.",
        "fa": "سفارش #{order_number} معلق است. برای فعال‌سازی مجدد اشتراک را تمدید کنید.",
    },
    "notify.appointment.booked.title": {"en": "New appointment booked", "fa": "نوبت جدید ثبت شد"},
    "notify.appointment.booked.body": {
        "en": "{service} with {staff} on {starts_at}.",
        "fa": "{service} با {staff} در {starts_at}.",
    },
    "notify.lead.captured.title": {"en": "New lead", "fa": "سرنخ جدید"},
    "notify.lead.captured.body": {
        "en": "A new lead came in from {source}.",
        "fa": "یک سرنخ جدید از {source} دریافت شد.",
    },
    "notify.commerce_order.placed.title": {"en": "New order", "fa": "سفارش جدید"},
    "notify.commerce_order.placed.body": {
        "en": "A customer placed an order for {total}.",
        "fa": "یک مشتری سفارشی به مبلغ {total} ثبت کرد.",
    },
    "notify.ai_budget.exceeded.title": {
        "en": "AI assistant budget reached",
        "fa": "سقف بودجهٔ دستیار هوش مصنوعی پر شد",
    },
    "notify.ai_budget.exceeded.body": {
        "en": "Your AI assistant's monthly token budget is used up, so it has stopped "
        "answering customers until next month. Raise the budget in AI settings to "
        "resume it sooner.",
        "fa": "بودجهٔ ماهانهٔ دستیار هوش مصنوعی شما تمام شده و تا ماه بعد به مشتریان پاسخ "
        "نمی‌دهد. برای فعال‌سازی زودتر، بودجه را در تنظیمات هوش مصنوعی افزایش دهید.",
    },
    "notify.subscription.grace_period.title": {
        "en": "Your subscription payment is overdue",
        "fa": "پرداخت اشتراک شما سررسید گذشته است",
    },
    "notify.subscription.grace_period.body": {
        "en": "Your bot's billing period ended without a renewal. It keeps working for "
        "now, but will be suspended if payment isn't received soon.",
        "fa": "دورهٔ صورتحساب ربات شما بدون تمدید به پایان رسید. فعلاً همچنان کار می‌کند، "
        "اما در صورت عدم دریافت پرداخت به‌زودی معلق خواهد شد.",
    },
    "notify.subscription.renewal_due.title": {
        "en": "Your subscription renews soon",
        "fa": "اشتراک شما به‌زودی تمدید می‌شود",
    },
    "notify.subscription.renewal_due.body": {
        "en": "{days_left} day(s) left until your bot's subscription is due for renewal.",
        "fa": "{days_left} روز تا سررسید تمدید اشتراک ربات شما باقی مانده است.",
    },
}


def render(key: str, params: dict | None = None, locale: str = DEFAULT_LOCALE) -> str:
    entry = MESSAGES.get(key)
    if entry is None:
        return key

    text = entry.get(locale) or entry.get(locale.split("-")[0]) or entry.get(DEFAULT_LOCALE, key)
    for name, value in (params or {}).items():
        text = text.replace("{" + name + "}", str(value))
    return text.strip()
