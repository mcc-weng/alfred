# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Save an extracted recipe to the cookbook + queue it as a craving for the ritual.

Chat mode's recipe-intake write-seam — the ONLY recipe writer. Narrow blast radius:
writes one state/cookbook/<slug>.md and appends one craving line to state/inbox.md
(via capture.append_note, DRY). Dedupes by slug: if the cookbook file already exists it
is left untouched (preserving any verdicts) and no craving is re-queued.

Usage:
  echo "<recipe body markdown>" | uv run scripts/save_recipe.py \
      --title "鮮奶麻糬甜湯" --slug "milk-mochi-dessert-soup" \
      --source "https://www.instagram.com/reel/DUNy6_ADXyp/" \
      --by "ball" --kind "IG reel"

Body (stdin) = the 繁中 card minus the H1 title: a meta line, **Ingredients:** …,
**Steps:** … . The script wraps it with the title, a **Source:** line, and ## Verdicts.
"""
import argparse
import datetime
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import capture  # reuse append_note for inbox writes (DRY)

ROOT = pathlib.Path(__file__).resolve().parent.parent
COOKBOOK = ROOT / "state" / "cookbook"
INBOX = ROOT / "state" / "inbox.md"


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def cookbook_markdown(title: str, body: str, source: str, by: str,
                      kind: str, date: str) -> str:
    src = f"**Source:** {source} ({kind}, shared by {by}) · saved {date}"
    return f"# {title}\n\n{body.strip()}\n\n{src}\n\n## Verdicts\n"


def craving_note(title: str, slug: str, by: str, kind: str) -> str:
    return f"想做{title} — 已存 cookbook/{slug}.md ({by}, {kind})"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--title", required=True)
    p.add_argument("--slug", default="")
    p.add_argument("--source", required=True)
    p.add_argument("--by", default="someone")
    p.add_argument("--kind", default="link")
    p.add_argument("--variant", action="store_true",
                   help="swapped-ingredient variant — skip queuing a craving")
    args = p.parse_args()

    slug = slugify(args.slug or args.title)
    if not slug:
        sys.exit("empty slug — pass an ASCII --slug (the title may be non-Latin)")
    body = sys.stdin.read().strip()
    if not body:
        sys.exit("empty recipe body on stdin")

    path = COOKBOOK / f"{slug}.md"
    if path.exists():
        print(f"already in cookbook: {slug}")
        return
    date = datetime.datetime.now().strftime("%Y-%m-%d")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        cookbook_markdown(args.title, body, args.source, args.by, args.kind, date),
        encoding="utf-8",
    )
    if not args.variant:
        capture.append_note(INBOX, date, "craving",
                            craving_note(args.title, slug, args.by, args.kind))
        print(f"saved cookbook/{slug}.md + queued craving")
    else:
        print(f"saved cookbook/{slug}.md (variant — no craving)")


if __name__ == "__main__":
    main()
