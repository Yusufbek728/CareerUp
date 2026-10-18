"""Small helpers shared by the models, the cities API and the geo seeding code (no Django imports)."""
import re
import unicodedata

LANGUAGE_CODES = ('en', 'ru', 'uz')

# Shown first in country lists, in this order (the countries of the project's audience).
FEATURED_COUNTRY_CODES = ('UZ', 'RU', 'KZ', 'KG', 'TJ', 'TM', 'AZ', 'TR', 'AE', 'DE', 'US', 'GB', 'KR')

# Extra search words for the country combobox (abbreviations and everyday names that CLDR does not have).
COUNTRY_SEARCH_ALIASES = {
    'US': 'USA America США Америка AQSh',
    'GB': 'UK Britain England Англия Angliya',
    'AE': 'UAE Emirates ОАЭ Emirliklar',
    'RU': 'Russian Federation РФ Rossiya',
    'KR': 'Korea Корея Janubiy Koreya',
    'KP': 'Korea Корея Shimoliy Koreya',
    'CZ': 'Czech Чехия',
    'NL': 'Holland Голландия',
    'TR': 'Turkiye Türkiye Turkey Турция',
    'MM': 'Burma Бирма',
    'CI': 'Ivory Coast Кот-д’Ивуар',
    'BY': 'Belarus Беларусь Белоруссия',
    'MK': 'Macedonia Македония',
    'SZ': 'Swaziland Свазиленд',
}

_APOSTROPHES = re.compile("[`'’‘ʻʼ]")


def normalize_search(text):
    """Lower-case, no accents (Koeln ~ Koln, ё ~ е) and no apostrophes (Qo'qon ~ Qoqon ~ Qoʻqon).

    The same algorithm lives in static/mainapp/country-city.js, so the browser and the server agree.
    """
    text = unicodedata.normalize('NFKD', str(text or ''))
    text = ''.join(char for char in text if not unicodedata.combining(char))
    return _APOSTROPHES.sub('', text).lower().strip()


def flag_emoji(code):
    """ISO 3166-1 alpha-2 code -> flag emoji (two regional indicator symbols); '' for anything else."""
    code = (code or '').upper()
    if len(code) != 2 or not code.isascii() or not code.isalpha():
        return ''
    return ''.join(chr(0x1F1E6 + ord(char) - ord('A')) for char in code)


def language_key(language=None):
    """'ru-RU' / 'RU' / None -> 'ru' (only languages we store names for, otherwise 'en')."""
    key = (language or 'en').split('-')[0].split('_')[0].lower()
    return key if key in LANGUAGE_CODES else 'en'


def build_search_text(*names):
    """Normalized names joined with '|': the haystack of the city search (``search_text__contains``)."""
    seen = []
    for name in names:
        normalized = normalize_search(name)
        if normalized and normalized not in seen:
            seen.append(normalized)
    return '|'.join(seen)
