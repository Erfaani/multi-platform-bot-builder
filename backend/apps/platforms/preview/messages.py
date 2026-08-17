"""Default bot copy for the pre-payment preview.

Keys, not literals, everywhere in the manifests — this is where they resolve. In Phase 4
a bot's own `BotConfiguration` overrides these per customer; the resolution chain is
bot override → template default → **this catalogue** → the key itself (I18N.md §1).

Keeping the catalogue in code rather than the database is deliberate for now: it ships
with the manifests that reference it, so a missing key is a review-time problem rather
than a production one.
"""

from __future__ import annotations

DEFAULT_LOCALE = "en"

MESSAGES: dict[str, dict[str, str]] = {
    # --- shell ---
    "bot.welcome": {
        "en": "Welcome to {business}! 👋\nHow can we help you today?",
        "fa": "به {business} خوش آمدید! 👋\nچطور می‌توانیم کمکتان کنیم؟",
    },
    "menu.about": {"en": "About us", "fa": "درباره ما"},
    "menu.contact": {"en": "Contact", "fa": "تماس با ما"},
    "menu.location": {"en": "Location", "fa": "آدرس"},
    "menu.working_hours": {"en": "Opening hours", "fa": "ساعات کاری"},
    "menu.faq": {"en": "FAQ", "fa": "سوالات متداول"},
    "menu.book": {"en": "Book an appointment", "fa": "رزرو نوبت"},
    "menu.catalog": {"en": "Browse products", "fa": "مشاهده محصولات"},
    "menu.cart": {"en": "My cart", "fa": "سبد خرید"},
    "menu.reserve": {"en": "Reserve a table", "fa": "رزرو میز"},
    "menu.ask": {"en": "Ask a question", "fa": "پرسش از دستیار"},
    "menu.contact_us": {"en": "Send us a message", "fa": "ارسال پیام"},
    "menu.consultation": {"en": "Request a consultation", "fa": "درخواست مشاوره"},
    "menu.feedback": {"en": "Leave feedback", "fa": "ثبت نظر"},

    # --- business ---
    "bot.business.about": {
        "en": "{business}\n\nWe have been serving our community with care and expertise.",
        "fa": "{business}\n\nما با دقت و تخصص در خدمت شما هستیم.",
    },
    "bot.business.contact": {
        "en": "📞 Phone: +1 555 0100\n✉️ Email: hello@example.com",
        "fa": "📞 تلفن: ۰۲۱-۱۲۳۴۵۶۷۸\n✉️ ایمیل: hello@example.com",
    },
    "bot.business.location": {
        "en": "📍 12 Example Street, Suite 4\nTap the map below for directions.",
        "fa": "📍 خیابان نمونه، پلاک ۱۲، واحد ۴\nبرای مسیریابی روی نقشه بزنید.",
    },
    "bot.business.hours": {
        "en": "Saturday–Wednesday: 9:00–18:00\nThursday: 9:00–13:00\nFriday: closed",
        "fa": "شنبه تا چهارشنبه: ۹:۰۰–۱۸:۰۰\nپنجشنبه: ۹:۰۰–۱۳:۰۰\nجمعه: تعطیل",
    },

    # --- faq ---
    "bot.faq.prompt": {
        "en": "Here are the questions we get most often:",
        "fa": "پرتکرارترین پرسش‌ها:",
    },
    "bot.faq.sample_question_1": {
        "en": "Do I need an appointment?",
        "fa": "آیا نیاز به نوبت قبلی دارم؟",
    },
    "bot.faq.sample_question_2": {"en": "Where are you located?", "fa": "آدرس شما کجاست؟"},

    # --- appointments ---
    "bot.appointment.select_service": {
        "en": "Which service would you like to book?",
        "fa": "کدام خدمت را می‌خواهید رزرو کنید؟",
    },
    "bot.appointment.sample_service_1": {"en": "Consultation", "fa": "ویزیت"},
    "bot.appointment.sample_service_2": {"en": "Follow-up visit", "fa": "ویزیت پیگیری"},
    "bot.appointment.select_staff": {
        "en": "Who would you like to see?",
        "fa": "با چه کسی می‌خواهید ملاقات کنید؟",
    },
    "bot.appointment.sample_staff_1": {"en": "Dr. Ahmadi", "fa": "دکتر احمدی"},
    "bot.appointment.sample_staff_2": {"en": "Dr. Rezaei", "fa": "دکتر رضایی"},
    "bot.appointment.select_slot": {
        "en": "Available times:",
        "fa": "زمان‌های آزاد:",
    },
    "bot.appointment.sample_slot_1": {"en": "10:00", "fa": "۱۰:۰۰"},
    "bot.appointment.sample_slot_2": {"en": "11:30", "fa": "۱۱:۳۰"},
    "bot.appointment.sample_slot_3": {"en": "14:00", "fa": "۱۴:۰۰"},
    "bot.appointment.confirmed": {
        "en": "✅ Booked! {service} with {staff} on {date} at {time}.\nWe'll send a reminder beforehand.",
        "fa": "✅ ثبت شد! {service} با {staff} در تاریخ {date} ساعت {time}.\nپیش از آن یادآوری ارسال می‌شود.",
    },
    "bot.appointment.reminder": {
        "en": "⏰ Reminder: {service} with {staff} today at {time}.",
        "fa": "⏰ یادآوری: {service} با {staff} امروز ساعت {time}.",
    },
    "bot.appointment.no_services": {
        "en": "This business hasn't set up any bookable services yet.",
        "fa": "این کسب‌وکار هنوز خدمتی برای رزرو تنظیم نکرده است.",
    },
    "bot.appointment.no_staff": {
        "en": "Nobody is available to take that booking right now.",
        "fa": "در حال حاضر کسی برای این رزرو در دسترس نیست.",
    },
    "bot.appointment.no_availability": {
        "en": "No open times in the next few weeks. Please check back later.",
        "fa": "در چند هفتهٔ آینده زمان آزادی وجود ندارد. لطفاً بعداً دوباره سر بزنید.",
    },
    "bot.appointment.expired": {
        "en": "That option is no longer available. Let's start over.",
        "fa": "این گزینه دیگر در دسترس نیست. از ابتدا شروع کنیم.",
    },
    "bot.appointment.slot_taken": {
        "en": "Sorry, someone just booked that time. Please pick another.",
        "fa": "متأسفانه این زمان همین الان رزرو شد. لطفاً زمان دیگری انتخاب کنید.",
    },

    # --- commerce ---
    "bot.commerce.select_category": {
        "en": "What are you looking for?",
        "fa": "دنبال چه چیزی هستید؟",
    },
    "bot.commerce.sample_category_1": {"en": "Best sellers", "fa": "پرفروش‌ها"},
    "bot.commerce.sample_category_2": {"en": "New arrivals", "fa": "تازه‌ها"},
    "bot.commerce.product_detail": {
        "en": "{name} — {price}\n{description}",
        "fa": "{name} — {price}\n{description}",
    },
    "bot.commerce.add_to_cart": {"en": "Add to cart", "fa": "افزودن به سبد"},
    "bot.commerce.added_to_cart": {
        "en": "Added {name} to your cart.",
        "fa": "{name} به سبد شما افزوده شد.",
    },
    "bot.commerce.cart_summary": {
        "en": "Your cart:\n{items}\n\nTotal: {total}",
        "fa": "سبد خرید شما:\n{items}\n\nجمع: {total}",
    },
    "bot.commerce.checkout": {"en": "Checkout", "fa": "تکمیل خرید"},
    "bot.commerce.order_placed": {
        "en": "✅ Order received. We'll message you when it's on the way.",
        "fa": "✅ سفارش ثبت شد. هنگام ارسال به شما اطلاع می‌دهیم.",
    },
    "bot.commerce.no_products": {
        "en": "Nothing available here yet.",
        "fa": "فعلاً چیزی برای نمایش نیست.",
    },
    "bot.commerce.expired": {
        "en": "That option is no longer available. Let's start over.",
        "fa": "این گزینه دیگر در دسترس نیست. از ابتدا شروع کنیم.",
    },
    "bot.commerce.out_of_stock": {
        "en": "Sorry, that item just sold out.",
        "fa": "متأسفانه این کالا به‌تازگی تمام شد.",
    },
    "bot.commerce.empty_cart": {
        "en": "Your cart is empty.",
        "fa": "سبد خرید شما خالی است.",
    },

    # --- restaurant ---
    "bot.restaurant.select_party_size": {
        "en": "How many people?",
        "fa": "چند نفر هستید؟",
    },
    "bot.restaurant.select_time": {
        "en": "What time would you like the table?",
        "fa": "میز را برای چه ساعتی می‌خواهید؟",
    },
    "bot.restaurant.sample_slot_1": {"en": "19:00", "fa": "۱۹:۰۰"},
    "bot.restaurant.sample_slot_2": {"en": "20:30", "fa": "۲۰:۳۰"},
    "bot.restaurant.slot_taken": {
        "en": "Sorry, that could not be reserved. Please pick another time.",
        "fa": "متأسفانه این زمان قابل رزرو نبود. لطفاً زمان دیگری انتخاب کنید.",
    },
    "bot.restaurant.reserved": {
        "en": "✅ Table for {party_size} reserved for {date} at {time}.",
        "fa": "✅ میز برای {party_size} نفر در تاریخ {date} ساعت {time} رزرو شد.",
    },
    "bot.restaurant.order_summary": {
        "en": "Your order is confirmed and being prepared.",
        "fa": "سفارش شما ثبت شد و در حال آماده‌سازی است.",
    },
    "bot.commerce.no_availability": {
        "en": "No open times in the next couple of weeks. Please check back later.",
        "fa": "در چند هفتهٔ آینده زمان آزادی نیست. لطفاً بعداً دوباره سر بزنید.",
    },

    # --- crm ---
    "bot.crm.ask_message": {
        "en": "Please type your message and we'll get back to you.",
        "fa": "پیام خود را بنویسید تا با شما تماس بگیریم.",
    },
    "bot.crm.message_received": {
        "en": "Thanks! We received your message and will get back to you soon.",
        "fa": "متشکریم! پیام شما دریافت شد و به‌زودی با شما تماس می‌گیریم.",
    },
    "bot.crm.ask_phone": {
        "en": "Please share your phone number and we'll call you back.",
        "fa": "شماره تماس خود را بفرستید تا با شما تماس بگیریم.",
    },
    "bot.crm.invalid_phone": {
        "en": "That doesn't look like a phone number. Please send digits only.",
        "fa": "این شماره معتبر به‌نظر نمی‌رسد. لطفاً فقط عدد ارسال کنید.",
    },
    "bot.crm.phone_received": {
        "en": "Thanks! We'll call you back soon.",
        "fa": "متشکریم! به‌زودی با شما تماس می‌گیریم.",
    },
    "bot.crm.ask_rating": {
        "en": "How would you rate your experience?",
        "fa": "تجربه خود را چطور ارزیابی می‌کنید؟",
    },
    "bot.crm.feedback_received": {
        "en": "Thank you for your feedback!",
        "fa": "از بازخورد شما سپاسگزاریم!",
    },

    # --- ai ---
    "bot.ai.prompt": {
        "en": "Ask me anything about our services.",
        "fa": "هر سوالی دربارهٔ خدمات ما دارید بپرسید.",
    },
    "bot.ai.sample_answer": {
        "en": "We're open Saturday to Wednesday, 9:00 to 18:00. "
        "Would you like me to book an appointment?",
        "fa": "ما شنبه تا چهارشنبه از ۹:۰۰ تا ۱۸:۰۰ باز هستیم. "
        "می‌خواهید برایتان نوبت رزرو کنم؟",
    },
    "bot.ai.answer": {"en": "{answer}", "fa": "{answer}"},
    "bot.ai.dont_know": {
        "en": "I don't have an answer to that yet — please contact us directly and we'll help.",
        "fa": "هنوز پاسخی برای این سوال ندارم — لطفاً مستقیماً با ما تماس بگیرید تا کمک کنیم.",
    },
    "bot.ai.unavailable": {
        "en": "The assistant is unavailable right now. Please try again later or contact us directly.",
        "fa": "دستیار در حال حاضر در دسترس نیست. لطفاً بعداً دوباره تلاش کنید یا مستقیماً تماس بگیرید.",
    },
    "bot.ai.error": {
        "en": "Sorry, I couldn't answer that just now. Please try again in a moment.",
        "fa": "متأسفیم، الان نتوانستم پاسخ دهم. لطفاً کمی بعد دوباره تلاش کنید.",
    },

    # --- notifications ---
    "bot.notifications.new_activity": {
        "en": "🔔 New appointment booked by a customer.",
        "fa": "🔔 یک نوبت جدید توسط مشتری ثبت شد.",
    },

    # --- runtime shell ---
    "bot.welcome.custom": {"en": "{text}", "fa": "{text}"},
    "bot.help": {
        "en": "This is the {business} bot. Use the menu below, or send /menu at any time.",
        "fa": "این ربات {business} است. از منوی زیر استفاده کنید یا هر زمان /menu بفرستید.",
    },
    "bot.language.prompt": {"en": "Choose your language:", "fa": "زبان خود را انتخاب کنید:"},
    "bot.language.changed": {"en": "Language updated.", "fa": "زبان تغییر کرد."},
    "bot.language.en": {"en": "English", "fa": "English"},
    "bot.language.fa": {"en": "فارسی", "fa": "فارسی"},
    "bot.error.generic": {
        "en": "Sorry — something went wrong on our side. Please try again.",
        "fa": "متأسفیم، مشکلی از سمت ما پیش آمد. لطفاً دوباره تلاش کنید.",
    },
    "bot.session.expired": {
        "en": "That took a while, so I've started again. Here's the main menu.",
        "fa": "کمی طول کشید، بنابراین از ابتدا شروع می‌کنیم. این منوی اصلی است.",
    },

    # --- business content, filled from what the customer entered ---
    "bot.business.about.custom": {"en": "{business}\n\n{description}", "fa": "{business}\n\n{description}"},
    "bot.business.contact.custom": {
        "en": "📞 Phone: {phone}\n✉️ Email: {email}",
        "fa": "📞 تلفن: {phone}\n✉️ ایمیل: {email}",
    },
    "bot.business.location.custom": {"en": "📍 {address}", "fa": "📍 {address}"},
    "bot.business.hours.custom": {"en": "{hours}", "fa": "{hours}"},
    "bot.faq.empty": {
        "en": "We haven't added any questions yet.",
        "fa": "هنوز پرسشی اضافه نشده است.",
    },
    "bot.faq.answer": {"en": "{question}\n\n{answer}", "fa": "{question}\n\n{answer}"},

    # --- preview step titles ---
    "preview.step.welcome": {"en": "First message", "fa": "پیام خوش‌آمد"},
    "preview.step.about": {"en": "About the business", "fa": "دربارهٔ کسب‌وکار"},
    "preview.step.contact": {"en": "Contact details", "fa": "اطلاعات تماس"},
    "preview.step.location": {"en": "Location", "fa": "آدرس"},
    "preview.step.hours": {"en": "Opening hours", "fa": "ساعات کاری"},
    "preview.step.faq": {"en": "Frequently asked questions", "fa": "سوالات متداول"},
    "preview.step.book_service": {"en": "Choosing a service", "fa": "انتخاب خدمت"},
    "preview.step.book_staff": {"en": "Choosing a specialist", "fa": "انتخاب متخصص"},
    "preview.step.book_slot": {"en": "Choosing a time", "fa": "انتخاب زمان"},
    "preview.step.book_confirm": {"en": "Confirmation", "fa": "تأیید"},
    "preview.step.reminder": {"en": "Automatic reminder", "fa": "یادآوری خودکار"},
    "preview.step.catalog": {"en": "Browsing the catalogue", "fa": "مرور محصولات"},
    "preview.step.product": {"en": "Product details", "fa": "جزئیات محصول"},
    "preview.step.cart": {"en": "The cart", "fa": "سبد خرید"},
    "preview.step.order_placed": {"en": "Order placed", "fa": "ثبت سفارش"},
    "preview.step.reserve": {"en": "Reserving a table", "fa": "رزرو میز"},
    "preview.step.food_order": {"en": "Food order", "fa": "سفارش غذا"},
    "preview.step.contact_request": {"en": "Message form", "fa": "فرم پیام"},
    "preview.step.consultation": {"en": "Consultation request", "fa": "درخواست مشاوره"},
    "preview.step.feedback": {"en": "Feedback", "fa": "ثبت نظر"},
    "preview.step.ai_ask": {"en": "Asking the assistant", "fa": "پرسش از دستیار"},
    "preview.step.ai_answer": {"en": "The assistant answers", "fa": "پاسخ دستیار"},
    "preview.step.owner_notification": {"en": "Owner alert", "fa": "اعلان مدیر"},
    "preview.step.main_menu": {"en": "Main menu", "fa": "منوی اصلی"},
}


#: Prefix for customer-authored text (an FAQ question, a product name) that has no
#: translation key because the customer wrote it. Keeping it explicit means a genuinely
#: missing key still shows as a key in review, instead of being mistaken for content.
LITERAL_PREFIX = "literal:"


def translate(key: str, params: dict | None = None, locale: str = DEFAULT_LOCALE) -> str:
    """Resolve a message key, falling back through locale → default → the key itself."""
    if key.startswith(LITERAL_PREFIX):
        return key[len(LITERAL_PREFIX) :]

    entry = MESSAGES.get(key)
    if entry is None:
        return key

    text = entry.get(locale) or entry.get(locale.split("-")[0]) or entry.get(DEFAULT_LOCALE, key)
    if params:
        for name, value in params.items():
            text = text.replace("{" + name + "}", str(value))
    return text
