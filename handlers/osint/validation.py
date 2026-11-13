import re
import phonenumbers

from urllib.parse import urlsplit
from phonenumbers import NumberParseException

# =========================
# ОГРАНИЧЕНИЯ ВАЛИДАЦИИ
# =========================

USERNAME_MIN_LENGTH = 4
USERNAME_MAX_LENGTH = 32

TELEGRAM_ID_MIN_LENGTH = 5
TELEGRAM_ID_MAX_LENGTH = 15

TELEGRAM_DOMAINS = {
    "t.me",
    "telegram.me",
    "telegram.dog",
}


# =========================
# ВАЛИДАЦИЯ РОССИЙСКОГО НОМЕРА
# =========================

def validate_phone(
    value: str,
) -> tuple[bool, str]:

    phone = value.strip()

    if not phone:
        return (
            False,
            "⚠️ Номер телефона не указан.",
        )

    if not re.fullmatch(r"\+?[0-9\s()\-]+", phone):
        return (
            False,
            "⚠️ Неверный формат номера.\n\n"
            "Используйте цифры. Можно добавить +, "
            "пробелы, скобки или дефисы.",
        )

    phone = re.sub(r"[\s()\-]", "", phone)

    if phone.startswith("+"):
        if not phone.startswith("+7"):
            return (
                False,
                "⚠️ Пока поддерживаются только номера России (+7).",
            )

        normalized_input = phone

    elif phone.startswith("8") and len(phone) == 11:
        normalized_input = "+7" + phone[1:]

    elif phone.startswith("7") and len(phone) == 11:
        normalized_input = "+" + phone

    elif len(phone) == 10:
        normalized_input = "+7" + phone

    else:
        return (
            False,
            "⚠️ Номер введён неверно.\n\n"
            "Пример: +7 999 123-45-67",
        )

    try:
        parsed_number = phonenumbers.parse(
            normalized_input,
            "RU",
        )

    except NumberParseException:
        return (
            False,
            "⚠️ Номер введён неверно.\n\n"
            "Пример: +7 999 123-45-67",
        )

    if not phonenumbers.is_possible_number(parsed_number):
        return (
            False,
            "⚠️ Номер введён неверно.\n\n"
            "Пример: +7 999 123-45-67",
        )

    if not phonenumbers.is_valid_number(parsed_number):
        return (
            False,
            "⚠️ Номер введён неверно.\n\n"
            "Пример: +7 999 123-45-67",
        )

    if phonenumbers.region_code_for_number(parsed_number) != "RU":
        return (
            False,
            "⚠️ Этот номер не относится к российской нумерации.",
        )

    normalized_number = phonenumbers.format_number(
        parsed_number,
        phonenumbers.PhoneNumberFormat.E164,
    )

    return True, normalized_number.replace("+", "")
    
    
# =========================
# НОРМАЛИЗАЦИЯ TELEGRAM URL
# =========================

def normalize_telegram_url(
    value: str,
) -> tuple[bool, str]:

    value = value.strip()

    if not value:
        return False, ""

    url_pattern = re.compile(
        r"^(?:https?://)?"
        r"(?:t\.me|telegram\.me|telegram\.dog)"
        r"(?:/|$)",
        re.IGNORECASE,
    )

    if not url_pattern.match(value):
        return False, ""

    url = value

    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url

    try:
        parsed = urlsplit(url)

        domain = (parsed.hostname or "").lower()

        if domain not in TELEGRAM_DOMAINS:
            return False, ""

        if parsed.username or parsed.password:
            return False, ""

        if parsed.port is not None:
            return False, ""

        raw_path = parsed.path

        if not raw_path.startswith("/"):
            return False, ""

        if raw_path.startswith("//"):
            return False, ""

        path = raw_path[1:]

        if path.endswith("/"):
            path = path[:-1]

        if not path:
            return False, ""

        parts = path.split("/")

        if any(not part for part in parts):
            return False, ""

        if parts[0].lower() == "s":

            if len(parts) not in (2, 3):
                return False, ""

            username = parts[1]

            if len(parts) == 3 and not re.fullmatch(
                r"[0-9]+",
                parts[2],
            ):
                return False, ""

        else:

            if len(parts) not in (1, 2):
                return False, ""

            username = parts[0]

            if len(parts) == 2 and not re.fullmatch(
                r"[0-9]+",
                parts[1],
            ):
                return False, ""

        if username.startswith("+"):
            return False, ""

        if username.lower() == "joinchat":
            return False, ""

        return True, username

    except (ValueError, TypeError):
        return False, ""


# =========================
# ВАЛИДАЦИЯ USERNAME
# =========================

def validate_username(
    value: str,
) -> tuple[bool, str]:

    username = value.strip()

    if not username:
        return (
            False,
            "⚠️ Username не указан.",
        )

    is_url, extracted_username = normalize_telegram_url(
        username
    )

    if is_url:
        username = extracted_username

    elif re.match(
        r"^(?:https?://|www\.|t\.me(?:/|$)|"
        r"telegram\.me(?:/|$)|telegram\.dog(?:/|$))",
        username,
        re.IGNORECASE,
    ):
        return (
            False,
            "⚠️ Некорректная Telegram-ссылка.",
        )

    if username.startswith("@"):
        username = username[1:]

    if not username:
        return (
            False,
            "⚠️ Username не указан.",
        )

    if username.startswith("@"):
        return (
            False,
            "⚠️ Неверный формат username.\n\n"
            "Используйте только один символ @ в начале.",
        )

    if len(username) < USERNAME_MIN_LENGTH:
        return (
            False,
            "⚠️ Недопустимая длина username.\n\n"
            f"Минимум: {USERNAME_MIN_LENGTH} символа.",
        )

    if len(username) > USERNAME_MAX_LENGTH:
        return (
            False,
            "⚠️ Недопустимая длина username.\n\n"
            f"Максимум: {USERNAME_MAX_LENGTH} символов.",
        )

    if not re.fullmatch(
        r"[A-Za-z0-9_]+",
        username,
    ):
        return (
            False,
            "⚠️ Неверный формат username.\n\n"
            "Допустимы только латинские буквы, "
            "цифры и символ подчёркивания.",
        )

    if not username[0].isascii() or not username[0].isalpha():
        return (
            False,
            "⚠️ Username должен начинаться "
            "с латинской буквы.",
        )

    if "__" in username:
        return (
            False,
            "⚠️ Username не может содержать "
            "двойные подчёркивания.",
        )

    if username.endswith("_"):
        return (
            False,
            "⚠️ Username не может заканчиваться "
            "символом подчёркивания.",
        )

    return True, username.lower()


# =========================
# ВАЛИДАЦИЯ TELEGRAM ID
# =========================

def validate_telegram_id(
    value: str,
) -> tuple[bool, str]:

    telegram_id = "".join(value.split())

    if not telegram_id:
        return (
            False,
            "⚠️ Telegram ID не указан.",
        )

    if not re.fullmatch(r"[0-9]+", telegram_id):
        return (
            False,
            "⚠️ Неверный формат Telegram ID.\n\n"
            "Telegram ID должен содержать только цифры.",
        )

    if telegram_id.startswith("0"):
        return (
            False,
            "⚠️ Telegram ID не может начинаться с нуля.",
        )

    if len(telegram_id) < TELEGRAM_ID_MIN_LENGTH:
        return (
            False,
            "⚠️ Недопустимая длина Telegram ID.\n\n"
            f"Минимум: {TELEGRAM_ID_MIN_LENGTH} цифр.",
        )

    if len(telegram_id) > TELEGRAM_ID_MAX_LENGTH:
        return (
            False,
            "⚠️ Недопустимая длина Telegram ID.\n\n"
            f"Максимум: {TELEGRAM_ID_MAX_LENGTH} цифр.",
        )

    return True, telegram_id