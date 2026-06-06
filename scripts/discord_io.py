# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Alfred's Discord bot I/O (REST API v10, stdlib only). Run from repo root.

Usage:
  uv run scripts/discord_io.py read --channel alfred --limit 100
  uv run scripts/discord_io.py post --channel meal-plan --content "text"
  cat long.md | uv run scripts/discord_io.py post --channel meal-plan
"""
import argparse
import json
import os
import pathlib
import sys
import urllib.request

API = "https://discord.com/api/v10"
MAX_LEN = 2000
ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def request(method: str, path: str, payload: dict | None = None):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode() if payload else None,
        headers={
            "Authorization": f"Bot {os.environ['DISCORD_BOT_TOKEN']}",
            "Content-Type": "application/json",
            "User-Agent": "Alfred (private household agent, 1.0)",
        },
        method=method,
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def split_message(text: str, limit: int = MAX_LEN) -> list[str]:
    """Split text into <=limit chunks, preferring newline boundaries."""
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


def channel_id(name: str) -> str:
    config = json.loads((ROOT / "config.json").read_text())
    cid = config["channels"].get(name, "")
    if not cid:
        sys.exit(f"config.json has no id for channel '{name}' — run Task 3 setup")
    return cid


def cmd_read(args) -> None:
    msgs = request(
        "GET", f"/channels/{channel_id(args.channel)}/messages?limit={args.limit}"
    )
    out = [
        {
            "author": m["author"].get("global_name") or m["author"]["username"],
            "bot": m["author"].get("bot", False),
            "timestamp": m["timestamp"],
            "content": m["content"],
            "attachments": [a["url"] for a in m.get("attachments", [])],
        }
        for m in reversed(msgs)  # API returns newest first; emit oldest first
    ]
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    print()


def cmd_post(args) -> None:
    content = args.content if args.content is not None else sys.stdin.read()
    chunks = split_message(content.strip())
    for chunk in chunks:
        request(
            "POST",
            f"/channels/{channel_id(args.channel)}/messages",
            {"content": chunk},
        )
    print(f"posted {len(chunks)} message(s) to #{args.channel}")


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("read", help="read recent messages, oldest first, as JSON")
    r.add_argument("--channel", required=True)
    r.add_argument("--limit", type=int, default=50)
    r.set_defaults(fn=cmd_read)
    p = sub.add_parser("post", help="post content (auto-splits at 2000 chars)")
    p.add_argument("--channel", required=True)
    p.add_argument("--content", help="message text; omit to read from stdin")
    p.set_defaults(fn=cmd_post)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
