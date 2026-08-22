import asyncio
import logging
import os
import re

import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
# API manzili - kerak bo'lsa Railway'dagi Environment Variables orqali o'zgartirasiz
API_BASE_URL = os.getenv("API_BASE_URL", "https://rendo-app.rendo.uz/api/v1")
VERIFY_ENDPOINT = f"{API_BASE_URL}/auth/verify-number"
# Xabarlar yuboriladigan kanal/guruh ID (bot o'sha yerda admin bo'lishi kerak)
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID")  # masalan: -1001234567890

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = Router()


class Form(StatesGroup):
    choosing_language = State()
    waiting_phone = State()
    waiting_name = State()
    waiting_issue = State()


TEXTS = {
    "uz": {
        "ask_phone": "Telefon raqamingizni yuborish uchun quyidagi tugmani bosing 👇",
        "share_phone_btn": "📱 Raqamni yuborish",
        "checking": "Raqamingiz tekshirilmoqda, biroz kuting...",
        "not_found": "Kechirasiz, sizning raqamingiz bizning bazamizda topilmadi.",
        "found_ask_name": "Raqamingiz tasdiqlandi ✅\n\nIltimos, ismingizni kiriting:",
        "ask_issue": "Rahmat, {name}! Endi qaysi masala bo'yicha yordam kerakligini qisqacha yozib qoldiring:",
        "thanks": "Rahmat! Murojaatingiz qabul qilindi ✅. Tez orada operatorlarimiz siz bilan bog'lanadi.",
        "invalid_phone": "Iltimos, telefon raqamingizni faqat «Raqamni yuborish» tugmasi orqali yuboring.",
        "error": "Xatolik yuz berdi, birozdan so'ng qayta urinib ko'ring.",
        "restart": "Qaytadan boshlash uchun /start ni bosing.",
    },
    "ru": {
        "ask_phone": "Нажмите на кнопку ниже, чтобы отправить номер телефона 👇",
        "share_phone_btn": "📱 Отправить номер",
        "checking": "Проверяем ваш номер, подождите немного...",
        "not_found": "К сожалению, ваш номер не найден в нашей базе.",
        "found_ask_name": "Ваш номер подтверждён ✅\n\nПожалуйста, введите ваше имя:",
        "ask_issue": "Спасибо, {name}! Теперь кратко опишите, по какому вопросу нужна помощь:",
        "thanks": "Спасибо! Ваше обращение принято ✅. Наши операторы скоро свяжутся с вами.",
        "invalid_phone": "Пожалуйста, отправьте номер телефона только с помощью кнопки «Отправить номер».",
        "error": "Произошла ошибка, попробуйте ещё раз чуть позже.",
        "restart": "Чтобы начать заново, нажмите /start.",
    },
}


def lang_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang_uz"),
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"),
            ]
        ]
    )


def phone_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=TEXTS[lang]["share_phone_btn"], request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def normalize_phone(raw: str) -> str:
    """Telefon raqamni faqat raqamlar shaklida, 998 bilan boshlanadigan qilib normallashtiradi."""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("998") and len(digits) == 12:
        return digits
    if len(digits) == 9:
        return "998" + digits
    if digits.startswith("8") and len(digits) == 10:
        return "998" + digits[1:]
    return digits


async def verify_number(phone: str) -> bool:
    """
    Rendo API orqali raqamni bazada bor-yo'qligini tekshiradi.

    MUHIM: haqiqiy API javobining aniq shaklini ko'rib, quyidagi
    parsing mantig'ini moslashtirish kerak bo'lishi mumkin.
    Hozirgi holatda bir nechta keng tarqalgan variant qo'llab-quvvatlanadi:
    {"exists": true}, {"found": true}, {"success": true}, {"result": true} va h.k.
    """
    payload = {"phone": phone}
    async with aiohttp.ClientSession() as session:
        async with session.post(
            VERIFY_ENDPOINT, json=payload, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status == 404:
                return False

            try:
                data = await resp.json(content_type=None)
            except Exception:
                data = {}

            if resp.status == 200:
                if isinstance(data, dict):
                    for key in ("exists", "found", "success", "is_registered", "result"):
                        if key in data:
                            return bool(data[key])
                    # Agar tanish kalit topilmasa, lekin javob bo'sh bo'lmasa - mavjud deb hisoblaymiz
                    return bool(data)
                return bool(data)

            return False


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Form.choosing_language)
    await message.answer(
        "Assalomu alaykum! Tilni tanlang / Выберите язык:",
        reply_markup=lang_keyboard(),
    )


@router.callback_query(F.data.startswith("lang_"), StateFilter(Form.choosing_language))
async def process_lang(callback: CallbackQuery, state: FSMContext):
    lang = callback.data.split("_")[1]
    await state.update_data(lang=lang)
    await state.set_state(Form.waiting_phone)
    await callback.message.delete()
    await callback.message.answer(TEXTS[lang]["ask_phone"], reply_markup=phone_keyboard(lang))
    await callback.answer()


@router.message(StateFilter(Form.waiting_phone), F.contact)
async def process_phone(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")

    contact = message.contact
    # Foydalanuvchi faqat o'z raqamini yuborishi kerak, boshqa odamning kontaktini emas
    if contact.user_id and contact.user_id != message.from_user.id:
        await message.answer(TEXTS[lang]["invalid_phone"])
        return

    phone = normalize_phone(contact.phone_number)
    await state.update_data(phone=phone)

    checking_msg = await message.answer(TEXTS[lang]["checking"], reply_markup=ReplyKeyboardRemove())

    try:
        exists = await verify_number(phone)
    except Exception as e:
        logger.exception("Verify API xatosi: %s", e)
        await checking_msg.edit_text(TEXTS[lang]["error"])
        await state.clear()
        return

    if not exists:
        await checking_msg.edit_text(TEXTS[lang]["not_found"] + "\n\n" + TEXTS[lang]["restart"])
        await state.clear()
        return

    await state.set_state(Form.waiting_name)
    await checking_msg.edit_text(TEXTS[lang]["found_ask_name"])


@router.message(StateFilter(Form.waiting_phone))
async def invalid_phone_input(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    await message.answer(TEXTS[lang]["invalid_phone"])


@router.message(StateFilter(Form.waiting_name), F.text)
async def process_name(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    name = message.text.strip()
    await state.update_data(name=name)
    await state.set_state(Form.waiting_issue)
    await message.answer(TEXTS[lang]["ask_issue"].format(name=name))


@router.message(StateFilter(Form.waiting_issue), F.text)
async def process_issue(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    name = data.get("name", "-")
    phone = data.get("phone", "-")
    issue = message.text.strip()

    username = f"@{message.from_user.username}" if message.from_user.username else "yo'q / нет"
    lang_label = "O'zbekcha" if lang == "uz" else "Русский"

    report = (
        "🆕 <b>Yangi murojaat / Новое обращение</b>\n\n"
        f"👤 <b>Ism / Имя:</b> {name}\n"
        f"📞 <b>Telefon:</b> +{phone}\n"
        f"💬 <b>Telegram:</b> {username} (id: <code>{message.from_user.id}</code>)\n"
        f"🌐 <b>Til / Язык:</b> {lang_label}\n\n"
        f"📝 <b>Xabar / Сообщение:</b>\n{issue}"
    )

    if GROUP_CHAT_ID:
        try:
            await bot.send_message(chat_id=GROUP_CHAT_ID, text=report)
        except Exception as e:
            logger.exception("Guruhga/kanalga yuborishda xatolik: %s", e)
    else:
        logger.warning("GROUP_CHAT_ID sozlanmagan - xabar hech qayerga yuborilmadi.")

    await message.answer(TEXTS[lang]["thanks"])
    await state.clear()


@router.message(StateFilter(None))
async def fallback(message: Message):
    await message.answer("Boshlash uchun /start buyrug'ini bosing / Нажмите /start, чтобы начать.")


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment o'zgaruvchisi topilmadi!")

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot ishga tushdi...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
