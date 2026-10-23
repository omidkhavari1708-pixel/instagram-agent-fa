#!/usr/bin/env python3
"""
beats.py - turn a Reel script into a timed beat sheet before you record it.
Persian and English.

Adapted from Jake Schincariol's instagram-agent-skill (MIT). The original
counted only Latin letters, so a Persian script timed out at a few seconds no
matter how long it was. This version counts Persian words (a half-space keeps
«می‌سازی» one word), Persian digits, spoken Persian numbers, and splits
sentences on «؟» and «…» as well.

It flags the four things that kill a Reel in the edit: a hook that runs past
three seconds, a beat long enough for the viewer to leave, a run of lines with
nothing concrete in them, and a total length that misses your target. It also
reports the true spoken length, because a script labelled "45 seconds" that
holds 240 words is an 85-second reel.

Timings come from word count at a words-per-minute rate. The default is 150
for Persian and 165 for English. Persian speaking rates vary a lot from person
to person, so time yourself reading one script out loud and pass --wpm.

Usage
  python3 beats.py script.txt
  python3 beats.py script.txt --target 40
  python3 beats.py script.txt --wpm 170 --target 45
  python3 beats.py script.txt --json
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fatext as fa  # noqa: E402

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for",
    "with", "that", "this", "it", "is", "are", "was", "were", "be", "been",
    "you", "your", "i", "my", "me", "we", "our", "they", "them", "he", "she",
    "so", "just", "not", "no", "do", "did", "does", "have", "has", "had",
    "will", "can", "at", "as", "by", "from", "out", "up", "off", "one", "all",
    "و", "که", "از", "به", "با", "رو", "را", "تو", "توی", "در", "این", "اون",
    "آن", "یه", "یک", "هم", "برای", "واسه", "یا", "اگه", "ولی", "اما", "من",
    "ما", "شما", "چی", "هست", "است", "بود", "شد", "می‌شه", "نه", "آره", "حالا",
    "اینو", "اونو", "خیلی", "دیگه", "فقط", "بعد", "قبل", "همه", "هر", "چون",
}

HOOK_WINDOW = 3.0        # seconds. Past this, the thumb has already decided.
MAX_BEAT = 4.0           # seconds on one idea with no change on screen.
ABSTRACT_RUN = 3         # beats in a row with nothing checkable in them.


def tc(seconds):
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f}"


def split_beats(raw, wps):
    """One line is one beat, unless a line is too long to be one."""
    beats = []
    for line in [l.strip() for l in raw.splitlines()]:
        if not line:
            continue
        if len(fa.words(line)) / wps <= MAX_BEAT * 1.5:
            beats.append(line)
            continue
        parts = [p.strip() for p in fa.SENT_RE.findall(line) if p.strip()]
        buf = ""
        for part in parts:
            candidate = (buf + " " + part).strip()
            if buf and len(fa.words(candidate)) / wps > MAX_BEAT:
                beats.append(buf)
                buf = part
            else:
                buf = candidate
        if buf:
            beats.append(buf)
    return beats


def analyse(raw, wpm=None, target=None):
    if wpm is None:
        wpm = 150 if fa.is_persian(raw) else 165
    wps = wpm / 60.0
    beats = split_beats(raw, wps)
    if not beats:
        return None

    rows, clock = [], 0.0
    for i, text in enumerate(beats):
        n = len(fa.words(text))
        dur = n / wps
        rows.append({
            "n": i + 1, "start": round(clock, 2), "dur": round(dur, 2), "words": n,
            "text": text, "concrete": len(fa.concrete_markers(text)),
            "label": "", "flags": [],
        })
        clock += dur
    total = clock

    for r in rows:
        if r["n"] == 1 or r["start"] + r["dur"] <= HOOK_WINDOW:
            r["label"] = "HOOK"
    rows[-1]["label"] = "CTA" if rows[-1]["label"] != "HOOK" else "HOOK/CTA"
    half = total / 2
    for r in rows:
        if not r["label"] and r["start"] <= half < r["start"] + r["dur"]:
            r["label"] = "MID"

    notes = []
    if rows[0]["dur"] > HOOK_WINDOW:
        rows[0]["flags"].append(f"hook runs {rows[0]['dur']:.1f}s, past the {HOOK_WINDOW:.0f}s mark")
        notes.append(f"Beat 1 takes {rows[0]['dur']:.1f}s to say. Cut it to "
                     f"{int(HOOK_WINDOW * wps)} words or fewer. "
                     f"هوک بیشتر از ۳ ثانیه‌ست؛ کوتاهش کن.")
    if rows[0]["concrete"] == 0:
        notes.append("Beat 1 has no number and no name in it. خط اول عدد یا اسم نداره.")

    for r in rows:
        if r["dur"] > MAX_BEAT:
            r["flags"].append(f"{r['dur']:.1f}s on one beat")
    long_beats = [r["n"] for r in rows if r["dur"] > MAX_BEAT]
    if long_beats:
        notes.append(f"Beat(s) {', '.join(map(str, long_beats))} run past {MAX_BEAT:.0f}s. "
                     "Split the line or change what is on screen inside it. "
                     "قاب ثابت همون‌جاییه که مخاطب می‌ره.")

    run, start = 0, None
    for r in rows:
        if r["concrete"] == 0:
            run += 1
            start = start if start is not None else r["n"]
            if run == ABSTRACT_RUN:
                notes.append(f"Beats {start}-{r['n']} have nothing concrete in them. "
                             "Put a number, a name or a price in one of them.")
        else:
            run, start = 0, None

    first = {fa.norm(w) for w in fa.words(rows[0]["text"])} - STOPWORDS
    last = {fa.norm(w) for w in fa.words(rows[-1]["text"])} - STOPWORDS
    loop = sorted(first & last)
    if loop:
        notes.append(f"Loops: the last beat repeats \"{', '.join(loop[:3])}\" from the hook. "
                     "Second watches are free reach.")
    else:
        notes.append("No loop. The last beat shares no word with the hook. "
                     "تکرار یه کلمه از خط اول تو خط آخر، ارزون‌ترین تماشای دوباره‌ست.")

    if target:
        delta = total - target
        if abs(delta) <= target * 0.1:
            notes.append(f"Length is on target ({total:.1f}s against {target}s).")
        elif delta > 0:
            notes.append(f"{delta:.1f}s over target. Cut about {int(delta * wps)} words.")
        else:
            notes.append(f"{-delta:.1f}s under target. Short is usually right.")

    return {
        "wpm": wpm, "target": target,
        "total_seconds": round(total, 2),
        "total_words": sum(r["words"] for r in rows),
        "beats": rows, "notes": notes,
    }


def render(a, out=sys.stdout):
    head = (f"BEAT SHEET  ·  {a['total_words']} words  ·  ~{a['total_seconds']:.1f}s "
            f"at {a['wpm']:.0f} wpm" + (f"  ·  target {a['target']}s" if a["target"] else ""))
    print("\n" + head, file=out)
    print("=" * max(len(head), 72), file=out)
    for r in a["beats"]:
        label = f"{r['label']:<8}" if r["label"] else " " * 8
        print(f"  {tc(r['start'])}  {r['dur']:4.1f}s  {label}{r['text']}", file=out)
        for f in r["flags"]:
            print(f"  {'':>6}  {'':>5}  {'':<8}^ {f}", file=out)
    print("-" * max(len(head), 72), file=out)
    for n in a["notes"]:
        print(f"  - {n}", file=out)
    print("", file=out)


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Time a Reel script into a beat sheet (Persian + English).")
    ap.add_argument("input", nargs="?", default="-", help="script file, or - for stdin")
    ap.add_argument("--wpm", type=float, help="speaking rate (default 150 Persian, 165 English)")
    ap.add_argument("--target", type=float, help="target length in seconds")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    a = analyse(raw, wpm=args.wpm, target=args.target)
    if not a:
        print("empty script", file=sys.stderr)
        sys.exit(2)
    if args.json:
        print(json.dumps(a, indent=2, ensure_ascii=False))
    else:
        render(a)
    sys.exit(0)


if __name__ == "__main__":
    main()
