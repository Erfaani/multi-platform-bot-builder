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
    "menu.open_app": {"en": "🛍 Open app", "fa": "🛍 باز کردن اپلیکیشن"},
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
    "menu.properties": {"en": "Browse properties", "fa": "مشاهده املاک"},
    "bot.commerce.select_property": {
        "en": "Here are our current listings:",
        "fa": "این آگهی‌های فعلی ماست:",
    },
    "bot.commerce.sample_property_1": {"en": "2-bed apartment — downtown", "fa": "آپارتمان ۲ خواب — مرکز شهر"},
    "bot.commerce.sample_property_2": {"en": "Family house — garden", "fa": "خانهٔ ویلایی — با حیاط"},
    "bot.commerce.property_detail": {
        "en": "{title} — {price}\n{property_type}, {listing_type}\n{facts}\n{address}\n\n{description}",
        "fa": "{title} — {price}\n{property_type}، {listing_type}\n{facts}\n{address}\n\n{description}",
    },
    "bot.commerce.no_properties": {
        "en": "No properties listed yet — please check back soon.",
        "fa": "هنوز آگهی‌ای ثبت نشده — بعداً دوباره سر بزنید.",
    },
    "menu.courses": {"en": "Browse courses", "fa": "مشاهده دوره‌ها"},
    "bot.commerce.select_course": {
        "en": "Here are our current courses:",
        "fa": "این دوره‌های فعلی ماست:",
    },
    "bot.commerce.sample_course_1": {"en": "Beginner Photoshop", "fa": "فتوشاپ مقدماتی"},
    "bot.commerce.sample_course_2": {"en": "Advanced Excel", "fa": "اکسل پیشرفته"},
    "bot.commerce.course_detail": {
        "en": "{title} — {price}\nInstructor: {instructor}\nDuration: {duration}\n\n{description}",
        "fa": "{title} — {price}\nمدرس: {instructor}\nمدت: {duration}\n\n{description}",
    },
    "bot.commerce.no_courses": {
        "en": "No courses listed yet — please check back soon.",
        "fa": "هنوز دوره‌ای ثبت نشده — بعداً دوباره سر بزنید.",
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
    "bot.crm.ask_email": {
        "en": "And your email address?",
        "fa": "ایمیل شما چیست؟",
    },
    "bot.crm.invalid_email": {
        "en": "That doesn't look like a valid email address. Please try again.",
        "fa": "این ایمیل معتبر به‌نظر نمی‌رسد. لطفاً دوباره تلاش کنید.",
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

    # --- Telegram Mini App (Phase 10.5) ---
    "bot.miniapp.launch": {
        "en": "Browse and book right here — tap below to open the app.",
        "fa": "همین‌جا مرور و رزرو کنید — برای باز کردن اپلیکیشن ضربه بزنید.",
    },
    "bot.miniapp.unavailable": {
        "en": "The in-chat app isn't available on this platform yet — use the menu below instead.",
        "fa": "اپلیکیشن داخل چت هنوز در این پلتفرم در دسترس نیست — از منوی زیر استفاده کنید.",
    },

    # --- account linking (spec §47) ---
    "bot.link.usage": {
        "en": "Send /link followed by the code shown on your dashboard, e.g. /link 483920.",
        "fa": "کد نمایش‌داده‌شده در داشبورد را بعد از /link بفرستید، مثل /link 483920.",
    },
    "bot.link.invalid_code": {
        "en": "That code isn't valid or has expired. Generate a new one from My Bots → Bot Management.",
        "fa": "این کد نامعتبر یا منقضی شده است. کد جدیدی از «ربات‌های من ← مدیریت ربات» بسازید.",
    },
    "bot.link.success": {
        "en": "Your account is linked! Send /admin to manage this bot from here.",
        "fa": "حساب شما متصل شد! برای مدیریت این ربات از همینجا، /admin را بفرستید.",
    },

    # --- owner admin menu (day-to-day management, spec's hybrid model) ---
    "bot.admin.not_linked": {
        "en": "This is for bot managers. Connect your account from My Bots → Bot Management on the website, then send /link with the code shown there.",
        "fa": "این بخش برای مدیران ربات است. از «ربات‌های من ← مدیریت ربات» در وبسایت حساب خود را متصل کنید و سپس /link را با کد نمایش‌داده‌شده بفرستید.",
    },
    "bot.admin.menu": {
        "en": "Bot management — what would you like to do?",
        "fa": "مدیریت ربات — چه کاری می‌خواهید انجام دهید؟",
    },
    "bot.admin.recentLeads": {"en": "Recent leads", "fa": "سرنخ‌های اخیر"},
    "bot.admin.todaysAppointments": {"en": "Upcoming appointments", "fa": "نوبت‌های پیش‌رو"},
    "bot.admin.addFaq": {"en": "Add an FAQ", "fa": "افزودن سوال متداول"},
    "bot.admin.moreSettings": {"en": "More settings", "fa": "تنظیمات بیشتر"},
    "bot.admin.noLeads": {"en": "No leads yet.", "fa": "هنوز سرنخی ثبت نشده."},
    "bot.admin.leadsList": {"en": "Recent leads:\n{lines}", "fa": "سرنخ‌های اخیر:\n{lines}"},
    "bot.admin.noAppointments": {
        "en": "Nothing in the next 24 hours.",
        "fa": "در ۲۴ ساعت آینده چیزی ثبت نشده.",
    },
    "bot.admin.appointmentsList": {
        "en": "Upcoming appointments:\n{lines}",
        "fa": "نوبت‌های پیش‌رو:\n{lines}",
    },
    "bot.admin.faqAskQuestion": {
        "en": "What's the question?",
        "fa": "سوال چیست؟",
    },
    "bot.admin.faqAskAnswer": {
        "en": "And the answer?",
        "fa": "و پاسخ آن؟",
    },
    "bot.admin.faqAdded": {
        "en": "Added! It's live for customers right away.",
        "fa": "افزوده شد! همین حالا برای مشتریان فعال است.",
    },
    "bot.admin.moreSettingsInfo": {
        "en": "That's managed from the website: My Bots → Bot Management.",
        "fa": "این بخش از وبسایت مدیریت می‌شود: «ربات‌های من ← مدیریت ربات».",
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

    # --- chat-native bot ordering (Phase 10.5, the platform's own builder bot) ---
    "menu.build_bot": {"en": "Build a new bot", "fa": "ساخت ربات جدید"},
    "menu.order_status": {"en": "Check my order status", "fa": "بررسی وضعیت سفارش"},
    "bot.builder.no_templates": {
        "en": "Nothing is available to build right now — please try again shortly.",
        "fa": "در حال حاضر چیزی برای ساخت موجود نیست — کمی بعد دوباره تلاش کنید.",
    },
    "bot.builder.pick_template": {
        "en": "Let's build your bot! What kind of business is this for?",
        "fa": "بیایید ربات شما را بسازیم! این ربات برای چه نوع کسب‌وکاری است؟",
    },
    "bot.builder.pick_features": {
        "en": "Choose what your bot should do. Tap to toggle, then Continue.\nAlways included: {included}",
        "fa": "کارهایی که ربات شما باید انجام دهد را انتخاب کنید. برای تغییر ضربه بزنید، سپس ادامه.\nهمیشه شامل: {included}",
    },
    "bot.builder.continue": {"en": "Continue ➜", "fa": "ادامه ➜"},
    "bot.builder.addOne": {"en": "Add one now", "fa": "همین حالا اضافه کنم"},
    "bot.builder.skipFeature": {
        "en": "Skip — I'll add this later", "fa": "رد شوم — بعداً اضافه می‌کنم",
    },
    "bot.builder.addAnother": {"en": "Add another", "fa": "افزودن مورد دیگر"},
    "bot.builder.doneWithFeature": {"en": "I'm done", "fa": "تمام شد"},
    "builder.collect.faq.title": {
        "en": "Enter your frequently asked questions and answers",
        "fa": "پرسش‌ها و پاسخ‌های متداول خود را وارد کنید",
    },
    "builder.collect.property_listings.title": {
        "en": "How would you like to add your property listings?",
        "fa": "چطور می‌خواهید آگهی‌های ملکی خود را اضافه کنید؟",
    },
    "builder.collect.course_catalog.title": {
        "en": "How would you like to add your courses?",
        "fa": "چطور می‌خواهید دوره‌های خود را اضافه کنید؟",
    },
    "bot.builder.item_added": {
        "en": "Added! ({count} so far) Add another, or move on?",
        "fa": "افزوده شد! (تا الان {count} مورد) مورد دیگری اضافه کنید یا ادامه بدهید؟",
    },
    "bot.builder.ask_business_name": {
        "en": "What's your business called?",
        "fa": "نام کسب‌وکار شما چیست؟",
    },
    "bot.builder.price_summary": {
        "en": "Here's the price:\nOne-time setup: {once}\nMonthly: {monthly}\nDue now: {total}",
        "fa": "این هزینه آن است:\nراه‌اندازی یک‌بار: {once}\nماهانه: {monthly}\nقابل پرداخت الان: {total}",
    },
    "bot.builder.placeOrder": {"en": "Place order", "fa": "ثبت سفارش"},
    "bot.builder.cancel": {"en": "Cancel", "fa": "انصراف"},
    "bot.builder.ask_email": {
        "en": "Almost done! What's your email? We'll create your account with it.",
        "fa": "تقریباً تمام شد! ایمیل شما چیست؟ حساب شما را با آن می‌سازیم.",
    },
    "bot.builder.invalid_email": {
        "en": "That doesn't look like a valid email. Please try again.",
        "fa": "این یک ایمیل معتبر به نظر نمی‌رسد. دوباره امتحان کنید.",
    },
    "bot.builder.email_taken": {
        "en": "An account already exists for that email. Please finish your order from the website, or connect your existing account (My Bots → Bot Management → link this bot) and message us again.",
        "fa": "برای این ایمیل قبلاً حسابی ساخته شده است. لطفاً سفارش خود را از وبسایت تکمیل کنید، یا حساب موجود خود را متصل کنید («ربات‌های من ← مدیریت ربات ← اتصال این ربات») و دوباره پیام دهید.",
    },
    "bot.builder.no_payment_methods": {
        "en": "No payment method is available for this order right now — please try again from the website.",
        "fa": "در حال حاضر روش پرداختی برای این سفارش موجود نیست — لطفاً از وبسایت دوباره تلاش کنید.",
    },
    "bot.builder.choose_payment_method": {
        "en": "How would you like to pay?",
        "fa": "چگونه می‌خواهید پرداخت کنید؟",
    },
    "bot.builder.payment_instructions": {
        "en": "{instructions}\n\nTo finish, upload your payment receipt here: {link}\nWe'll set up your bot as soon as it's confirmed — check progress any time from the menu.",
        "fa": "{instructions}\n\nبرای اتمام، رسید پرداخت خود را اینجا بارگذاری کنید: {link}\nبه محض تأیید، ربات شما راه‌اندازی می‌شود — هر زمان می‌توانید از منو وضعیت را بررسی کنید.",
    },
    "bot.builder.no_orders": {
        "en": "You don't have any orders yet. Use the menu to build your first bot!",
        "fa": "هنوز سفارشی ثبت نکرده‌اید. از منو برای ساخت اولین ربات خود استفاده کنید!",
    },
    "bot.builder.order_status": {
        "en": "Order #{number}: {status_text}",
        "fa": "سفارش شماره {number}: {status_text}",
    },
    "bot.builder.orderStatus.DRAFT": {"en": "Being prepared.", "fa": "در حال آماده‌سازی."},
    "bot.builder.orderStatus.PENDING_PAYMENT": {
        "en": "Awaiting your payment.", "fa": "در انتظار پرداخت شما.",
    },
    "bot.builder.orderStatus.RECEIPT_SUBMITTED": {
        "en": "Your receipt was received — awaiting review.", "fa": "رسید شما دریافت شد — در انتظار بررسی.",
    },
    "bot.builder.orderStatus.PAYMENT_REVIEW": {
        "en": "Your payment is being reviewed.", "fa": "پرداخت شما در حال بررسی است.",
    },
    "bot.builder.orderStatus.PAYMENT_REJECTED": {
        "en": "Your payment was not accepted — please check the website for details.",
        "fa": "پرداخت شما تأیید نشد — برای جزئیات به وبسایت مراجعه کنید.",
    },
    "bot.builder.orderStatus.PAID": {
        "en": "Payment confirmed — setting up your bot now.", "fa": "پرداخت تأیید شد — در حال راه‌اندازی ربات شما.",
    },
    "bot.builder.orderStatus.PROVISIONING": {
        "en": "Setting up your bot.", "fa": "در حال راه‌اندازی ربات شما.",
    },
    "bot.builder.orderStatus.CONFIGURING": {
        "en": "Applying your settings.", "fa": "در حال اعمال تنظیمات شما.",
    },
    "bot.builder.orderStatus.DEPLOYING": {
        "en": "Almost live.", "fa": "تقریباً آماده است.",
    },
    "bot.builder.orderStatus.ACTIVE": {
        "en": "🎉 Your bot is live! Manage it from My Bots on the website.",
        "fa": "🎉 ربات شما فعال شد! از «ربات‌های من» در وبسایت آن را مدیریت کنید.",
    },
    "bot.builder.orderStatus.GRACE_PERIOD": {
        "en": "Live, but your subscription needs renewal soon.", "fa": "فعال، اما اشتراک شما به‌زودی نیاز به تمدید دارد.",
    },
    "bot.builder.orderStatus.SUSPENDED": {
        "en": "Suspended — please check the website.", "fa": "معلق شده — لطفاً به وبسایت مراجعه کنید.",
    },
    "bot.builder.orderStatus.CANCELLED": {"en": "Cancelled.", "fa": "لغو شد."},
    "bot.builder.orderStatus.FAILED": {
        "en": "Something went wrong — our team has been notified.", "fa": "مشکلی پیش آمد — تیم ما مطلع شد.",
    },

    # --- CollectItemField.label_key mirrors (Stage 2/3's `builder.collect.*` keys were
    # only ever wired into the website's own i18n JSON; the chat-native builder above
    # needs the identical text from this, its separate, Python-side catalogue) ---
    "builder.collect.faq.question": {"en": "Question", "fa": "پرسش"},
    "builder.collect.faq.answer": {"en": "Answer", "fa": "پاسخ"},
    "builder.collect.property_listings.title_field": {"en": "Title", "fa": "عنوان"},
    "builder.collect.property_listings.listing_type": {"en": "Listing type", "fa": "نوع آگهی"},
    "builder.collect.property_listings.sale": {"en": "For sale", "fa": "برای فروش"},
    "builder.collect.property_listings.rent": {"en": "For rent", "fa": "برای اجاره"},
    "builder.collect.property_listings.property_type": {"en": "Property type", "fa": "نوع ملک"},
    "builder.collect.property_listings.apartment": {"en": "Apartment", "fa": "آپارتمان"},
    "builder.collect.property_listings.house": {"en": "House", "fa": "خانه ویلایی"},
    "builder.collect.property_listings.land": {"en": "Land", "fa": "زمین"},
    "builder.collect.property_listings.commercial": {"en": "Commercial", "fa": "تجاری"},
    "builder.collect.property_listings.price": {"en": "Price", "fa": "قیمت"},
    "builder.collect.property_listings.address": {"en": "Address", "fa": "آدرس"},
    "builder.collect.property_listings.description": {"en": "Description", "fa": "توضیحات"},
    "builder.collect.course_catalog.title_field": {"en": "Course title", "fa": "عنوان دوره"},
    "builder.collect.course_catalog.instructor": {"en": "Instructor (optional)", "fa": "مدرس (اختیاری)"},
    "builder.collect.course_catalog.price": {"en": "Price", "fa": "قیمت"},
    "builder.collect.course_catalog.duration": {
        "en": "Duration (e.g. \"6 weeks\")", "fa": "مدت (مثلاً «۶ هفته»)",
    },
    "builder.collect.course_catalog.description": {"en": "Description", "fa": "توضیحات"},
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
