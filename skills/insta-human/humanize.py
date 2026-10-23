#!/usr/bin/env python3
"""
humanize.py - strip the machine fingerprint out of a draft. Persian and English.

Adapted from Jake Schincariol's instagram-agent-skill (MIT). The original
deleted every invisible "format" character, and in Persian that includes the
half-space (ZWNJ): «می‌سازی» became «میسازی» and «کلمه‌ی» became the broken
«کلمهی». This version never touches the half-space or the direction marks,
and adds what Persian text actually needs:

  1. INVISIBLE   delete the characters a keyboard never produces - zero-width
                 spaces, word joiners, BOMs, tag characters - but KEEP the
                 Persian half-space (U+200C), the direction marks (U+200E,
                 U+200F, U+061C) and the joiner inside emoji sequences.
  2. PERSIAN     ي/ك -> ی/ک, Arabic-Indic digits -> Persian digits, the spaced
                 prefix «می شه» -> «می‌شه», spaced suffixes «سایت ها» -> «سایت‌ها».
  3. TYPOGRAPHIC English text: em dash -> comma, curly quotes -> straight.
                 Persian text: em dash -> «،», curly quotes -> « », and Latin
                 , ; ? next to Persian letters -> ، ؛ ؟
  4. LEXICAL     the slop lexicon in slop.json, English and Persian, replaced
                 with plain words. URLs are never rewritten.
  5. SPOKEN      (only with --spoken) written Persian -> spoken Persian:
                 «می‌شود» -> «می‌شه»، «را» -> «رو». For reel scripts and
                 voiceovers, never for captions you want to keep formal.

Structural tells («این فقط یه X نیست، بلکه Y», rule-of-three, hashtag walls)
are REPORTED, never auto-rewritten: changing a sentence's shape needs judgement.

Usage
  python3 humanize.py draft.txt --report
  python3 humanize.py script.txt --spoken --report      # a reel script
  python3 humanize.py draft.txt -o clean.txt
  python3 humanize.py draft.txt --json
"""

import argparse
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fatext as fa  # noqa: E402

LEX = os.path.join(HERE, "slop.json")
URL_RE = re.compile(r"https?://\S+|www\.\S+|\S+@\S+\.\S+")
FA_LETTER = r"[؀-ۿ]"
PUNCT = ",.;:!?،؛؟"


def load_lexicon(path=LEX):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _cp(spec):
    if "-" in spec:
        a, b = spec.split("-")
        return (int(a[2:], 16), int(b[2:], 16))
    return int(spec[2:], 16)


def protect_urls(text):
    found = []

    def stash(m):
        found.append(m.group(0))
        return f"\x00URL{len(found) - 1}\x00"

    return URL_RE.sub(stash, text), found


def restore_urls(text, found):
    for i, url in enumerate(found):
        text = text.replace(f"\x00URL{i}\x00", url)
    return text


def _is_emojiish(ch):
    return bool(ch) and (unicodedata.category(ch) in ("So", "Sk") or 0x1F000 <= ord(ch) <= 0x1FFFF)


def pass_invisible(text, lex):
    """Delete or space-normalise invisible characters, keeping the Persian ones."""
    hits = []
    for entry in lex["invisible"]:
        action = entry["action"]
        if action == "keep":
            continue
        cp = _cp(entry["cp"])
        if action == "keep-in-emoji":
            ch = chr(cp)
            out, n = [], 0
            for i, c in enumerate(text):
                if c == ch and not (i and i + 1 < len(text)
                                    and _is_emojiish(text[i - 1]) and _is_emojiish(text[i + 1])):
                    n += 1
                    continue
                out.append(c)
            if n:
                text = "".join(out)
                hits.append({"name": entry["cp"] + " " + entry["name"] + " (outside emoji)",
                             "count": n, "action": "delete"})
            continue
        if isinstance(cp, tuple):
            pattern = "[" + re.escape(chr(cp[0])) + "-" + re.escape(chr(cp[1])) + "]"
        else:
            pattern = re.escape(chr(cp))
        n = len(re.findall(pattern, text))
        if n:
            hits.append({"name": entry["cp"] + " " + entry["name"], "count": n, "action": action})
            text = re.sub(pattern, "" if action == "delete" else " ", text)
    # Any other format character is invisible by definition, except the ones
    # Persian needs and a joiner that is holding an emoji together.
    keep = fa.PERSIAN_KEEP | {"‍"}
    stray = [c for c in text if unicodedata.category(c) == "Cf" and c not in keep]
    if stray:
        hits.append({"name": "other invisible format chars", "count": len(stray), "action": "delete"})
        text = "".join(c for c in text if not (unicodedata.category(c) == "Cf" and c not in keep))
    return text, hits


def pass_persian(text, lex):
    """Persian normalisation. Only runs on text that has Persian in it."""
    hits = []
    if not fa.ARABIC_SCRIPT_RE.search(text):
        return text, hits
    for entry in lex.get("normalize_fa", []):
        src, dst = entry["from"], entry["to"]
        n = sum(text.count(c) for c in src)
        if n:
            text = text.translate(str.maketrans(src, dst))
            hits.append({"name": entry["name"], "count": n})
    # «می شه» -> «می‌شه». The prefix is a whole word, followed by a Persian word.
    pattern = re.compile(r"(^|[\s«(])(ن?می) (?=[؀-ۿ])")
    n = len(pattern.findall(text))
    if n:
        text = pattern.sub(lambda m: m.group(1) + m.group(2) + fa.ZWNJ, text)
        hits.append({"name": "spaced prefix «می » -> «می‌»", "count": n})
    # «سایت ها» -> «سایت‌ها», «بزرگ ترین» -> «بزرگ‌ترین».
    pattern = re.compile(r"(?<=[؀-ۿ]) (ها|های|هایی|تر|ترین)(?=[\s.,،!؟?:؛»)]|$)")
    n = len(pattern.findall(text))
    if n:
        text = pattern.sub(lambda m: fa.ZWNJ + m.group(1), text)
        hits.append({"name": "spaced suffix «ها / تر / ترین» -> half-space", "count": n})
    return text, hits


def pass_typographic(text, lex, persian):
    hits = []
    table = lex["typographic_fa"] if persian else lex["typographic"]
    for entry in table:
        ch = entry["from"]
        n = text.count(ch)
        if not n:
            continue
        hits.append({"name": f"{ch} {entry['name']}", "count": n, "to": entry["to"].strip() or "(space)"})
        if ch == "—":
            sep = "، " if persian else ", "
            text = re.sub(r"\s*—\s*", sep, text)
        elif ch == "–":
            text = re.sub(r"\s*–\s*(?=\d)", "-", text)
            text = re.sub(r"\s+–\s+", "، " if persian else ", ", text)
            text = text.replace("–", "-")
        else:
            text = text.replace(ch, entry["to"])
    if persian:
        # Latin punctuation glued to Persian words -> Persian punctuation.
        for latin, persian_mark in ((",", "،"), (";", "؛"), ("?", "؟")):
            pattern = re.compile(rf"(?<={FA_LETTER})\s*{re.escape(latin)}(?!\d)")
            n = len(pattern.findall(text))
            if n:
                text = pattern.sub(persian_mark, text)
                hits.append({"name": f"{latin} after a Persian word", "count": n, "to": persian_mark})
    text = re.sub(rf"[,،]\s*([{re.escape(PUNCT)}])", r"\1", text)
    text = re.sub(r"[,،]\s*\n", "\n", text)
    return text, hits


def _match_case(src, repl):
    if not repl:
        return repl
    if src.isupper() and len(src) > 1:
        return repl.upper()
    if src[0].isupper():
        return repl[0].upper() + repl[1:]
    return repl


def _phrase_re(find):
    body = re.escape(find).replace(r"\ ", " ").replace(" ", r"[\s‌]+")
    return re.compile(r"(?<![\w‌])" + body + r"(?![\w])", re.IGNORECASE)


def _cleanup(text):
    p = re.escape(PUNCT)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(rf"(?m)^[ \t]*(?:[{p}]+[ \t]*)+", "", text)
    text = re.sub(r"(?m)^[ \t](?=\S)", "", text)
    text = re.sub(rf"\s+([{p}])", r"\1", text)
    text = re.sub(rf"[,،]\s*([{p}])", r"\1", text)
    text = text.replace("...", "\x00ELL\x00")
    text = re.sub(r"\.\s*\.+", ".", text)
    text = re.sub(r"([!?؟])\s*\.", r"\1", text)
    text = text.replace("\x00ELL\x00", "...")
    text = re.sub(r"(?m)^[ \t]+$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r",\s*(also|so|still|basically|in the end)\s*,\s*",
                  lambda m: ". " + m.group(1)[0].upper() + m.group(1)[1:] + ", ", text)
    return text


def pass_lexical(text, lex):
    """Replace slop words and phrases. Longest first so phrases win."""
    hits = []
    entries = sorted(lex["phrases"] + lex["words"], key=lambda e: len(e["find"]), reverse=True)
    for entry in entries:
        pattern = _phrase_re(entry["find"])
        found = pattern.findall(text)
        if not found:
            continue
        hits.append({"find": entry["find"], "replace": entry["replace"] or "(deleted)",
                     "count": len(found), "family": entry["family"]})
        text = pattern.sub(lambda m: _match_case(m.group(0), entry["replace"]), text)
    return _cleanup(text), hits


def pass_spoken(text, lex):
    """Written Persian -> spoken Persian. Only with --spoken."""
    hits = []
    for entry in sorted(lex.get("spoken", []), key=lambda e: len(e["find"]), reverse=True):
        pattern = _phrase_re(entry["find"])
        n = len(pattern.findall(text))
        if n:
            text = pattern.sub(entry["replace"], text)
            hits.append({"find": entry["find"], "replace": entry["replace"], "count": n})
    return text, hits


def scan_structures(text, lex):
    flags = []
    for s in lex["structures"]:
        try:
            pattern = re.compile(s["regex"], re.MULTILINE)
        except re.error:
            continue
        found = pattern.findall(text)
        if found:
            flags.append({"name": s["name"], "count": len(found), "fix": s["fix"]})
    lens = [len(fa.words(s)) for s in fa.SENT_RE.findall(text) if len(fa.words(s)) > 2]
    if len(lens) >= 4:
        mean = sum(lens) / len(lens)
        var = sum((n - mean) ** 2 for n in lens) / len(lens)
        cv = (var ** 0.5) / mean if mean else 0
        if cv < 0.35:
            flags.append({
                "name": f"Uniform sentence length (variation {cv:.2f}) / طول جمله‌ها یکنواخته",
                "count": len(lens),
                "fix": "یه جمله رو نصف کن، بذار یکی بلند بشه. ماشین یکنواخت می‌نویسه.",
            })
    return flags


def restore_capitals(original, text):
    """English only: deleting an opener leaves the next word lower case."""
    starts = re.findall(r"(?:^|[.!?]\s+|\n)\s*([A-Za-z])", original)
    if not starts or sum(1 for c in starts if c.isupper()) * 2 < len(starts):
        return text
    return re.sub(r"(?:^|(?<=[.!?] )|(?<=[.!?]\n)|(?<=\n))\s*([a-z])",
                  lambda m: m.group(0)[:-1] + m.group(1).upper(), text)


def humanize(text, lex, spoken=False):
    raw_for_case = text
    persian = fa.is_persian(text)
    text, urls = protect_urls(text)
    text, inv = pass_invisible(text, lex)
    text, per = pass_persian(text, lex)
    text, typo = pass_typographic(text, lex, persian)
    text, lexi = pass_lexical(text, lex)
    spk = []
    if spoken and persian:
        text, spk = pass_spoken(text, lex)
    if not persian:
        text = restore_capitals(raw_for_case, text)
    text = restore_urls(text, urls)
    return text.strip() + "\n", {
        "language": "fa" if persian else "en",
        "invisible": inv, "persian": per, "typographic": typo,
        "lexical": lexi, "spoken": spk,
        "structures": scan_structures(text, lex),
    }


def render_report(report, out=sys.stderr):
    def head(title):
        print(f"\n{title}\n" + "-" * len(title), file=out)

    total = sum(h["count"] for k in ("invisible", "persian", "typographic", "lexical", "spoken")
                for h in report[k])
    head(f"HUMANIZE REPORT  ·  language: {report['language']}")
    print(f"{total} artefacts fixed, {len(report['structures'])} structural tells flagged for rewrite",
          file=out)
    if report["invisible"]:
        head("1. INVISIBLE CHARACTERS  (half-space kept)")
        for h in report["invisible"]:
            print(f"  {h['count']:>3}x  {h['name']}  -> {h['action']}", file=out)
    if report["persian"]:
        head("2. PERSIAN NORMALISATION")
        for h in report["persian"]:
            print(f"  {h['count']:>3}x  {h['name']}", file=out)
    if report["typographic"]:
        head("3. TYPOGRAPHY")
        for h in report["typographic"]:
            print(f"  {h['count']:>3}x  {h['name']}  -> {h['to']}", file=out)
    if report["lexical"]:
        head("4. SLOP LEXICON")
        for h in report["lexical"]:
            print(f"  {h['count']:>3}x  {h['find']}  -> {h['replace']}   [{h['family']}]", file=out)
    if report["spoken"]:
        head("5. SPOKEN PERSIAN  (--spoken)")
        for h in report["spoken"]:
            print(f"  {h['count']:>3}x  {h['find']}  -> {h['replace']}", file=out)
    if report["structures"]:
        head("6. STRUCTURAL TELLS  (not auto-fixed - rewrite these yourself)")
        for h in report["structures"]:
            print(f"  {h['count']:>3}x  {h['name']}\n        {h['fix']}", file=out)
    if not total and not report["structures"]:
        head("CLEAN")
        print("  Nothing to strip.", file=out)
    print("", file=out)


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Strip the machine fingerprint out of a draft (Persian + English).")
    ap.add_argument("input", nargs="?", default="-", help="file, or - for stdin")
    ap.add_argument("-o", "--out", help="write cleaned text here instead of stdout")
    ap.add_argument("--report", action="store_true", help="print what changed, to stderr")
    ap.add_argument("--spoken", action="store_true",
                    help="also turn written Persian into spoken Persian (reel scripts only)")
    ap.add_argument("--json", action="store_true", help="emit {text, report} as JSON")
    ap.add_argument("--lexicon", default=LEX, help="path to slop.json")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    lex = load_lexicon(args.lexicon)
    clean, report = humanize(raw, lex, spoken=args.spoken)

    if args.json:
        print(json.dumps({"text": clean, "report": report}, indent=2, ensure_ascii=False))
        return
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(clean)
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(clean)
    if args.report:
        render_report(report)


if __name__ == "__main__":
    main()
