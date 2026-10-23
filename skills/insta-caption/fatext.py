#!/usr/bin/env python3
"""
fatext.py - Persian-aware text helpers shared by the insta-* tools.

The original English tools counted words with [A-Za-z]+, so a Persian line
was "one word, 0.4 seconds" and every score built on it was noise. This module
is the fix, and every tool in the pack imports the same copy of it:

  - a word is any run of letters or digits in any script, and a half-space
    (ZWNJ, U+200C) INSIDE a word keeps it one word: «می‌سازی» is one word.
  - Persian (۰-۹) and Arabic-Indic (٠-٩) digits count as numbers, and the
    Persian separators ٬ and ٫ are understood.
  - spoken numbers and money words are recognised in Persian and English.
  - "is this text mostly Persian" is a measurable question, so tools can pick
    the right rules instead of guessing.

Standard library only. Nothing here touches the network.
"""

import re

ZWNJ = "‌"

# Characters that must NEVER be stripped from Persian text. The original
# humanizer deleted every one of these as "invisible watermark characters",
# which turns «می‌سازی» into «میسازی» and «کلمه‌ی» into the broken «کلمهی».
PERSIAN_KEEP = {
    "‌",   # ZERO WIDTH NON-JOINER - the Persian half-space
    "‎",   # LEFT-TO-RIGHT MARK - needed in mixed Persian/English lines
    "‏",   # RIGHT-TO-LEFT MARK
    "؜",   # ARABIC LETTER MARK
}

_MARKS = "ً-ٰٟ"            # harakat and tanvin: «حتماً» stays one word
WORD_RE = re.compile(
    rf"[\w$%٪'’{_MARKS}](?:[\w$%٪'’{_MARKS}‌\-]*[\w$%٪'’{_MARKS}])?")
ARABIC_SCRIPT_RE = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
LATIN_RE = re.compile(r"[A-Za-z]")
SENT_RE = re.compile(r"[^.!?؟…\n]+[.!?؟…]*")

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٬٫", "01234567890123456789,.")


def to_ascii_digits(text):
    """۱۸٬۰۰۰ -> 18,000 so one number regex works for every script."""
    return text.translate(_DIGITS)


def words(text):
    """Spoken words. «۱۸٬۰۰۰» and "$18,000" are one word each, as when said."""
    flat = re.sub(r"(?<=\d),(?=\d)", "", to_ascii_digits(text))
    return WORD_RE.findall(flat)


def sentences(text, min_words=3):
    return [s.strip() for s in SENT_RE.findall(text) if len(words(s)) >= min_words]


def persian_ratio(text):
    """Share of letters that are Arabic-script. 0.0 English, 1.0 pure Persian."""
    fa = len(ARABIC_SCRIPT_RE.findall(text))
    en = len(LATIN_RE.findall(text))
    return fa / (fa + en) if (fa + en) else 0.0


def is_persian(text):
    return persian_ratio(text) >= 0.5


def norm(token):
    """Lower-case, strip quotes and tanvin, Arabic ي/ك -> Persian ی/ک."""
    t = token.lower().strip("'’\"«»")
    t = re.sub(f"[{_MARKS}]", "", t)
    return t.replace("ي", "ی").replace("ك", "ک").replace("ى", "ی")


# Numbers said out loud. «نه» (nine / no) and «یک» (one / a) are left out on
# purpose: they are filler far more often than they are a quantity.
SPOKEN_NUMBERS = {
    # English (from the original pack)
    "zero", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "fifteen", "twenty", "thirty", "forty", "fifty",
    "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "million",
    "billion", "dozen", "half", "twice", "triple",
    # Persian, written and spoken forms
    "صفر", "دو", "سه", "چهار", "پنج", "شش", "شیش", "هفت", "هشت", "ده",
    "یازده", "دوازده", "پونزده", "پانزده", "بیست", "سی", "چهل", "پنجاه",
    "شصت", "هفتاد", "هشتاد", "نود", "صد", "دویست", "سیصد", "پونصد", "پانصد",
    "هزار", "میلیون", "میلیارد", "نصف", "نیم", "دوبرابر", "دو‌برابر",
    "سه‌برابر", "ده‌برابر", "صدبرابر", "دوجین",
}

MONEY_WORDS = {
    "dollars", "dollar", "bucks", "grand", "percent", "cents",
    "millionaire", "billionaire", "revenue", "profit", "salary", "rent",
    "تومن", "تومان", "ریال", "دلار", "یورو", "درصد", "درآمد", "سود", "ضرر",
    "حقوق", "اجاره", "قسط", "رایگان", "مجانی", "پول", "هزینه", "قیمت",
    "میلیونی", "میلیاردی", "هزارتومنی",
}

NUMBER_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?"
    r"|\b\d[\d,]*(?:\.\d+)?\s?"
    r"(?:%|٪|k\b|x\b|hrs?\b|hours?\b|mins?\b|minutes?\b|days?\b|weeks?\b|months?\b|years?\b"
    r"|درصد|ساعت|دقیقه|ثانیه|روز|هفته|ماه|سال|تومن|تومان|میلیون|هزار|میلیارد|برابر)?",
    re.IGNORECASE)

# Persian has no capital letters, so "a proper noun" is only detectable when it
# is written in Latin script: Claude, GitHub, Google Flow.
# Like the original, a capital at the start of a sentence is not a name.
LATIN_NAME_RE = re.compile(r"(?<!^)(?<![.!?؟]\s)(?<![\w.])[A-Z][A-Za-z0-9]{1,}(?:\s[A-Z][A-Za-z0-9]+)?",
                           re.MULTILINE)


def numbers(text):
    return [n.strip() for n in NUMBER_RE.findall(to_ascii_digits(text)) if n.strip()]


# In a Persian line a capitalised Latin word is a name wherever it stands:
# «Strix یه تیم هکره» starts with a name, not with a capitalised sentence.
LATIN_IN_PERSIAN_RE = re.compile(r"(?<![\w.])[A-Z][A-Za-z0-9]+(?:\s[A-Z][A-Za-z0-9]+)?")


def concrete_markers(text):
    """Numbers, Latin-script names, spoken numbers and money words."""
    toks = [norm(w) for w in words(text)]
    spoken = [t for t in toks if t in SPOKEN_NUMBERS or t in MONEY_WORDS]
    name_re = LATIN_IN_PERSIAN_RE if is_persian(text) else LATIN_NAME_RE
    names = set(name_re.findall(text))
    return numbers(text) + sorted(names) + spoken


# Second-person address. «تو» alone is ambiguous in spoken Persian (it also
# means "in": «تو سایت»), so it only counts next to a second-person verb.
YOU_TOKENS = {
    "you", "your", "you're", "youre", "yourself",
    "شما", "خودت", "خودتون", "بهت", "بهتون", "ازت", "ازتون", "برات", "براتون",
    "باهات", "باهاتون", "واست", "واستون", "یادت", "یادتون",
}
ME_TOKENS = {
    "i", "my", "me", "we", "our",
    "من", "ما", "خودم", "خودمون", "بهم", "ازم", "برام", "باهام", "واسم",
}
# The verb prefix needs its half-space («می‌سازی»), otherwise «میلیونی» would
# read as "you". The common no-half-space spellings are listed instead.
_YOU_VERB = re.compile(r"^ن?می‌\S+(?:ی|ین|ید)$")
_ME_VERB = re.compile(r"^ن?می‌\S+(?:م|یم)$")
YOU_LOOSE = {"میخوای", "میتونی", "میدونی", "میسازی", "میکنی", "میری", "میگی",
             "میبینی", "نمیدونی", "نمیتونی", "داری", "نداری", "هستی", "نیستی"}
YOU_PAST = {
    "ساختی", "دیدی", "کردی", "خوردی", "گذاشتی", "داشتی", "رفتی", "گفتی",
    "خوندی", "نوشتی", "زدی", "شدی", "بودی", "خواستی", "تونستی", "فرستادی",
    "گرفتی", "دادی", "باختی", "نساختی", "ندیدی", "نکردی", "نذاشتی",
}


ME_PAST = {
    "ساختم", "کردم", "دیدم", "رفتم", "گفتم", "گشتم", "فهمیدم", "گذاشتم",
    "نوشتم", "خوندم", "زدم", "شدم", "بودم", "داشتم", "خواستم", "تونستم",
    "فرستادم", "گرفتم", "دادم", "باختم", "خوردم", "اومدم", "موندم",
    "نساختم", "نکردم", "ندیدم", "نتونستم", "دارم", "ندارم", "هستم",
}


def is_you(t):
    return t in YOU_TOKENS or t in YOU_LOOSE or t in YOU_PAST or bool(_YOU_VERB.match(t))


def is_me(t):
    return t in ME_TOKENS or t in ME_PAST or bool(_ME_VERB.match(t))


def address(text):
    """'you', 'me' or None - who the line is aimed at."""
    toks = [norm(w) for w in words(text)]
    if any(is_you(t) for t in toks):
        return "you"
    if any(is_me(t) for t in toks):
        return "me"
    return None


# Spoken versus written Persian. A reel is said out loud, and a line in the
# written register («می‌باشد»، «را»، «می‌شود») is the single loudest tell that
# a Persian script came out of a model instead of a mouth.
COLLOQUIAL = {
    "می‌شه", "نمی‌شه", "میشه", "نمیشه", "رو", "یه", "اینو", "اونو", "اون",
    "اونا", "اینا", "اینجوری", "این‌جوری", "اونجوری", "چیه", "کجاست", "دیگه",
    "آره", "اگه", "واسه", "باهاش", "بهش", "ازش", "داره", "نداره", "میاد",
    "نمیاد", "می‌ره", "نمی‌دونم", "خب", "چطوری", "هست", "نیست", "اینه",
    "همینه", "حالا", "یعنی", "بعدش", "اصلاً", "اصلا", "کلی", "یکم",
    "میکنه", "میگه", "میخوام", "میدونم", "نمیدونم", "میره", "میده", "میخواد",
}
FORMAL = {
    "است", "هستند", "می‌باشد", "می‌باشند", "را", "یک", "آن", "آنها", "آن‌ها",
    "می‌شود", "نمی‌شود", "می‌کند", "نمی‌کند", "می‌کنند", "می‌شوند",
    "می‌گوید", "می‌آید", "می‌رود", "می‌دهد", "نمی‌دهد", "می‌دهند",
    "می‌سازد", "می‌سازند", "می‌خواهد", "می‌خواهید", "می‌خواهم", "می‌توان",
    "می‌تواند", "نمی‌تواند", "می‌توانید", "می‌دانید", "می‌دانند", "باشد",
    "باشند", "شوند", "گردید", "نمایید", "می‌نمایید", "لذا", "جهت", "همچنین",
    "بنابراین", "علاوه", "گردد", "می‌گردد", "شوید", "بپردازیم",
    "می‌پردازیم", "باشید", "اینجانب", "اینچنین", "چنانچه",
}
# Spoken third person ends in «ه» or «ن» (می‌کنه، می‌سازن). The written forms
# are listed by hand above, because «می‌شد»، «می‌کرد» and «می‌خواد» also end
# in «د» and are perfectly colloquial.
_COLLOQ_VERB = re.compile(r"^ن?می‌\S+(?:ه|ن)$")
_NOT_COLLOQ = {"می‌توان"}


def register(text):
    """(colloquial hits, formal hits) for Persian text."""
    toks = [norm(w) for w in words(text)]
    col = sum(1 for t in toks
              if t not in _NOT_COLLOQ and (t in COLLOQUIAL or _COLLOQ_VERB.match(t)))
    frm = sum(1 for t in toks if t in FORMAL)
    return col, frm


HASHTAG_RE = re.compile(r"(?:^|\s)(#[\w‌]+)")
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")
