import phonenumbers

from handlers.osint.validation import validate_phone


def test_phone():

    ru_number = phonenumbers.example_number_for_type(
        "RU",
        phonenumbers.PhoneNumberType.MOBILE,
    )

    kz_number = phonenumbers.example_number_for_type(
        "KZ",
        phonenumbers.PhoneNumberType.MOBILE,
    )

    tests = [
        ("Российский номер", phonenumbers.format_number(
            ru_number,
            phonenumbers.PhoneNumberFormat.E164,
        )),
        ("Казахстанский номер", phonenumbers.format_number(
            kz_number,
            phonenumbers.PhoneNumberFormat.E164,
        )),
        ("Пустая строка", ""),
        ("Слишком короткий", "123"),
        ("Буквы", "abcdefgh"),
        ("Неподдерживаемый код", "+12345678901"),
        ("Неверный формат", "++79991234567"),
    ]

    for name, value in tests:
        result = validate_phone(value)
        print(f"{name}: {result}")


if __name__ == "__main__":
    test_phone()