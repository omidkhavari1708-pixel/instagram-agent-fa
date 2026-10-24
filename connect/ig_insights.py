#!/usr/bin/env python3
"""
ig_insights.py - read-only Instagram stats for your own account, through
Meta's official "Instagram API with Instagram Login".

It READS: profile counts, your recent posts, the insights of each reel, and
(if you allow it) your recent DMs. The only thing it can ever write is one DM
reply that you approved word for word (--send ... --yes). It cannot post,
comment, like or follow, and it never asks for a password. The access token
lives in one local file and is never printed.

Token file:  ~/.claude/instagram/.ig_token   (paste the token there yourself)
Output:      ~/.claude/instagram/insights.md and insights.json

Usage
  python3 connect/ig_insights.py              # fetch and write the report
  python3 connect/ig_insights.py --check      # who am I connected as (no report)
  python3 connect/ig_insights.py --refresh    # extend the 60-day token (keeps it local)
  python3 connect/ig_insights.py --limit 50   # how many recent posts to read (default 30)
  python3 connect/ig_insights.py --dms        # read recent DMs into dms.md (read-only)
  python3 connect/ig_insights.py --send <recipient-id> --text-file reply.txt --yes
                                 # send ONE reply, only after you approved
                                 # that exact text

Needs a Professional (Creator or Business) account and a token from a Meta app
that uses "Instagram API with Instagram Login", with the permissions
instagram_business_basic and instagram_business_manage_insights, plus
instagram_business_manage_messages for DMs. Nothing is ever sent automatically:
--send refuses to run without --yes.

Network: requests go out directly, or through HTTPS_PROXY if you set it. From
Iran, point it at your VPN client's local HTTP proxy, for example
HTTPS_PROXY=http://127.0.0.1:10809 (the port depends on your client).

Part of instagram-agent-fa (MIT). Standard library only.
"""

import argparse
import json
import os
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

BASE = "https://graph.instagram.com/v23.0"
HOME = os.path.join(os.path.expanduser("~"), ".claude", "instagram")
TOKEN_FILE = os.path.join(HOME, ".ig_token")
OUT_MD = os.path.join(HOME, "insights.md")
OUT_JSON = os.path.join(HOME, "insights.json")
TEHRAN = timezone(timedelta(hours=3, minutes=30))

REEL_METRICS = ["views", "reach", "saved", "shares", "comments", "likes",
                "total_interactions", "ig_reels_avg_watch_time",
                "ig_reels_video_view_total_time"]
POST_METRICS = ["views", "reach", "saved", "shares", "comments", "likes",
                "total_interactions"]


def opener():
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not proxy:
        return urllib.request.build_opener()
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"https": proxy, "http": proxy}))


def read_token():
    if not os.path.exists(TOKEN_FILE):
        sys.exit(f"توکن پیدا نشد. توکن رو تو این فایل بذار: {TOKEN_FILE}")
    tok = open(TOKEN_FILE, encoding="utf-8").read().strip()
    if len(tok) < 50:
        sys.exit("فایل توکن خالیه یا ناقصه.")
    return tok


class ApiError(Exception):
    pass


def get(op, path, token, base=BASE, **params):
    params["access_token"] = token
    url = f"{base}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with op.open(url, timeout=40) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Graph errors never contain the token, but the URL does: never print it.
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            msg = ""
        raise ApiError(f"HTTP {e.code}: {msg}".replace(token, "***")) from None
    except urllib.error.URLError as e:
        raise ApiError(f"شبکه: {e.reason} (فیلترشکن/پروکسی روشنه؟)") from None


def media_insights(op, token, media):
    metrics = REEL_METRICS if media.get("media_product_type") == "REELS" else POST_METRICS
    out = {}
    try:
        data = get(op, f"{media['id']}/insights", token, metric=",".join(metrics))["data"]
        for d in data:
            out[d["name"]] = d["values"][0]["value"] if d.get("values") else d.get("total_value", {}).get("value")
    except ApiError:
        # One unsupported metric fails the whole call; fall back to one by one.
        for m in metrics:
            try:
                d = get(op, f"{media['id']}/insights", token, metric=m)["data"][0]
                out[m] = d["values"][0]["value"] if d.get("values") else None
            except (ApiError, KeyError, IndexError):
                out[m] = None
    return out


def post_json(op, path, token, body):
    req = urllib.request.Request(
        f"{BASE}/{path}", data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with op.open(req, timeout=40) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            msg = ""
        raise ApiError(f"HTTP {e.code}: {msg}".replace(token, "***")) from None


def read_dms(op, token, me, limit):
    """Recent conversations and their last messages. Read-only."""
    convs = get(op, "me/conversations", token, platform="instagram", limit=limit,
                fields="id,updated_time,participants").get("data", [])
    out = []
    for c in convs:
        msgs = get(op, c["id"], token,
                   fields="messages.limit(6){id,created_time,from,to,message}"
                   ).get("messages", {}).get("data", [])
        others = [p for p in c.get("participants", {}).get("data", [])
                  if p.get("username") != me]
        out.append({"conversation": c["id"], "updated": c.get("updated_time"),
                    "with": others[0] if others else {}, "messages": msgs})
    return out


def dms_report(convs, me):
    now = datetime.now(TEHRAN).strftime("%Y-%m-%d %H:%M")
    lines = [f"# دایرکت‌های @{me} — {now} (تهران)", "",
             "> فقط خونده شده. هیچ پیامی بدون تأیید صاحب پیج فرستاده نمی‌شه.",
             "> جواب فقط تا ۲۴ ساعت بعد از آخرین پیام طرف ممکنه (پنجره‌ی پیام اینستاگرام).", ""]
    for c in convs:
        who = c["with"].get("username") or c["with"].get("id", "?")
        lines.append(f"## @{who} · گیرنده: `{c['with'].get('id', '?')}` · آخرین: {c['updated']}")
        for m in reversed(c["messages"]):
            sender = (m.get("from") or {}).get("username", "?")
            mark = "⬅️" if sender != me else "➡️"
            lines.append(f"- {mark} {m.get('created_time', '')[:16]} · {m.get('message') or '[پیوست/استیکر]'}")
        lines.append("")
    return "\n".join(lines) + "\n"


def first_line(caption):
    line = (caption or "").strip().split("\n")[0]
    return line if len(line) <= 70 else line[:67] + "…"


def fmt(n):
    return "—" if n is None else f"{n:,}"


def report(profile, rows):
    reels = [r for r in rows if r["type"] == "REELS" and r["m"].get("views")]
    med = statistics.median([r["m"]["views"] for r in reels]) if reels else None
    now = datetime.now(TEHRAN).strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# آمار اینستاگرام @{profile.get('username')} — {now} (تهران)",
        "",
        f"فالوور: {fmt(profile.get('followers_count'))} · پست‌ها: {fmt(profile.get('media_count'))}"
        f" · نوع حساب: {profile.get('account_type')}",
        "",
        "> فقط‌خواندنی، از API رسمی Meta. «ضریب» = ویو تقسیم بر میانه‌ی ویو ریلزهای همین حساب.",
        "> «فرستادن به ازای ریچ» قوی‌ترین سیگنال پخش به غیرفالوورهاست.",
        "",
        "| تاریخ | خط اول کپشن | ویو | ضریب | ریچ | میانگین تماشا (ث) | فرستادن | فرستادن/ریچ | ذخیره | کامنت | لایک |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        m = r["m"]
        views, reach, shares = m.get("views"), m.get("reach"), m.get("shares")
        mult = f"{views / med:.1f}×" if (med and views) else "—"
        spr = f"{shares / reach * 100:.1f}٪" if (reach and shares is not None) else "—"
        avg = m.get("ig_reels_avg_watch_time")
        avg_s = f"{avg / 1000:.1f}" if avg else "—"
        lines.append(f"| {r['date']} | {r['line']} | {fmt(views)} | {mult} | {fmt(reach)} | {avg_s}"
                     f" | {fmt(shares)} | {spr} | {fmt(m.get('saved'))} | {fmt(m.get('comments'))}"
                     f" | {fmt(m.get('likes'))} |")
    lines += ["", "پیوندها:"] + [f"- {r['date']} · {r['permalink']}" for r in rows]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Read-only Instagram insights.")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--dms", action="store_true", help="read recent DMs into dms.md")
    ap.add_argument("--send", metavar="RECIPIENT_ID", help="send one reply (needs --text-file and --yes)")
    ap.add_argument("--text-file", help="UTF-8 file with the reply text")
    ap.add_argument("--yes", action="store_true", help="confirm: you approved this exact message")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")   # Persian on a Windows console
        except Exception:
            pass

    if args.send and not (args.text_file and args.yes):
        sys.exit("ارسال فقط با --text-file و --yes (یعنی خودت همین متن رو تأیید کردی).")

    token = read_token()
    op = opener()

    if args.refresh:
        # The refresh endpoint is unversioned. On any error the old token is
        # left untouched.
        r = get(op, "refresh_access_token", token, base="https://graph.instagram.com",
                grant_type="ig_refresh_token")
        new = r.get("access_token")
        if new:
            with open(TOKEN_FILE, "w", encoding="utf-8") as fh:
                fh.write(new)
            days = int(r.get("expires_in", 0)) // 86400
            print(f"توکن تمدید شد، {days} روز اعتبار. (خودِ توکن چاپ نمی‌شه)")
        return

    try:
        profile = get(op, "me", token,
                      fields="user_id,username,account_type,followers_count,follows_count,media_count")
    except ApiError as e:
        sys.exit(f"وصل نشد. {e}")
    if args.check:
        print(f"وصلی به @{profile.get('username')} · {profile.get('account_type')} · "
              f"{fmt(profile.get('followers_count'))} فالوور")
        return

    if args.send:
        text = open(args.text_file, encoding="utf-8").read().strip()
        try:
            r = post_json(op, "me/messages", token,
                          {"recipient": {"id": args.send}, "message": {"text": text}})
        except ApiError as e:
            sys.exit(f"فرستاده نشد. {e}")
        print(f"فرستاده شد ✓ (شناسه‌ی پیام: {r.get('message_id', '?')})")
        return

    if args.dms:
        me = profile.get("username")
        try:
            convs = read_dms(op, token, me, min(args.limit, 25))
        except ApiError as e:
            sys.exit(f"دایرکت‌ها خونده نشد. {e}\n(دسترسی instagram_business_manage_messages تو توکن هست؟)")
        path = os.path.join(HOME, "dms.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(dms_report(convs, me))
        print(f"{len(convs)} گفت‌وگو خونده شد ← {path}")
        return

    media = get(op, "me/media", token, limit=min(args.limit, 50),
                fields="id,caption,media_type,media_product_type,timestamp,permalink,"
                       "like_count,comments_count").get("data", [])
    rows = []
    for item in media:
        ts = datetime.strptime(item["timestamp"], "%Y-%m-%dT%H:%M:%S%z").astimezone(TEHRAN)
        rows.append({
            "id": item["id"], "type": item.get("media_product_type"),
            "date": ts.strftime("%Y-%m-%d"), "line": first_line(item.get("caption")).replace("|", "/"),
            "permalink": item.get("permalink"), "m": media_insights(op, token, item),
        })
        print(f"  {rows[-1]['date']}  {rows[-1]['type']:<6} {rows[-1]['line'][:40]}", file=sys.stderr)

    os.makedirs(HOME, exist_ok=True)
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write(report(profile, rows))
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump({"profile": profile, "media": rows,
                   "fetched": datetime.now(TEHRAN).isoformat()}, fh, ensure_ascii=False, indent=2)
    print(f"\n{len(rows)} پست خونده شد ← {OUT_MD}")


if __name__ == "__main__":
    main()
