"""One-off generator of ``mainapp/data/cities.json.gz``. NOT imported by the app, NOT a runtime dependency.

Usage (dev machine only; geonamescache is installed into a throw-away folder, never into requirements.txt):

    python -m pip install --no-deps --target /tmp/gnc geonamescache
    python mainapp/data/build_geo_data.py /tmp/gnc/geonamescache/data mainapp/data/cities.json.gz

Source: GeoNames "cities5000" (CC BY 4.0) as packaged by geonamescache.
Selection: every city >= 100k inhabitants (>= 50k for CIS countries), all capitals, every city of
Uzbekistan, at least the 8 biggest cities of every country and every city of the legacy seed list.
Names: English = GeoNames name. Russian/Uzbek = manual overrides -> CLDR exemplar cities (Babel) ->
(Russian only) heuristic pick of a Russian-looking alternate name whose transliteration matches a Latin
alternate name -> empty string (the loader falls back to the English name).
"""
import gzip
import importlib.util
import json
import re
import sys
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from babel import Locale

BIG = 100_000
CIS_BIG = 50_000
CIS = {'UZ', 'RU', 'KZ', 'KG', 'TJ', 'TM', 'AZ', 'AM', 'GE', 'BY', 'UA', 'MD'}
# Cyrillic is the local script there, so a Cyrillic alternate name is as likely Serbian/Bulgarian as Russian.
LOCAL_CYRILLIC = {'BG', 'RS', 'MK', 'ME', 'BA', 'MN'}
MIN_PER_COUNTRY = 8

# GeoNames "cities" that are city districts, not cities (no feature class in the source to filter on).
NOT_CITIES = {
    'UZ': {'yunusobod', 'chilanzar', 'sergeli', 'bektemir', 'tashkentoblast'},
    'US': {'brooklyn', 'queens', 'manhattan', 'thebronx', 'statenisland'},
    'UA': {'saltivka', 'desna'},
}
# GeoNames primary names that are not the common English name.
NAME_FIX = {('KG', 'Manas'): 'Jalal-Abad'}
UZ_SUFFIXES = (' Shahri', ' Shaharchasi', ' Shahar', ' Tumani', " Qishlog’i", " Qishlog'i")

RU_LETTERS = set('абвгдеёжзийклмнопрстуфхцчшщъыьэюя')
TRANSLIT = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюя', [
    'a', 'b', 'v', 'g', 'd', 'e', 'e', 'zh', 'z', 'i', 'y', 'k', 'l', 'm', 'n', 'o', 'p', 'r', 's', 't', 'u', 'f',
    'kh', 'ts', 'ch', 'sh', 'shch', '', 'y', '', 'e', 'yu', 'ya']))


def fold(text):
    """Lower-case, strip accents and punctuation: used only to compare names."""
    text = unicodedata.normalize('NFKD', text.lower())
    return re.sub(r'[^a-z0-9]', '', ''.join(c for c in text if not unicodedata.combining(c)))


def is_russian_looking(name):
    letters = [c for c in name.lower() if c.isalpha()]
    return bool(letters) and all(c in RU_LETTERS for c in letters)


def translit(name):
    return ''.join(TRANSLIT.get(c, c if c in " -" else '') for c in name.lower())


RU_NAME_RE = re.compile(r'^[а-яё]+(?:[ -][а-яё]+)*$')


def pick_russian(city, country):
    """Best Russian-looking alternate name or None.

    GeoNames alternate names carry no language tag, so a candidate must (a) be plain Russian Cyrillic with the
    same number of words as the English name, (b) transliterate close to the English name (>= 0.95, or 0.72 for
    the CIS where Russian forms differ more: Kyiv -> Kiev) and (c) match some Latin alternate name (>= 0.9).
    Anything less certain stays empty and falls back to English.
    """
    primary = fold(city['name'])
    words = len(city['name'].split())
    latin = {fold(n) for n in city['alternatenames'] if n.isascii() and len(n.split()) == words}
    latin.discard('')
    min_name_score = 0.72 if country in CIS else 0.95
    best, best_score = None, 0.0
    for candidate in city['alternatenames']:
        if not RU_NAME_RE.match(candidate.lower()) or len(candidate.split()) != words:
            continue
        folded = fold(translit(candidate))
        name_score = SequenceMatcher(None, folded, primary).ratio()
        alt_score = max((SequenceMatcher(None, folded, item).ratio() for item in latin), default=0)
        if name_score < min_name_score or alt_score < 0.9:
            continue
        score = 0.6 * name_score + 0.4 * alt_score
        if score > best_score + 1e-9:
            best, best_score = candidate, score
    return best


# (country, fold(English or alternate Latin name)) -> (russian, uzbek-latin or None). Verified by hand.
MANUAL = {
    'UZ': {
        'Tashkent': ('Ташкент', 'Toshkent'), 'Samarkand': ('Самарканд', 'Samarqand'),
        'Bukhara': ('Бухара', 'Buxoro'), 'Andijan': ('Андижан', 'Andijon'),
        'Namangan': ('Наманган', 'Namangan'), 'Fergana': ('Фергана', "Farg'ona"),
        'Nukus': ('Нукус', 'Nukus'), 'Qarshi': ('Карши', 'Qarshi'), 'Navoiy': ('Навои', 'Navoiy'),
        'Urgench': ('Ургенч', 'Urganch'), 'Termez': ('Термез', 'Termiz'), 'Jizzax': ('Джизак', 'Jizzax'),
        'Gulistan': ('Гулистан', 'Guliston'), 'Kokand': ('Коканд', "Qo'qon"),
        'Margilan': ('Маргилан', "Marg'ilon"), 'Chirchiq': ('Чирчик', 'Chirchiq'),
        'Angren': ('Ангрен', 'Angren'), 'Olmaliq': ('Алмалык', 'Olmaliq'), 'Bekobod': ('Бекабад', 'Bekobod'),
        'Shahrisabz': ('Шахрисабз', 'Shahrisabz'), 'Khiva': ('Хива', 'Xiva'), 'Denov': ('Денау', 'Denov'),
        'Yangiyer': ('Янгиер', 'Yangiyer'), 'Zarafshon': ('Зарафшан', 'Zarafshon'),
        'Kogon': ('Каган', 'Kogon'), 'Asaka': ('Асака', 'Asaka'), 'Quvasoy': ('Кувасай', 'Quvasoy'),
        'Shirin': ('Ширин', 'Shirin'), 'Yangiyul': ('Янгиюль', "Yangiyo'l"), 'Beruniy': ('Беруни', 'Beruniy'),
        'Chust': ('Чуст', 'Chust'), 'Pop': ('Пап', 'Pop'), 'Angor': ('Ангор', 'Angor'),
        'Qoqon': ('Коканд', "Qo'qon"), 'Marg`ilon': ('Маргилан', "Marg'ilon"),
        'Khujayli': ('Ходжейли', 'Xo\'jayli'), 'Kungrad': ('Кунград', "Qo'ng'irot"),
        'Shumanay': ('Шуманай', 'Shumanay'), 'Turtkul': ('Турткуль', "To'rtko'l"),
        'Chimboy': ('Чимбай', 'Chimboy'), 'Gazli': ('Газли', 'Gazli'), 'Kitob': ('Китаб', 'Kitob'),
        'Muborak': ('Мубарек', 'Muborak'), 'Shofirkon': ('Шафиркан', 'Shofirkon'),
        'Gijduvon': ('Гиждуван', 'G\'ijduvon'), 'Karakul': ('Каракуль', 'Qorako\'l'),
        'Urgut': ('Ургут', 'Urgut'), 'Payshanba': ('Пайшанба', 'Payshanba'),
        'Nurota': ('Нурата', 'Nurota'), 'Zomin': ('Заамин', 'Zomin'), 'Bulungur': ('Булунгур', "Bulung'ur"),
        'Jomboy': ('Джамбай', 'Jomboy'), 'Kattaqo`rg`on': ('Каттакурган', "Kattaqo'rg'on"),
        'Kattakurgan': ('Каттакурган', "Kattaqo'rg'on"), 'Parkent': ('Паркент', 'Parkent'),
        'Ohangaron': ('Ахангаран', 'Ohangaron'), 'Nurafshon': ('Нурафшан', 'Nurafshon'),
        'Gagarin': ('Гагарин', 'Gagarin'), 'Yaypan': ('Яйпан', 'Yaypan'), 'Rishton': ('Риштан', 'Rishton'),
        'Uchqurghon': ('Учкурган', "Uchqo'rg'on"), 'Uychi': ('Уйчи', 'Uychi'), 'Konibodom': ('Канибадам', 'Konibodom'),
        'Bagat': ('Багат', "Bog'ot"), 'Khonqa': ('Ханка', 'Xonqa'), 'Hazorasp': ('Хазарасп', 'Hazorasp'),
        'Beshariq': ('Бешарык', None), 'Shahrixon': ('Шахрихан', None), 'Kosonsoy': ('Касансай', None),
        'Paxtaobod': ('Пахтаабад', None), 'Chortoq': ('Чартак', None), 'Vobkent': ('Вабкент', None),
        'Romitan': ('Ромитан', None), 'Olot': ('Алат', None), 'Ishtixon': ('Иштыхан', None),
        'Kegeyli': ('Кегейли', None), 'Payariq': ('Пайарык', None), 'Qorovulbozor': ('Каравулбазар', None),
        'Yangiqorgon': ('Янгикурган', None), 'Torqaorgon': ('Туракурган', None), 'Chiroqchi': ('Чиракчи', None),
        'Boka': ('Бука', None), 'Qoshkopir': ('Кошкупыр', None), 'Moynoq': ('Муйнак', None),
        'Hamza': ('Хамза', None), 'Oltiariq': ('Алтыарык', None), 'Shorchi': ('Шурчи', None),
        'Shovot': ('Шават', None), 'Uchkuduk': ('Учкудук', None), 'Jalolquduq': ('Джалалкудук', None),
        'Paxtakor': ('Пахтакор', None), 'Xojaobod': ('Ходжаабад', None), 'Toshloq': ('Ташлак', None),
        'Juma': ('Джума', None), 'Chelak': ('Челек', None), 'Druzhba': ('Дружба', None),
        'Dardoq': ('Дардак', None), 'Oltinkol': ('Алтынкуль', None), 'Toshbuloq': ('Ташбулак', None),
        'Qiziltepa': ('Кызылтепа', None), 'Oqqorgon': ('Аккурган', None), 'Nishon': ('Нишан', None),
        'Gozgon': ('Газган', None), 'Dostlik': ('Дустлик', None), 'Qorasuv': ('Карасу', None),
        'Hazratishoh': ('Хазратишох', None), 'Galaosiyo': ('Галляарал', None),
        'Tashkent Oblast': ('Ташкентская область', 'Toshkent viloyati'),
    },
    'RU': {
        'Saint Petersburg': ('Санкт-Петербург', None), 'Nizhniy Novgorod': ('Нижний Новгород', None),
        'Nizhniy Tagil': ('Нижний Тагил', None), 'Rostov-na-Donu': ('Ростов-на-Дону', None),
        'Yekaterinburg': ('Екатеринбург', None), 'Moscow': ('Москва', None),
    },
    'KZ': {'Astana': ('Астана', None), 'Almaty': ('Алматы', None), 'Shymkent': ('Шымкент', None),
           'Karaganda': ('Караганда', None), 'Aktobe': ('Актобе', 'Aqto\'be'),
           'Taraz': ('Тараз', None), 'Pavlodar': ('Павлодар', None), 'Atyrau': ('Атырау', None)},
    'KG': {'Bishkek': ('Бишкек', None), 'Osh': ('Ош', None), 'Jalal-Abad': ('Джалал-Абад', None),
           'Karakol': ('Каракол', 'Qorako\'l'), 'Tokmok': ('Токмок', None), 'Naryn': ('Нарын', None)},
    'TJ': {'Dushanbe': ('Душанбе', None), 'Khujand': ('Худжанд', None),
           'Bokhtar': ('Бохтар', None), 'Kulob': ('Куляб', None),
           'Istaravshan': ('Истаравшан', None), 'Kurgan-Tyube': ('Курган-Тюбе', 'Qo\'rg\'ontepa')},
    'TM': {'Ashgabat': ('Ашхабад', None), 'Turkmenabat': ('Туркменабат', None),
           'Dashoguz': ('Дашогуз', None), 'Mary': ('Мары', None), 'Turkmenbasy': ('Туркменбаши', None)},
    'AZ': {'Baku': ('Баку', None), 'Ganja': ('Гянджа', None), 'Sumqayit': ('Сумгаит', None),
           'Mingelchaur': ('Мингечевир', None), 'Shirvan': ('Ширван', None)},
    'AM': {'Yerevan': ('Ереван', None)}, 'GE': {'Tbilisi': ('Тбилиси', None)},
    'BY': {'Minsk': ('Минск', None)},
    'UA': {'Kyiv': ('Киев', None), 'Kharkiv': ('Харьков', None), 'Odesa': ('Одесса', None),
           'Dnipro': ('Днепр', None), 'Donetsk': ('Донецк', None), 'Lviv': ('Львов', None),
           'Zaporizhzhya': ('Запорожье', None), 'Kryvyy Rih': ('Кривой Рог', None),
           'Sevastopol': ('Севастополь', None), 'Mykolayiv': ('Николаев', None), 'Vinnytsya': ('Винница', None),
           'Luhansk': ('Луганск', None), 'Poltava': ('Полтава', None), 'Chernihiv': ('Чернигов', None),
           'Cherkasy': ('Черкассы', None), 'Sumy': ('Сумы', None), 'Zhytomyr': ('Житомир', None),
           'Khmelnytskyi': ('Хмельницкий', None), 'Rivne': ('Ровно', None),
           'Ivano-Frankivsk': ('Ивано-Франковск', None), 'Ternopil': ('Тернополь', None), 'Lutsk': ('Луцк', None),
           'Uzhhorod': ('Ужгород', None), 'Chernivtsi': ('Черновцы', None),
           'Kropyvnytskyi': ('Кропивницкий', None), 'Kherson': ('Херсон', None),
           'Kramatorsk': ('Краматорск', None), 'Mariupol': ('Мариуполь', None)},
    'MD': {'Chisinau': ('Кишинёв', None)},
    'US': {'New York City': ('Нью-Йорк', None), 'Los Angeles': ('Лос-Анджелес', None),
           'San Francisco': ('Сан-Франциско', None), 'Washington, D.C.': ('Вашингтон', None),
           'Seattle': ('Сиэтл', None), 'Chicago': ('Чикаго', None), 'Houston': ('Хьюстон', None),
           'Boston': ('Бостон', None), 'Miami': ('Майами', None)},
    'DE': {'Cologne': ('Кёльн', None), 'Frankfurt am Main': ('Франкфурт-на-Майне', None),
           'Munich': ('Мюнхен', None), 'Dusseldorf': ('Дюссельдорф', None), 'Hamburg': ('Гамбург', None),
           'Stuttgart': ('Штутгарт', None), 'Leipzig': ('Лейпциг', None), 'Berlin': ('Берлин', None)},
    'TR': {'Istanbul': ('Стамбул', None)},
    'AE': {'Abu Dhabi': ('Абу-Даби', None), 'Ras Al Khaimah': ('Рас-эль-Хайма', None),
           'Al Ain': ('Эль-Айн', None), 'Dubai': ('Дубай', None), 'Sharjah': ('Шарджа', None),
           'Ajman': ('Аджман', None)},
    'KR': {'Seoul': ('Сеул', None), 'Busan': ('Пусан', None), 'Incheon': ('Инчхон', None),
           'Daegu': ('Тэгу', None), 'Daejeon': ('Тэджон', None), 'Gwangju': ('Кванджу', None)},
    'GB': {'London': ('Лондон', None), 'Manchester': ('Манчестер', None), 'Birmingham': ('Бирмингем', None),
           'Edinburgh': ('Эдинбург', None), 'Glasgow': ('Глазго', None), 'Liverpool': ('Ливерпуль', None)},
    'BG': {'Sofia': ('София', None)}, 'RS': {'Belgrade': ('Белград', None)},
    'MK': {'Skopje': ('Скопье', None)}, 'ME': {'Podgorica': ('Подгорица', None)},
    'BA': {'Sarajevo': ('Сараево', None)}, 'MN': {'Ulaanbaatar': ('Улан-Батор', None)},
}


# Russian names of well-known cities (country code|English name|Russian): used when CLDR has none.
WORLD_RU_TABLE = """
US|Philadelphia|Филадельфия
US|Jacksonville|Джэксонвилл
US|Fort Worth|Форт-Уэрт
US|San Jose|Сан-Хосе
US|Austin|Остин
US|Columbus|Колумбус
US|Charlotte|Шарлотт
US|Indianapolis|Индианаполис
US|Seattle|Сиэтл
US|Denver|Денвер
US|Washington|Вашингтон
US|Boston|Бостон
US|Nashville|Нашвилл
US|Detroit|Детройт
US|Portland|Портленд
US|Las Vegas|Лас-Вегас
US|Memphis|Мемфис
US|Baltimore|Балтимор
US|Milwaukee|Милуоки
US|Atlanta|Атланта
US|Miami|Майами
US|Minneapolis|Миннеаполис
US|New Orleans|Новый Орлеан
US|San Diego|Сан-Диего
US|San Antonio|Сан-Антонио
US|Dallas|Даллас
US|Phoenix|Финикс
US|Honolulu|Гонолулу
US|Pittsburgh|Питтсбург
US|Cleveland|Кливленд
US|Sacramento|Сакраменто
US|Kansas City|Канзас-Сити
US|Orlando|Орландо
US|Tampa|Тампа
US|Oakland|Окленд
US|Cincinnati|Цинциннати
US|St. Louis|Сент-Луис
US|Salt Lake City|Солт-Лейк-Сити
US|Anchorage|Анкоридж
GB|Leeds|Лидс
GB|Cardiff|Кардифф
GB|Coventry|Ковентри
GB|Leicester|Лестер
GB|Nottingham|Ноттингем
GB|Newcastle upon Tyne|Ньюкасл-апон-Тайн
GB|Southampton|Саутгемптон
GB|Belfast|Белфаст
GB|Bristol|Бристоль
GB|Sheffield|Шеффилд
GB|Bradford|Брэдфорд
GB|Oxford|Оксфорд
GB|Cambridge|Кембридж
DE|Nuremberg|Нюрнберг
DE|Essen|Эссен
DE|Dresden|Дрезден
DE|Duisburg|Дуйсбург
DE|Hannover|Ганновер
DE|Bochum|Бохум
DE|Wuppertal|Вупперталь
DE|Bielefeld|Билефельд
DE|Bonn|Бонн
DE|Munster|Мюнстер
DE|Karlsruhe|Карлсруэ
DE|Mannheim|Мангейм
DE|Augsburg|Аугсбург
DE|Wiesbaden|Висбаден
DE|Aachen|Аахен
DE|Kiel|Киль
DE|Freiburg im Breisgau|Фрайбург-им-Брайсгау
DE|Rostock|Росток
DE|Mainz|Майнц
DE|Lubeck|Любек
DE|Erfurt|Эрфурт
DE|Potsdam|Потсдам
FR|Marseille|Марсель
FR|Lyon|Лион
FR|Toulouse|Тулуза
FR|Nice|Ницца
FR|Nantes|Нант
FR|Bordeaux|Бордо
FR|Montpellier|Монпелье
FR|Lille|Лилль
FR|Rennes|Ренн
FR|Reims|Реймс
FR|Le Havre|Гавр
FR|Strasbourg|Страсбург
FR|Grenoble|Гренобль
FR|Dijon|Дижон
FR|Toulon|Тулон
ES|Madrid|Мадрид
ES|Barcelona|Барселона
ES|Valencia|Валенсия
ES|Seville|Севилья
ES|Zaragoza|Сарагоса
ES|Malaga|Малага
ES|Bilbao|Бильбао
IT|Rome|Рим
IT|Milan|Милан
IT|Naples|Неаполь
IT|Turin|Турин
IT|Palermo|Палермо
IT|Genoa|Генуя
IT|Bologna|Болонья
IT|Florence|Флоренция
IT|Venice|Венеция
IT|Verona|Верона
PT|Lisbon|Лиссабон
PT|Porto|Порту
NL|Amsterdam|Амстердам
NL|Rotterdam|Роттердам
NL|The Hague|Гаага
NL|Utrecht|Утрехт
BE|Brussels|Брюссель
BE|Antwerp|Антверпен
AT|Vienna|Вена
CH|Zurich|Цюрих
CH|Geneva|Женева
CH|Bern|Берн
SE|Stockholm|Стокгольм
SE|Gothenburg|Гётеборг
NO|Oslo|Осло
DK|Copenhagen|Копенгаген
FI|Helsinki|Хельсинки
PL|Warsaw|Варшава
PL|Krakow|Краков
PL|Lodz|Лодзь
PL|Wroclaw|Вроцлав
PL|Poznan|Познань
PL|Gdansk|Гданьск
CZ|Prague|Прага
CZ|Brno|Брно
SK|Bratislava|Братислава
HU|Budapest|Будапешт
RO|Bucharest|Бухарест
GR|Athens|Афины
GR|Thessaloniki|Салоники
IE|Dublin|Дублин
LT|Vilnius|Вильнюс
LV|Riga|Рига
EE|Tallinn|Таллин
TR|Izmir|Измир
TR|Bursa|Бурса
TR|Eskisehir|Эскишехир
CN|Beijing|Пекин
CN|Shanghai|Шанхай
CN|Guangzhou|Гуанчжоу
CN|Shenzhen|Шэньчжэнь
CN|Chengdu|Чэнду
CN|Tianjin|Тяньцзинь
CN|Wuhan|Ухань
CN|Hangzhou|Ханчжоу
CN|Nanjing|Нанкин
CN|Chongqing|Чунцин
CN|Xi'an|Сиань
CN|Harbin|Харбин
CN|Shenyang|Шэньян
CN|Urumqi|Урумчи
CN|Kunming|Куньмин
CN|Qingdao|Циндао
CN|Dalian|Далянь
IN|Delhi|Дели
IN|New Delhi|Нью-Дели
IN|Mumbai|Мумбаи
IN|Bengaluru|Бангалор
IN|Hyderabad|Хайдарабад
IN|Chennai|Ченнаи
IN|Kolkata|Калькутта
IN|Ahmedabad|Ахмедабад
IN|Pune|Пуна
IN|Jaipur|Джайпур
IN|Lucknow|Лакхнау
JP|Tokyo|Токио
JP|Osaka|Осака
JP|Yokohama|Иокогама
JP|Nagoya|Нагоя
JP|Sapporo|Саппоро
JP|Kyoto|Киото
JP|Kobe|Кобе
JP|Fukuoka|Фукуока
JP|Hiroshima|Хиросима
KR|Suwon|Сувон
KR|Ulsan|Ульсан
SA|Riyadh|Эр-Рияд
SA|Jeddah|Джидда
SA|Mecca|Мекка
SA|Medina|Медина
QA|Doha|Доха
KW|Kuwait City|Эль-Кувейт
OM|Muscat|Маскат
BH|Manama|Манама
IR|Tehran|Тегеран
IR|Mashhad|Мешхед
IR|Isfahan|Исфахан
IR|Shiraz|Шираз
IQ|Baghdad|Багдад
IL|Jerusalem|Иерусалим
IL|Tel Aviv|Тель-Авив
JO|Amman|Амман
LB|Beirut|Бейрут
SY|Damascus|Дамаск
EG|Cairo|Каир
EG|Alexandria|Александрия
EG|Giza|Гиза
MA|Casablanca|Касабланка
MA|Rabat|Рабат
DZ|Algiers|Алжир
TN|Tunis|Тунис
NG|Lagos|Лагос
NG|Abuja|Абуджа
ZA|Johannesburg|Йоханнесбург
ZA|Cape Town|Кейптаун
ZA|Pretoria|Претория
KE|Nairobi|Найроби
ET|Addis Ababa|Аддис-Абеба
BR|Sao Paulo|Сан-Паулу
BR|Rio de Janeiro|Рио-де-Жанейро
BR|Brasilia|Бразилиа
BR|Salvador|Салвадор
AR|Buenos Aires|Буэнос-Айрес
CL|Santiago|Сантьяго
CO|Bogota|Богота
PE|Lima|Лима
MX|Mexico City|Мехико
MX|Guadalajara|Гвадалахара
MX|Monterrey|Монтеррей
CU|Havana|Гавана
CA|Toronto|Торонто
CA|Montreal|Монреаль
CA|Vancouver|Ванкувер
CA|Ottawa|Оттава
CA|Calgary|Калгари
AU|Sydney|Сидней
AU|Melbourne|Мельбурн
AU|Brisbane|Брисбен
AU|Perth|Перт
AU|Canberra|Канберра
NZ|Auckland|Окленд
NZ|Wellington|Веллингтон
TH|Bangkok|Бангкок
VN|Hanoi|Ханой
VN|Ho Chi Minh City|Хошимин
ID|Jakarta|Джакарта
PH|Manila|Манила
MY|Kuala Lumpur|Куала-Лумпур
SG|Singapore|Сингапур
PK|Karachi|Карачи
PK|Lahore|Лахор
PK|Islamabad|Исламабад
BD|Dhaka|Дакка
AF|Kabul|Кабул
NP|Kathmandu|Катманду
MN|Ulaanbaatar|Улан-Батор
KZ|Karagandy|Караганда
"""
WORLD_RU = {}
for _line in WORLD_RU_TABLE.strip().splitlines():
    _code, _name, _ru = _line.split('|')
    WORLD_RU[(_code, fold(_name))] = _ru


def clean_name(name, country):
    """Uzbek GeoNames names: drop ' Shahri' style suffixes, unify apostrophes (o‘, g‘ -> oʻ, gʻ), ŭ -> oʻ."""
    name = NAME_FIX.get((country, name), name)
    if country != 'UZ':
        return name.replace('ŭ', 'u').replace('Ŭ', 'U')
    for suffix in UZ_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    name = name.replace('ŭ', 'oʻ').replace('Ŭ', 'Oʻ')
    return re.sub(r"(?<=[A-Za-z])[’‘ʼ`'](?=[A-Za-z])", 'ʻ', name)


def load_legacy():
    path = Path(__file__).resolve().parent.parent / 'geo_data.py'
    spec = importlib.util.spec_from_file_location('legacy_geo_data', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {code: cities for _name, code, cities in module.COUNTRIES}


def build(source_dir, output):
    source_dir = Path(source_dir)
    countries = json.loads((source_dir / 'countries.json').read_text(encoding='utf-8'))
    raw = json.loads((source_dir / 'cities5000.json').read_text(encoding='utf-8'))

    ru_locale, uz_locale = Locale('ru'), Locale('uz')
    valid = {c for c in countries if c in ru_locale.territories and c in uz_locale.territories}
    cldr = defaultdict(dict)  # fold(exemplar city) -> {tz id: (ru, uz)}
    for tz_id, data in ru_locale.time_zones.items():
        if 'city' in data and '/' in tz_id:
            ru_city = data['city']
            uz_city = uz_locale.time_zones.get(tz_id, {}).get('city')
            cldr[fold(tz_id.split('/')[-1].replace('_', ' '))][tz_id] = (ru_city, uz_city)

    by_country = defaultdict(list)
    for city in raw.values():
        if city['countrycode'] in valid:
            by_country[city['countrycode']].append(city)

    legacy = load_legacy()
    selected = {}
    stats = {'legacy_unmatched': []}

    def names_of(city, code=None):
        names = [city['name'], clean_name(city['name'], code), *city['alternatenames']]
        return {fold(n) for n in names if n.isascii() and fold(n)}

    for code, cities in by_country.items():
        cities.sort(key=lambda c: -c['population'])
        threshold = CIS_BIG if code in CIS else BIG
        chosen = [c for c in cities if c['population'] >= threshold]
        chosen += [c for c in cities[:MIN_PER_COUNTRY] if c not in chosen]
        if code == 'UZ':
            chosen = list(cities)
        capital = fold(countries[code].get('capital') or '')
        if capital:
            for city in cities:
                if capital in names_of(city):
                    if city not in chosen:
                        chosen.append(city)
                    break
        chosen = [
            c for c in chosen
            if fold(c['name']) not in NOT_CITIES.get(code, ()) and not re.search(r'\d', c['name'])
        ]
        selected[code] = chosen

    resolved = {}
    for code, cities in selected.items():
        manual = {fold(k): v for k, v in MANUAL.get(code, {}).items()}
        for city in cities:
            ru = uz = None
            for key in names_of(city, code):
                if key in manual:
                    ru, uz = manual[key]
                    break
            hits = cldr.get(fold(city['name']))
            if hits and city['timezone'] in hits:
                cldr_ru, cldr_uz = hits[city['timezone']]
                ru, uz = ru or cldr_ru, uz or cldr_uz
            if ru is None:
                for key in names_of(city, code):
                    if (code, key) in WORLD_RU:
                        ru = WORLD_RU[(code, key)]
                        break
            if ru is None and code not in LOCAL_CYRILLIC:
                ru = pick_russian(city, code)
            resolved[city['geonameid']] = (ru or '', uz or '')

    # Legacy cities must stay (listings may reference them): add the ones the filters dropped.
    for code, legacy_names in legacy.items():
        for legacy_name in legacy_names:
            found = [c for c in selected.get(code, []) if resolved[c['geonameid']][0] == legacy_name]
            if not found:
                for city in by_country.get(code, []):
                    candidate = resolved.get(city['geonameid'], (None,))[0] or pick_russian(city, code)
                    if candidate == legacy_name or legacy_name in city['alternatenames']:
                        selected[code].append(city)
                        resolved[city['geonameid']] = (legacy_name, resolved.get(city['geonameid'], ('', ''))[1])
                        found = [city]
                        break
            if not found:
                stats['legacy_unmatched'].append((code, legacy_name))

    out_cities = {}
    for code, cities in sorted(selected.items()):
        seen, rows = {}, []
        unique = {c['geonameid']: c for c in cities}.values()
        for city in sorted(unique, key=lambda c: (-c['population'], c['name'])):
            name = clean_name(city['name'], code)
            if name in seen:
                if code != 'US':  # the admin1 code is only readable for US states ("Springfield (MA)")
                    continue
                name = f"{name} ({city.get('admin1code') or city['geonameid']})"
            seen[name] = True
            ru, uz = resolved[city['geonameid']]
            uz = clean_name(uz, code) if uz else uz
            if name.endswith(')') and ' (' in name:  # keep "Springfield (MA)" style disambiguation in every language
                suffix = name[name.rindex(' ('):]
                ru, uz = (ru + suffix if ru else ''), (uz + suffix if uz else '')
            rows.append([city['geonameid'], name, '' if ru == name else ru, '' if uz == name else uz, city['population']])
        out_cities[code] = rows

    payload = {
        'source': 'GeoNames cities5000 via geonamescache (CC BY 4.0)',
        'countries': sorted(valid),
        'capitals': {code: countries[code].get('capital') or '' for code in sorted(valid)},
        'cities': out_cities,
    }
    raw_json = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    with gzip.GzipFile(output, 'wb', compresslevel=9, mtime=0) as fh:  # mtime=0: reproducible bytes
        fh.write(raw_json)
    total = sum(len(v) for v in out_cities.values())
    print(f'countries={len(valid)} cities={total} bytes={Path(output).stat().st_size}')
    print('legacy unmatched:', stats['legacy_unmatched'])
    return payload


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    build(sys.argv[1], sys.argv[2])
