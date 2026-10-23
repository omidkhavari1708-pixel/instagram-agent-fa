#!/usr/bin/env python3
"""
caption.py - lint an Instagram caption and show exactly what the feed shows
before the "... more". Persian and English.

Adapted from Jake Schincariol's instagram-agent-skill (MIT). What changed for
Persian captions:

  - Persian hashtags (#سایت_شخصی) are counted; the original only saw [A-Za-z].
  - the asks are recognised in Persian: «کلمه‌ی X رو کامنت کن»، «دایرکت بده»،
    «سیو کن»، «بفرست برای»، «فالو کن»، «لینک تو بایو»، «ورق بزن».
  - PERSIAN LETTERS: Arabic ي/ك typed instead of Persian ی/ک can make a word
    that looks identical stop matching what people type into search. Flagged.
  - HALF-SPACE: a spaced «می » or «ها» is flagged. Same reason, plus it looks
    careless on a brand caption.
  - the keyword in a keyword ask should be easy to type on a phone: one word,
    and ideally no half-space in it.

Instagram shows about 125 characters before "... more". The exact cut moves
with device and font, so leave a margin rather than engineering to 125.

Usage
  python3 caption.py caption.txt
  python3 caption.py caption.txt --keywords "سایت شخصی,طراحی سایت"
  python3 caption.py caption.txt --json
"""

import argparse
import json
import os
import re
import sys
import textwrap

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fatext as fa  # noqa: E402

LIMIT = 2200             # Instagram's hard caption limit.
TRUNCATE = 125           # Roughly where the feed cuts to "... more".
HASHTAG_LIMIT = 5        # Instagram's cap per post or reel since 18 Dec 2025, down
                         # from 30, announced by @Creators ("using fewer (up to 5)
                         # more targeted hashtags ... can improve both your
                         # content's performance and people's experience").

MENTION_RE = re.compile(r"(?:^|\s)(@[A-Za-z0-9_.]+)")
LINK_RE = re.compile(r"https?://\S+|\bwww\.\S+|\b[a-z0-9-]+\.(?:com|co|io|net|org|ai|app|ir)/\S*",
                     re.IGNORECASE)
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF☀-➿←-⇿️]")

ASKS = [
    (re.compile(r"(?i)\bcomment (?:the word |\")?[A-Z0-9]{2,}\b"), "comment a keyword"),
    (re.compile(r"(?:کلمه‌ی|کلمه\s?ی|کلمه)\s*[«\"]?[^»\"\s]{2,}[»\"]?\s*(?:رو|را)\s*(?:کامنت|بنویس)"),
     "comment a keyword / کلمه رو کامنت کن"),
    (re.compile(r"(?i)\b(?:dm|message) me\b|(?:دایرکت|پیام)\s+(?:بده|بدید|بدین|بفرست|بفرستید)"),
     "DM me / دایرکت"),
    (re.compile(r"(?i)\bsave (?:this|it)\b|(?:ذخیره|سیو)\s*(?:ش|اش)?\s*(?:کن|کنید)"), "save / ذخیره"),
    (re.compile(r"(?i)\bshare (?:this|it)\b|(?:بفرست|بفرستید|بفرستش)\s+(?:برای|واسه)|(?:شیر|شیرش)\s*(?:کن|کنید)"),
     "share / بفرست برای"),
    (re.compile(r"(?i)\bfollow (?:me|for)\b|فالو\s*(?:م\s*)?(?:کن|کنید)"), "follow / فالو"),
    (re.compile(r"(?i)\blink in (?:my )?bio\b|لینک\s+(?:تو|توی|در)\s+بایو"), "link in bio / لینک بایو"),
    (re.compile(r"(?i)\b(?:swipe|tap) (?:through|left|right|for|to)\b|ورق\s+بزن|اسلاید\s+(?:کن|بزن)"),
     "swipe / ورق بزن"),
    (re.compile(r"(?i)\btell me\b|\bwhat would you\b|\bwhich one\b|(?:بهم|بهمون)\s+بگو|کدومش\s*[؟?]|کدوم\s+رو\s+(?:انتخاب|می‌خوای)"),
     "answer a question / سؤال"),
]

FILLER_TAGS = {
    "#viral", "#fyp", "#explore", "#explorepage", "#foryou", "#foryoupage",
    "#trending", "#instagood", "#love", "#follow", "#like4like", "#reels",
    "#reelsinstagram", "#viralreels", "#instadaily",
    "#اکسپلور", "#اکسپلورر", "#فالو", "#لایک", "#ریلز", "#ترند", "#وایرال",
    "#اینستاگرام", "#فالوور", "#کلیپ", "#جذاب",
}

KEYWORD_RE = re.compile(r"(?:کلمه‌ی|کلمه\s?ی|کلمه)\s*[«\"]([^»\"]+)[»\"]")


def visible_window(text, cut):
    flat = text.strip()
    return flat if len(flat) <= cut else flat[:cut]


def render_box(window, truncated, out=sys.stdout, width=52):
    print("\n  WHAT THE FEED SHOWS / چیزی که فید نشون می‌ده", file=out)
    print("  +" + "-" * (width + 2) + "+", file=out)
    lines = []
    for raw in window.split("\n"):
        lines.extend(textwrap.wrap(raw, width) or [""])
    for line in lines[:8]:
        print(f"  | {line:<{width}} |", file=out)
    tail = "... more" if truncated else "(whole caption fits)"
    print("  +" + "-" * (width + 2 - len(tail) - 2) + f" {tail} " + "+", file=out)


def analyse(text, cut=TRUNCATE, keywords=None):
    stripped = text.rstrip().strip()
    chars = len(stripped)
    lines = stripped.split("\n")
    first_line = lines[0].strip() if lines else ""
    tags = fa.HASHTAG_RE.findall(stripped)
    mentions = MENTION_RE.findall(stripped)
    links = LINK_RE.findall(stripped)
    emoji = EMOJI_RE.findall(stripped)
    window = visible_window(stripped, cut)
    truncated = chars > cut
    asks = sorted({name for pattern, name in ASKS if pattern.search(stripped)})
    filler = [t for t in tags if t.lower() in FILLER_TAGS]
    keywords = [k.strip() for k in (keywords or []) if k.strip()]
    persian = fa.is_persian(stripped)

    checks = []

    def add(name, status, detail):
        checks.append({"check": name, "status": status, "detail": detail})

    add("LENGTH", "FAIL" if chars > LIMIT else "PASS",
        f"{chars} / {LIMIT} characters" + (f", {chars - LIMIT} over the limit" if chars > LIMIT else ""))

    if not first_line:
        add("FIRST LINE", "FAIL", "the caption opens on a blank line")
    elif first_line.startswith(("#", "@")):
        add("FIRST LINE", "FAIL", "opens on a hashtag or a mention, the one position worth a sentence")
    elif re.match(r"^\s*(?:سلام|درود|دوستان|عزیزان)", first_line):
        add("FIRST LINE", "FAIL", "opens on a greeting («سلام»). خط اول جای حرف اصلیه، نه سلام")
    elif len(first_line) > cut:
        add("FIRST LINE", "WARN", f"{len(first_line)} characters, so it gets cut at {cut} mid-thought")
    else:
        add("FIRST LINE", "PASS", f"{len(first_line)} characters, lands whole")

    concrete = fa.concrete_markers(window)
    add("HOOK IS CONCRETE", "PASS" if concrete else "WARN",
        f"{len(concrete)} number(s) or name(s) in the visible window"
        + ("" if concrete else " - nothing checkable before the tap / قبل از «بیشتر» عدد یا اسمی نیست"))

    if len(tags) > HASHTAG_LIMIT:
        add("HASHTAGS", "FAIL", f"{len(tags)} tags, over Instagram's cap of {HASHTAG_LIMIT}")
    elif filler:
        add("HASHTAGS", "WARN", f"{len(tags)} tags, {len(filler)} generic ({', '.join(filler[:3])}). "
                                "Those describe nothing / این‌ها چیزی رو توصیف نمی‌کنن")
    else:
        add("HASHTAGS", "PASS", f"{len(tags)} tag(s)" + (f": {' '.join(tags)}" if tags else ""))

    if tags and any(t in window for t in tags):
        add("TAG PLACEMENT", "WARN", "a hashtag is inside the visible window, spending feed space on a label")
    else:
        add("TAG PLACEMENT", "PASS", "tags are below the fold" if tags else "no tags to place")

    add("LINKS", "WARN" if links else "PASS",
        f"{len(links)} link(s) in the caption, and captions are not clickable. Bio or DM"
        if links else "no dead links in the body")

    if len(asks) == 1:
        add("ONE ASK", "PASS", f"one call to action: {asks[0]}")
    elif not asks:
        add("ONE ASK", "WARN", "no call to action. Decide what this post is for")
    else:
        add("ONE ASK", "WARN", f"{len(asks)} asks ({', '.join(asks)}). Two asks is the same as none")

    kw = KEYWORD_RE.findall(stripped)
    if kw:
        word = kw[0].strip()
        if len(fa.words(word)) > 1:
            add("KEYWORD", "WARN", f"«{word}» is more than one word. One word people can type")
        elif fa.ZWNJ in word:
            add("KEYWORD", "WARN", f"«{word}» has a half-space; on many phone keyboards that is hard "
                                   "to type, and a typo breaks keyword auto-replies")
        else:
            add("KEYWORD", "PASS", f"«{word}», one word, easy to type")

    density = len(emoji) * 100 / max(chars, 1)
    add("EMOJI", "WARN" if density > 4 else "PASS",
        f"{len(emoji)} emoji, {density:.1f} per 100 characters" + (" - reads as decoration" if density > 4 else ""))

    if persian:
        arabic = len(re.findall(r"[يكى]", stripped))
        add("PERSIAN LETTERS", "WARN" if arabic else "PASS",
            f"{arabic} Arabic ي/ك/ى. Search terms are typed with Persian ی/ک; run /insta-human to fix"
            if arabic else "Persian ی/ک throughout")
        spaced = len(re.findall(r"(?:^|\s)ن?می (?=[؀-ۿ])", stripped)) + \
            len(re.findall(r"(?<=[؀-ۿ]) (?:ها|های|تر|ترین)(?=[\s.,،!؟?]|$)", stripped))
        add("HALF-SPACE", "WARN" if spaced else "PASS",
            f"{spaced} spaced «می / ها / تر» that should be a half-space" if spaced else "half-spaces in place")

    if keywords:
        low = stripped.lower()
        found = [k for k in keywords if k.lower() in low]
        missing = [k for k in keywords if k.lower() not in low]
        in_window = [k for k in found if k.lower() in window.lower()]
        status = "PASS" if not missing else ("WARN" if found else "FAIL")
        add("SEARCH TERMS", status,
            f"{len(found)}/{len(keywords)} present" + (f", {len(in_window)} in the visible window" if found else "")
            + (f". Missing: {', '.join(missing)}" if missing else ""))

    fails = sum(1 for c in checks if c["status"] == "FAIL")
    warns = sum(1 for c in checks if c["status"] == "WARN")
    verdict = "FIX" if fails else ("REVIEW" if warns else "READY")
    return {
        "characters": chars, "limit": LIMIT, "truncate_at": cut, "language": "fa" if persian else "en",
        "visible": window, "truncated": truncated, "first_line_chars": len(first_line),
        "hashtags": tags, "mentions": mentions, "links": links, "emoji": len(emoji), "asks": asks,
        "checks": checks, "verdict": verdict,
    }


def render(a, out=sys.stdout):
    head = (f"CAPTION LINT  ·  {a['characters']} / {a['limit']} chars  ·  "
            f"{len(a['hashtags'])} hashtags  ·  {len(a['asks'])} ask(s)  ·  {a['language']}")
    print("\n" + head, file=out)
    print("=" * max(len(head), 62), file=out)
    render_box(a["visible"], a["truncated"], out=out)
    print("", file=out)
    for c in a["checks"]:
        print(f"  {c['status']:<5} {c['check']:<17} {c['detail']}", file=out)
    print("-" * max(len(head), 62), file=out)
    print(f"  VERDICT  {a['verdict']}\n", file=out)


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Lint an Instagram caption (Persian + English).")
    ap.add_argument("input", nargs="?", default="-", help="caption file, or - for stdin")
    ap.add_argument("--truncate", type=int, default=TRUNCATE)
    ap.add_argument("--keywords", default="", help="comma-separated terms you want to be found for")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    a = analyse(raw, cut=args.truncate, keywords=args.keywords.split(","))
    if args.json:
        print(json.dumps(a, indent=2, ensure_ascii=False))
    else:
        render(a)
    sys.exit(0 if a["verdict"] == "READY" else 1)


if __name__ == "__main__":
    main()
