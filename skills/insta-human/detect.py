#!/usr/bin/env python3
"""
detect.py - a five-check panel that scores how machine-written a draft looks.
Persian and English.

Adapted from Jake Schincariol's instagram-agent-skill (MIT). For Persian the
checks change where the language does:

  - words, sentences and numbers are counted with fatext (half-space words,
    Persian digits, «؟»).
  - FINGERPRINT no longer counts the Persian half-space or direction marks as
    "invisible watermark characters": they are how Persian is typed.
  - VOICE has no contractions to count in Persian. The equivalent tell is the
    register: a reel script in written Persian («می‌باشد»، «را»، «می‌شود»)
    instead of spoken Persian («هست»، «رو»، «می‌شه»). That ratio replaces
    contractions for Persian text.

What this is NOT:  GPTZero, Originality, Copyleaks, Winston or Turnitin. It
does not call any API and cannot promise their verdicts. Every score is
computed on your machine from the text alone.

Usage
  python3 detect.py draft.txt
  python3 detect.py before.txt after.txt      # compare two drafts
  python3 detect.py draft.txt --json
"""

import argparse
import json
import os
import re
import statistics
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fatext as fa  # noqa: E402

LEX = os.path.join(HERE, "slop.json")
CONTRACTIONS = re.compile(r"\b\w+'(?:s|t|re|ve|ll|d|m)\b", re.IGNORECASE)
PRONOUNS_EN = re.compile(r"\b(i|me|my|mine|we|us|our|you|your)\b", re.IGNORECASE)


def clamp(n):
    return max(0.0, min(100.0, n))


def scale(value, human, machine):
    """Map value onto 0-100 where `human` -> 100 and `machine` -> 0."""
    if human == machine:
        return 50.0
    return clamp((value - machine) / (human - machine) * 100)


def check_burstiness(text):
    """Humans vary sentence length hard. Models write even."""
    lens = [len(fa.words(s)) for s in fa.sentences(text)]
    if len(lens) < 4:
        return 50.0, "too short to judge"
    mean = statistics.mean(lens)
    cv = statistics.pstdev(lens) / mean if mean else 0
    return scale(cv, human=0.70, machine=0.22), \
        f"variation {cv:.2f} across {len(lens)} sentences (want 0.55+)"


def check_specificity(text):
    """Numbers, names and concrete nouns. Slop is abstract."""
    w = fa.words(text)
    if len(w) < 25:
        return 50.0, "too short to judge"
    hits = len(fa.concrete_markers(text))
    density = hits * 100 / len(w)
    return scale(density, human=6.0, machine=0.5), \
        f"{hits} concrete markers, {density:.1f} per 100 words (want 4+)"


def check_slop(text, lex):
    """Stock vocabulary density against the lexicon (both languages)."""
    w = fa.words(text)
    if not w:
        return 50.0, "empty"
    hits, found = 0, []
    for entry in lex["words"] + lex["phrases"]:
        body = re.escape(entry["find"]).replace(r"\ ", " ").replace(" ", r"[\s‌]+")
        n = len(re.findall(r"(?<![\w‌])" + body + r"(?![\w])", text, re.IGNORECASE))
        if n:
            hits += n
            found.append(entry["find"])
    density = hits * 100 / len(w)
    detail = f"{hits} stock terms, {density:.1f} per 100 words"
    if found:
        detail += " (" + ", ".join(sorted(found)[:4]) + (", ..." if len(found) > 4 else "") + ")"
    return scale(density, human=0.0, machine=4.0), detail


def check_fingerprint(text):
    """Characters a phone keyboard does not produce. The Persian half-space does."""
    keep = fa.PERSIAN_KEEP | {"‍"}
    invisible = sum(1 for c in text if unicodedata.category(c) == "Cf" and c not in keep)
    em = text.count("—")
    curly = sum(text.count(c) for c in "‘’“”")
    ellip = text.count("…")
    nbsp = sum(text.count(c) for c in "   ")
    total = invisible * 4 + em * 2 + curly + ellip + nbsp
    per1k = total * 1000 / max(len(text), 1)
    detail = (f"{invisible} invisible, {em} em dash, {curly} curly quote, "
              f"{ellip} ellipsis, {nbsp} hard space (half-spaces not counted)")
    return scale(per1k, human=0.0, machine=12.0), detail


def _tells(text, lex):
    tells, names = 0, []
    for s in lex["structures"]:
        try:
            n = len(re.compile(s["regex"], re.MULTILINE).findall(text))
        except re.error:
            continue
        if n:
            tells += n
            names.append(s["id"])
    return tells, names


def check_voice(text, lex):
    """English: contractions + person. Persian: spoken vs written register + person."""
    w = fa.words(text)
    if len(w) < 25:
        return 50.0, "too short to judge"
    per100 = 100 / len(w)
    tells, names = _tells(text, lex)
    bullets = [len(fa.words(b)) for b in re.findall(r"(?m)^\s*[-*•]\s+(.+)$", text)]
    uniform = len(bullets) >= 3 and statistics.pstdev(bullets) < 1.6

    if fa.is_persian(text):
        col, frm = fa.register(text)
        reg = col / (col + frm) if (col + frm) else 0.5
        toks = [fa.norm(t) for t in w]
        person = sum(1 for t in toks if fa.is_you(t) or fa.is_me(t)) * per100
        score = (scale(reg, human=0.85, machine=0.30) * 0.35
                 + scale(person, human=8.0, machine=1.0) * 0.35
                 + clamp(100 - tells * 22) * 0.30)
        detail = (f"register {col} spoken / {frm} written ({reg:.0%} spoken), "
                  f"{person:.1f} person markers per 100 words, {tells} structural tell(s)")
    else:
        contractions = len(CONTRACTIONS.findall(text)) * per100
        person = len(PRONOUNS_EN.findall(text)) * per100
        score = (scale(contractions, human=3.0, machine=0.0) * 0.35
                 + scale(person, human=8.0, machine=1.0) * 0.35
                 + clamp(100 - tells * 22) * 0.30)
        detail = (f"{contractions:.1f} contractions, {person:.1f} personal pronouns "
                  f"per 100 words, {tells} structural tell(s)")
    if uniform:
        score -= 12
        names.append("uniform-bullets")
    if names:
        detail += " [" + ", ".join(names[:4]) + "]"
    return clamp(score), detail


CHECKS = ["BURSTINESS", "SPECIFICITY", "SLOP DENSITY", "FINGERPRINT", "VOICE"]


def run(text, lex):
    results = {
        "BURSTINESS": check_burstiness(text),
        "SPECIFICITY": check_specificity(text),
        "SLOP DENSITY": check_slop(text, lex),
        "FINGERPRINT": check_fingerprint(text),
        "VOICE": check_voice(text, lex),
    }
    scores = [results[c][0] for c in CHECKS]
    overall = statistics.mean(scores) * 0.6 + min(scores) * 0.4
    verdict = "PASS" if overall >= 70 and min(scores) >= 55 else (
        "REVIEW" if overall >= 50 else "FLAGGED")
    return results, overall, verdict


def bar(score, width=24):
    filled = round(score / 100 * width)
    return "#" * filled + "." * (width - filled)


def render(results, overall, verdict, label=None, out=sys.stdout):
    title = "AI DETECTION PANEL" + (f"  -  {label}" if label else "")
    print("\n" + title, file=out)
    print("=" * max(len(title), 62), file=out)
    for name in CHECKS:
        score, detail = results[name]
        print(f"  {name:<13} {bar(score)} {score:5.1f}", file=out)
        print(f"  {'':<13} {detail}", file=out)
    print("-" * 62, file=out)
    print(f"  {'HUMAN SCORE':<13} {bar(overall)} {overall:5.1f}   {verdict}", file=out)
    if verdict != "PASS":
        weakest = min(CHECKS, key=lambda c: results[c][0])
        print(f"\n  Weakest signal: {weakest}. Fix that first.", file=out)
    print("", file=out)


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Score how machine-written a draft looks (Persian + English).")
    ap.add_argument("input", nargs="?", default="-", help="file, or - for stdin")
    ap.add_argument("compare", nargs="?", help="second file, to show before/after")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--lexicon", default=LEX)
    args = ap.parse_args()

    lex = json.load(open(args.lexicon, encoding="utf-8"))
    read = lambda p: sys.stdin.read() if p == "-" else open(p, encoding="utf-8").read()
    targets = [(args.input, read(args.input))]
    if args.compare:
        targets.append((args.compare, read(args.compare)))

    payload = []
    for name, text in targets:
        results, overall, verdict = run(text, lex)
        payload.append({
            "source": name,
            "checks": {k: {"score": round(v[0], 1), "detail": v[1]} for k, v in results.items()},
            "human_score": round(overall, 1),
            "verdict": verdict,
        })

    if args.json:
        print(json.dumps(payload if args.compare else payload[0], indent=2, ensure_ascii=False))
        return
    for (name, text), p in zip(targets, payload):
        results, overall, verdict = run(text, lex)
        render(results, overall, verdict, label=os.path.basename(name) if args.compare else None)
    if args.compare:
        a, b = payload
        delta = b["human_score"] - a["human_score"]
        print(f"  {a['human_score']:.1f} {a['verdict']}  ->  "
              f"{b['human_score']:.1f} {b['verdict']}   ({delta:+.1f})\n")
    sys.exit(0 if payload[-1]["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
