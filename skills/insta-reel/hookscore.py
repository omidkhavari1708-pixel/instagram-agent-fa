#!/usr/bin/env python3
"""
hookscore.py - score the first line of a Reel on the five things strong hooks
have in common, and rank a batch of them. Persian and English.

Adapted from Jake Schincariol's instagram-agent-skill (MIT). The original only
counted Latin letters, so a Persian hook scored as "1 word, 0.4s" and came
back WEAK no matter what it said. This version reads Persian: half-space words,
Persian digits, spoken Persian numbers and money words, Persian tension words,
second-person verbs («می‌سازی»، «ساختی») and the Persian greetings and
preambles that waste the first second.

What this is:  five local heuristics computed from the text alone - a length
you can say in under three seconds, a concrete marker, something at stake, the
payload at the front, and a viewer to aim it at.

What this is NOT:  a view predictor. The original was tested on 74 English
short-form hooks: good at telling a real hook from a deliberately bad one
(AUC 0.83), close to a coin flip at telling a creator's hits from their misses
(AUC 0.56). The Persian rules have NOT been validated on a Persian corpus yet;
treat the number as a checklist, and trust your retention graph over it.

Usage
  python3 hookscore.py hooks.txt              # one hook per line, ranked
  python3 hookscore.py --hook "ببین… سایتی که با AI ساختی، خطرناک‌ترین درش تو کدش نیست."
  python3 hookscore.py hooks.txt --json
"""

import argparse
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fatext as fa  # noqa: E402

# Words that put something on the line, in both languages.
STAKES = {
    # English (original pack)
    "stop", "never", "wrong", "mistake", "mistakes", "lost", "lose", "losing",
    "cost", "costs", "broke", "broken", "failed", "failure", "fail", "nobody",
    "no", "not", "don't", "dont", "doesn't", "didn't", "can't", "won't",
    "quit", "quitting", "fired", "deleted", "delete", "killed", "kills", "kill",
    "replaced", "replaces", "cut", "beat", "free", "paid", "charged", "hired",
    "saved", "first", "banned", "illegal", "worst", "hate", "hated", "wasted",
    "waste", "scam", "lie", "lied", "lying", "truth", "secret", "hidden",
    "stole", "stolen", "before", "until", "instead", "but", "except", "unless",
    "problem", "risk", "danger", "warning", "regret", "wish", "should",
    "shouldn't", "still", "already", "only", "without", "versus", "vs", "actually",
    # Persian
    "ولی", "اما", "هیچ‌وقت", "هیچوقت", "هرگز", "هیچ‌کس", "هیچکس", "هیچ‌کی",
    "هیچکی", "هیچی", "اشتباه", "غلط", "ضرر", "باختم", "باختی", "خراب",
    "شکست", "فیلتر", "بلاک", "ریپورت", "هک", "خطر", "خطرناک", "خطرناک‌ترین",
    "ممنوع", "دروغ", "راز", "حقیقت", "مخفی", "قبل", "به‌جای", "بجای", "فقط",
    "بدون", "نکن", "نکنید", "نذار", "نزن", "نده", "دیگه", "هنوز", "حتی",
    "اخراج", "پاک", "حذف", "کلاهبرداری", "گرون", "مجانی", "رایگان", "پول",
    "هزینه", "جریمه", "ترس", "نگران", "مشکل", "گیر", "سوخت", "سوختم",
    "بدترین", "تنها", "بالاخره", "نیاز", "لازم", "صفر",
}

WEAK_OPENERS = [
    # English
    "so", "ok", "okay", "hey", "hi", "hello", "guys", "yo", "alright",
    "welcome", "today", "basically", "honestly", "look", "listen", "um",
    "just", "let", "lets", "let's", "i wanted", "i want", "one of",
    "have you", "did you", "do you", "are you", "in this", "in today",
    "the thing", "a lot", "there is", "there are", "this is", "it is",
    "as a", "when it", "if you've", "you know",
    # Persian. «ببین» is deliberately NOT here: «ببین» + the claim in one
    # breath is a strong Persian opener. «ببین» followed by nothing is caught
    # by the payload check instead.
    "سلام", "درود", "خب", "خوب", "دوستان", "عزیزان", "رفقا", "بچه‌ها",
    "امروز", "توی این", "تو این", "در این", "قراره", "می‌خوام", "میخوام",
    "بیاید", "بیایید", "اول از", "راستش", "یه سوال", "یه سؤال", "تا حالا",
    "آیا", "شاید", "یه چیزی", "همونطور", "همان‌طور", "اینجا", "خیلی‌ها",
]

IMPERATIVES = {
    "stop", "steal", "copy", "delete", "try", "watch", "read", "save",
    "use", "build", "make", "write", "send", "take", "start", "quit",
    "never", "always", "don't", "dont", "do", "put", "run", "check",
    "ببین", "نگاه", "بساز", "بنویس", "امتحان", "بزن", "کپی", "بدزد", "ذخیره",
    "سیو", "پاک", "نکن", "بگو", "بپرس", "برو", "بخون", "تست", "شروع",
    "بفرست", "هیچ‌وقت", "همیشه", "دیگه",
}

DEALBREAKERS = [
    (re.compile(r"(?i)^\s*(?:stop scrolling|don'?t scroll)"),
     "Opens with \"stop scrolling\". Asking for attention proves you have not earned it."),
    (re.compile(r"(?i)\b(?:in (?:this|today'?s) (?:video|reel)|i'?m going to show you|i'?ll show you how)\b"),
     "Video preamble. Delete it and open on the payoff."),
    (re.compile(r"(?i)^\s*(?:hey |hi |what'?s up |welcome )"),
     "Greeting. Nobody came to the feed to be greeted."),
    (re.compile(r"^\s*(?:اسکرول\s+نکن|رد\s+نشو|صبر\s+کن\s+رد\s+نشو|وایسا)"),
     "شروع با «اسکرول نکن». خواهش برای توجه یعنی هنوز به دستش نیاوردی."),
    (re.compile(r"(?:تو|توی|در)\s+(?:این|امروز)\s*(?:ویدیو|ویدئو|ریلز|پست)"
                r"|امروز\s+(?:می‌خوام|میخوام|می‌خواهم|قراره)"
                r"|می‌خوام\s+(?:بهت|بهتون)\s+(?:نشون|یاد)"),
     "مقدمه‌ی ویدیو («تو این ویدیو…»). پاکش کن و با خود نتیجه شروع کن."),
    (re.compile(r"^\s*(?:سلام|درود)"),
     "سلام کردن. کسی برای سلام شنیدن تو فید نیومده."),
    (re.compile(r"تا\s+آخر\s+(?:ویدیو\s+)?(?:ببین|ببینید)"),
     "«تا آخر ببین». به‌جای خواهش، یه سؤال بذار که فقط آخر جواب بگیره."),
    (fa.HASHTAG_RE,
     "Hashtag in the hook. هشتگ جاش پایین کپشنه، اگه اصلاً لازم باشه."),
    (fa.EMOJI_RE,
     "Emoji in the hook. متن هوک یا جای کلمه داره یا ایموجی، نه هر دو."),
]


def clamp(n):
    return max(0.0, min(100.0, n))


def check_length(text, wps):
    """A hook has to land before the thumb moves. Roughly two seconds."""
    n = len(fa.words(text))
    secs = n / wps
    chars = len(text.strip())
    if 5 <= n <= 12:
        score = 100.0
    elif n < 5:
        score = clamp(100 - (5 - n) * 20)
    else:
        score = clamp(100 - (n - 12) * 11)
    if chars > 60:                       # two lines of big on-screen text
        score -= 12
    return clamp(score), f"{n} words, {chars} chars, ~{secs:.1f}s spoken (want 5-12 words)"


def check_specificity(text):
    """One concrete thing beats three abstract ones."""
    found = fa.concrete_markers(text)
    hits = len(found)
    score = 15.0 if hits == 0 else clamp(45 + hits * 30)
    return score, (f"{hits} concrete marker(s)" + (f": {', '.join(found[:4])}" if found else
                   " - no number, no name, nothing checkable / عدد و اسم نداره"))


def check_stakes(text):
    """Tension, cost, negation. Something the viewer might lose."""
    toks = [fa.norm(w) for w in fa.words(text)]
    hits = {t for t in toks if t in STAKES or t.startswith("نمی‌") or t.startswith("نمی")}
    markers = sorted(hits)
    if re.search(r"\$\s?\d", text) or re.search(r"\d\s*(?:تومن|تومان|دلار)", fa.to_ascii_digits(text)):
        markers.append("a price")
    n = len(markers)
    score = {0: 20.0, 1: 70.0}.get(n, 100.0)
    detail = f"{n} tension marker(s)" + (f": {', '.join(markers[:4])}" if markers else
                                         " - nothing is at stake in this line / چیزی در خطر نیست")
    return clamp(score), detail


def _is_payload(tok, i):
    t = fa.norm(tok)
    return bool(t in STAKES or t.startswith("نمی") or t in fa.SPOKEN_NUMBERS
                or t in fa.MONEY_WORDS or re.match(r"[\d$]", fa.to_ascii_digits(tok))
                or (i and fa.LATIN_NAME_RE.match(tok)))


def check_frontload(text):
    """The interesting word cannot be in position nine."""
    w = fa.words(text)
    if not w:
        return 0.0, "empty"
    low = [fa.norm(x) for x in w]
    opener = " ".join(low[:2])
    penalty, hit_opener = 0, None
    for weak in WEAK_OPENERS:
        if opener.startswith(weak) or low[0] == weak:
            penalty, hit_opener = 30, weak
            break
    payload = next((i for i, tok in enumerate(w) if _is_payload(tok, i)), None)
    if payload is None:
        base, where = 30.0, "no payload word anywhere in the line"
    elif payload <= 3:
        base, where = 100.0, f"payload at word {payload + 1}"
    elif payload <= 6:
        base, where = 70.0, f"payload at word {payload + 1}, could move forward"
    else:
        base, where = 40.0, f"payload at word {payload + 1}, too late"
    detail = where + (f"; weak opener \"{hit_opener}\"" if hit_opener else "")
    return clamp(base - penalty), detail


def check_address(text):
    """Aimed at one viewer, or floating in the air."""
    who = fa.address(text)
    first = fa.norm(fa.words(text)[0]) if fa.words(text) else ""
    if who == "you":
        return 100.0, "speaks to the viewer / با «تو» حرف می‌زنه"
    if first in IMPERATIVES:
        return 90.0, f"imperative opener (\"{first}\")"
    if who == "me":
        return 70.0, "first person, no viewer named / «من» داره، «تو» نه"
    return 35.0, "third person, nobody in the room / با هیچ‌کس حرف نمی‌زنه"


CHECKS = ["LENGTH", "SPECIFICITY", "STAKES", "FRONTLOAD", "ADDRESS"]


def run(text, wpm=None):
    if wpm is None:
        wpm = 150 if fa.is_persian(text) else 165
    results = {
        "LENGTH": check_length(text, wpm / 60.0),
        "SPECIFICITY": check_specificity(text),
        "STAKES": check_stakes(text),
        "FRONTLOAD": check_frontload(text),
        "ADDRESS": check_address(text),
    }
    flags = [msg for pattern, msg in DEALBREAKERS if pattern.search(text)]
    scores = [results[c][0] for c in CHECKS]
    # The weakest property caps the hook: one bad property is enough for the
    # thumb to keep moving.
    overall = clamp(statistics.mean(scores) * 0.6 + min(scores) * 0.4 - len(flags) * 15)
    verdict = "STRONG" if overall >= 70 and min(scores) >= 55 and not flags else (
        "OK" if overall >= 50 else "WEAK")
    return results, overall, verdict, flags


def bar(score, width=24):
    filled = round(score / 100 * width)
    return "#" * filled + "." * (width - filled)


def render_one(text, results, overall, verdict, flags, out=sys.stdout):
    print("\nHOOK SCORE", file=out)
    print("=" * 62, file=out)
    print(f"  \"{text.strip()}\"\n", file=out)
    for name in CHECKS:
        score, detail = results[name]
        print(f"  {name:<13} {bar(score)} {score:5.1f}", file=out)
        print(f"  {'':<13} {detail}", file=out)
    print("-" * 62, file=out)
    print(f"  {'HOOK SCORE':<13} {bar(overall)} {overall:5.1f}   {verdict}", file=out)
    for f in flags:
        print(f"\n  DEALBREAKER  {f}", file=out)
    if verdict != "STRONG":
        weakest = min(CHECKS, key=lambda c: results[c][0])
        print(f"\n  Weakest property: {weakest}. Fix that one and re-run.", file=out)
    print("", file=out)


def render_table(rows, out=sys.stdout):
    print("\nHOOK RANKING\n" + "=" * 78, file=out)
    for i, r in enumerate(rows, 1):
        mark = "->" if i == 1 else "  "
        hook = r["hook"] if len(r["hook"]) <= 62 else r["hook"][:59] + "..."
        print(f"{mark} {r['score']:5.1f} {r['verdict']:<7} {hook}", file=out)
        print(f"        weakest: {r['weakest']} ({r['checks'][r['weakest']]['score']:.0f})", file=out)
        for f in r["flags"]:
            print(f"        dealbreaker: {f}", file=out)
    print("\nShoot the top one. If the top one is under 50, none of these are the hook.\n"
          "اولی رو ضبط کن. اگه اولی زیر ۵۰ـه، هیچ‌کدوم هوک نیستن.\n", file=out)


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Score a Reel hook on five properties (Persian + English).")
    ap.add_argument("input", nargs="?", default="-", help="file with one hook per line, or -")
    ap.add_argument("--hook", help="score a single hook given on the command line")
    ap.add_argument("--wpm", type=float, help="speaking rate (default 150 Persian, 165 English)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.hook:
        lines = [args.hook]
    else:
        raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if not lines:
        print("nothing to score", file=sys.stderr)
        sys.exit(2)

    payload = []
    for line in lines:
        results, overall, verdict, flags = run(line, args.wpm)
        payload.append({
            "hook": line,
            "checks": {k: {"score": round(v[0], 1), "detail": v[1]} for k, v in results.items()},
            "weakest": min(CHECKS, key=lambda c: results[c][0]),
            "flags": flags,
            "score": round(overall, 1),
            "verdict": verdict,
        })

    if args.json:
        print(json.dumps(payload if len(payload) > 1 else payload[0], indent=2, ensure_ascii=False))
        return
    if len(payload) == 1:
        results, overall, verdict, flags = run(lines[0], args.wpm)
        render_one(lines[0], results, overall, verdict, flags)
    else:
        render_table(sorted(payload, key=lambda r: -r["score"]))
    sys.exit(0 if max(p["score"] for p in payload) >= 70 else 1)


if __name__ == "__main__":
    main()
