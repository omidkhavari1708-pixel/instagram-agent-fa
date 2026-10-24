#!/usr/bin/env python3
"""
Tests for the Persian adaptation. Standard library only.

    python3 -m unittest discover tests -v

The two bugs this pack exists to fix are tested first: the humanizer must
never delete the Persian half-space, and the scorers must count Persian words.
"""

import filecmp
import importlib.util
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, "skills")
ZWNJ = "‌"


def load(skill, module):
    path = os.path.join(SKILLS, skill, module + ".py")
    sys.path.insert(0, os.path.join(SKILLS, skill))
    spec = importlib.util.spec_from_file_location(f"{skill}_{module}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.path.pop(0)
    return mod


fa = load("insta-human", "fatext")
humanize = load("insta-human", "humanize")
detect = load("insta-human", "detect")
hookscore = load("insta-reel", "hookscore")
beats = load("insta-reel", "beats")
caption = load("insta-caption", "caption")
def read(*parts):
    with open(os.path.join(SKILLS, *parts), encoding="utf-8") as fh:
        return fh.read()


LEX = json.loads(read("insta-human", "slop.json"))
HOOKS = json.loads(read("insta-reel", "hooks.json"))


class HalfSpace(unittest.TestCase):
    """Bug 1: the original humanizer deleted every ZWNJ."""

    TEXT = "ببین… سایتی که با AI ساختی، خطرناک‌ترین درش تو کدش نیست. حالا تو چی می‌سازی؟ کلمه‌ی «امنیت» رو کامنت کن."

    def test_half_space_survives(self):
        clean, _ = humanize.humanize(self.TEXT, LEX)
        self.assertEqual(clean.count(ZWNJ), self.TEXT.count(ZWNJ))
        self.assertIn("می‌سازی", clean)
        self.assertIn("کلمه‌ی", clean)

    def test_direction_marks_survive(self):
        text = "نسخه‌ی ‏Claude‏ جدیده"
        clean, _ = humanize.humanize(text, LEX)
        self.assertIn("‏", clean)

    def test_real_invisibles_still_go(self):
        clean, _ = humanize.humanize("سلام​دنیا و ﻿تست", LEX)
        self.assertNotIn("​", clean)
        self.assertNotIn("﻿", clean)

    def test_emoji_joiner_survives(self):
        clean, _ = humanize.humanize("برنامه‌نویس 👨‍💻 هستم", LEX)
        self.assertIn("‍", clean)

    def test_spaced_prefix_and_suffix_get_half_space(self):
        clean, _ = humanize.humanize("این کار می شه و سایت ها بزرگ ترین هستن", LEX)
        self.assertIn("می‌شه", clean)
        self.assertIn("سایت‌ها", clean)
        self.assertIn("بزرگ‌ترین", clean)

    def test_arabic_letters_normalised(self):
        clean, _ = humanize.humanize("سايت كوچك براي شما", LEX)
        self.assertNotRegex(clean, "[يك]")

    def test_spoken_mode(self):
        clean, _ = humanize.humanize("شما می‌توانید این را در یک روز بسازید.", LEX, spoken=True)
        self.assertIn("می‌تونید", clean)
        self.assertIn("رو", clean)
        self.assertIn("یه", clean)

    def test_english_unchanged_behaviour(self):
        clean, _ = humanize.humanize("We leverage AI — it's seamless.", LEX)
        self.assertNotIn("—", clean)
        self.assertNotIn("leverage", clean.lower())


class PersianWords(unittest.TestCase):
    """Bug 2: the original counted only [A-Za-z], so Persian was '1 word'."""

    def test_half_space_word_is_one_word(self):
        self.assertEqual(fa.words("می‌سازی"), ["می‌سازی"])

    def test_counts_a_persian_line(self):
        self.assertEqual(len(fa.words("ببین… سایتی که با AI ساختی، خطرناک‌ترین درش تو کدش نیست.")), 11)

    def test_persian_digits_are_numbers(self):
        self.assertTrue(fa.numbers("۱۸٬۰۰۰ تومن"))
        self.assertEqual(fa.words("۱۸٬۰۰۰"), ["18000"])

    def test_tanvin_stays_in_word(self):
        self.assertEqual(fa.words("حتماً"), ["حتماً"])

    def test_address(self):
        self.assertEqual(fa.address("حالا تو چی می‌سازی؟"), "you")
        self.assertEqual(fa.address("من سایتم رو ساختم"), "me")
        self.assertIsNone(fa.address("میلیونی"))

    def test_register(self):
        col, frm = fa.register("این کار می‌شه و رو یه سایت میاد")
        self.assertGreater(col, frm)
        col, frm = fa.register("این کار انجام می‌شود و آن را در یک سایت می‌باشد")
        self.assertGreater(frm, col)


class HookScore(unittest.TestCase):

    def test_persian_hook_is_scored_on_its_words(self):
        res, overall, verdict, _ = hookscore.run("ببین… سایتی که با AI ساختی، خطرناک‌ترین درش تو کدش نیست.")
        self.assertIn("11 words", res["LENGTH"][1])
        self.assertEqual(verdict, "STRONG")

    def test_persian_greeting_is_a_dealbreaker(self):
        _, overall, verdict, flags = hookscore.run("سلام دوستان، امروز می‌خوام یه ابزار جدید بهتون معرفی کنم")
        self.assertEqual(verdict, "WEAK")
        self.assertGreaterEqual(len(flags), 2)

    def test_english_matches_the_original(self):
        # Values produced by the original instagram-agent-skill hookscore.py.
        for hook, expected in [
            ("Proposals used to take me five hours. Twenty minutes now.", 51.2),
            ("Steal the proposal template that did it.", 36.6),
            ("Nobody tells you your first 30 reels are supposed to flop.", 87.0),
        ]:
            _, overall, _, _ = hookscore.run(hook)
            self.assertAlmostEqual(round(overall, 1), expected, places=1, msg=hook)


class Beats(unittest.TestCase):

    def test_persian_script_length(self):
        script = "ببین… سایتی که با AI ساختی، خطرناک‌ترین درش تو کدش نیست.\nحالا تو چی می‌سازی؟"
        a = beats.analyse(script)
        self.assertEqual(a["total_words"], 15)
        self.assertEqual(a["wpm"], 150)


class Caption(unittest.TestCase):

    def test_persian_hashtags_and_ask(self):
        a = caption.analyse("سایت رزومه بدون اجاره.\n\nکلمه‌ی «سایت» رو کامنت کن.\n\n#سایت_شخصی #طراحی_سایت")
        self.assertEqual(len(a["hashtags"]), 2)
        self.assertEqual(len(a["asks"]), 1)

    def test_arabic_letters_flagged(self):
        a = caption.analyse("سايت شخصي براي دكترها")
        status = {c["check"]: c["status"] for c in a["checks"]}
        self.assertEqual(status["PERSIAN LETTERS"], "WARN")

    def test_too_many_hashtags(self):
        a = caption.analyse("متن\n\n" + " ".join(f"#تگ{i}" for i in range(7)))
        status = {c["check"]: c["status"] for c in a["checks"]}
        self.assertEqual(status["HASHTAGS"], "FAIL")


class Hooks(unittest.TestCase):

    def test_ids_and_regexes(self):
        ids = [h["id"] for h in HOOKS["hooks"]]
        self.assertEqual(sorted(ids), list(range(1, 28)))
        self.assertEqual(sorted(HOOKS["classify_order"]), list(range(1, 28)))
        for h in HOOKS["hooks"]:
            re.compile(h["match"], re.IGNORECASE)

    def test_every_persian_example_names_its_own_formula(self):
        by_id = {h["id"]: h for h in HOOKS["hooks"]}
        pats = [(i, re.compile(by_id[i]["match"], re.IGNORECASE)) for i in HOOKS["classify_order"]]
        for h in HOOKS["hooks"]:
            got = next((i for i, p in pats if p.search(h["example"])), None)
            self.assertEqual(got, h["id"], h["example"])


class Detect(unittest.TestCase):

    def test_machine_persian_scores_below_human_persian(self):
        machine = ("در دنیای امروز، هوش مصنوعی یک ابزار شگفت‌انگیز است که می‌تواند زندگی شما را متحول کند. "
                   "این فقط یک ابزار نیست، بلکه یک انقلاب است. شما می‌توانید سایت خود را طراحی نمایید. "
                   "همچنین این ابزار برای کسب‌وکارها بسیار حیاتی می‌باشد. لذا پیشنهاد می‌شود از آن بهره ببرید.")
        human = ("سایتم رو با Claude ساختم و سه بار خراب شد. بار اول شماره تلفنم تو متن فارسی برعکس نشون داده شد. "
                 "یه ساعت گشتم تا فهمیدم مشکل راست‌به‌چپه. بار دوم رو گوشی همه‌چی به هم ریخت. "
                 "الان ۷ صفحه داره، صفر تومن هاست می‌دم، و از ایران تو ۲ ثانیه باز می‌شه.")
        _, m, _ = detect.run(machine, LEX)
        _, h, _ = detect.run(human, LEX)
        self.assertLess(m, h - 20)

    def test_short_comment_can_pass(self):
        # Found by running /insta-comment for real: a 2-3 sentence comment got a neutral 50 on
        # BURSTINESS ("too short to judge"), and the verdict needs every check >= 55, so no
        # comment could ever PASS. Unjudged checks are now left out of the verdict.
        comment = "Real question. When Duet waits for your okay, does it show the exact text it's about to send?"
        results, overall, verdict = detect.run(comment, LEX)
        self.assertEqual(results["BURSTINESS"][1], "too short to judge")
        self.assertEqual(verdict, "PASS")
        slop = "This is a game-changer. It will revolutionize everything. Truly seamless."
        self.assertNotEqual(detect.run(slop, LEX)[2], "PASS")


class Packaging(unittest.TestCase):

    def test_fatext_copies_identical(self):
        src = os.path.join(SKILLS, "insta-human", "fatext.py")
        for skill in ("insta-reel", "insta-caption", "insta-viral"):
            self.assertTrue(filecmp.cmp(src, os.path.join(SKILLS, skill, "fatext.py"), shallow=False), skill)

    def test_every_skill_has_frontmatter_matching_its_folder(self):
        folders = sorted(d for d in os.listdir(SKILLS) if os.path.isdir(os.path.join(SKILLS, d)))
        self.assertEqual(len(folders), 13)
        for d in folders:
            text = read(d, "SKILL.md")
            m = re.match(r"---\nname: ([\w-]+)\ndescription: >-\n", text)
            self.assertIsNotNone(m, d)
            self.assertEqual(m.group(1), d)

    def test_keep_rules_in_lexicon(self):
        actions = {e["cp"]: e["action"] for e in LEX["invisible"]}
        self.assertEqual(actions["U+200C"], "keep")
        self.assertEqual(actions["U+200F"], "keep")


if __name__ == "__main__":
    unittest.main()
