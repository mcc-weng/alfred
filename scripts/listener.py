# /// script
# requires-python = ">=3.11"
# dependencies = ["discord.py"]
# ///
"""Alfred's ears: Discord gateway daemon.

#alfred messages → debounce → brain (chat or ritual mode) → reply in-channel.
Backfills missed messages on connect. Ritual mode = multi-turn transcript replay
persisted to .runtime/ritual.json (survives daemon restarts).
"""
import asyncio
import json
import pathlib
import re
import time

import discord

import brain
from discord_io import load_env, split_message

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNTIME = ROOT / ".runtime"
CFG = json.loads((ROOT / "config.json").read_text())
ALFRED = int(CFG["channels"]["alfred"])
DEBOUNCE = CFG.get("debounce_seconds", 8)
RITUAL_TIMEOUT = CFG.get("ritual_timeout_hours", 3) * 3600

TRIGGER = re.compile(
    r"\b(plan the week|alfred plan)\b|排菜單|規劃本週|規劃這週", re.IGNORECASE
)
CART_TRIGGER = re.compile(r"裝車|裝購物車|fill the cart", re.IGNORECASE)
SENTINEL = "<<<RITUAL_COMPLETE>>>"


def is_ritual_trigger(text: str) -> bool:
    return bool(TRIGGER.search(text))


def is_cart_trigger(text: str) -> bool:
    return bool(CART_TRIGGER.search(text))


def ritual_complete(text: str) -> bool:
    return SENTINEL in text


def strip_sentinel(text: str) -> str:
    return text.replace(SENTINEL, "").strip()


def render_turns(turns: list[dict]) -> str:
    out = []
    for t in turns:
        out.append(t["content"] if t["role"] == "user" else f"Alfred: {t['content']}")
    return "\n".join(out)


class Transcript:
    """Ritual conversation persisted to disk — replay-based multi-turn."""

    def __init__(self, path: pathlib.Path):
        self.path = path

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {"started": None, "turns": []}

    def active(self) -> bool:
        d = self._load()
        if not d["turns"]:
            return False
        if time.time() - (d["started"] or 0) > RITUAL_TIMEOUT:
            return False
        return True

    def turns(self) -> list[dict]:
        return self._load()["turns"]

    def append(self, role: str, content: str) -> None:
        d = self._load()
        if not d["turns"]:
            d["started"] = time.time()
        d["turns"].append({"role": role, "content": content})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(d, ensure_ascii=False, indent=1))

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


class AlfredListener(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.pending: list[discord.Message] = []
        self.flush_task: asyncio.Task | None = None
        self.brain_lock = asyncio.Lock()
        self.seen_ids: set[int] = set()
        self.transcript = Transcript(RUNTIME / "ritual.json")
        self.last_seen_file = RUNTIME / "last_seen"

    # -- persistence of last processed message id (for backfill)
    def _last_seen(self) -> int | None:
        if self.last_seen_file.exists():
            return int(self.last_seen_file.read_text().strip())
        return None

    def _mark_seen(self, message_id: int) -> None:
        self.last_seen_file.parent.mkdir(parents=True, exist_ok=True)
        self.last_seen_file.write_text(str(message_id))

    async def on_ready(self):
        print(f"READY as {self.user}", flush=True)
        channel = self.get_channel(ALFRED)
        last = self._last_seen()
        if channel and last:
            async for m in channel.history(after=discord.Object(id=last),
                                           oldest_first=True, limit=50):
                await self.on_message(m)

    async def on_message(self, message: discord.Message):
        if message.author.bot or message.channel.id != ALFRED:
            return
        if message.id in self.seen_ids:
            return
        self.seen_ids.add(message.id)
        self.pending.append(message)
        if self.flush_task is not None:
            self.flush_task.cancel()
        self.flush_task = asyncio.create_task(self._debounced_flush())

    async def _debounced_flush(self):
        try:
            await asyncio.sleep(DEBOUNCE)
        except asyncio.CancelledError:
            return
        self.flush_task = None  # past the cancellable window — never cancel in-flight work
        batch, self.pending = self.pending, []
        if batch:
            async with self.brain_lock:
                await self._handle(batch)

    async def _to_lines(self, batch: list[discord.Message]) -> list[dict]:
        lines = []
        for m in batch:
            content = m.content
            for a in m.attachments:
                dest = RUNTIME / "attachments" / f"{a.id}-{a.filename}"
                dest.parent.mkdir(parents=True, exist_ok=True)
                await a.save(dest)
                content += f" [attached file saved at: {dest}]"
            lines.append({"author": m.author.display_name, "content": content})
        return lines

    async def _recent_history(self, channel, exclude: set[int], limit: int = 15) -> list[dict]:
        out = []
        async for m in channel.history(limit=limit, oldest_first=False):
            if m.id in exclude:
                continue
            who = "Alfred" if m.author.bot else m.author.display_name
            out.append({"author": who, "content": m.content})
        return list(reversed(out))

    async def _handle(self, batch: list[discord.Message]):
        channel = batch[0].channel
        lines = await self._to_lines(batch)
        batch_text = "\n".join(f"{l['author']}: {l['content']}" for l in lines)
        ritual_now = self.transcript.active() or any(
            is_ritual_trigger(l["content"]) for l in lines
        )
        cart_now = (
            not self.transcript.active()
            and any(is_cart_trigger(l["content"]) for l in lines)
        )
        try:
            async with channel.typing():
                if cart_now:
                    history = await self._recent_history(channel, {m.id for m in batch})
                    reply = await asyncio.to_thread(
                        brain.run_brain, "cart", history, lines
                    )
                elif ritual_now:
                    reply = await self._ritual_reply(lines)
                else:
                    history = await self._recent_history(channel, {m.id for m in batch})
                    reply = await asyncio.to_thread(
                        brain.run_brain, "chat", history, lines
                    )
        except Exception as e:  # noqa: BLE001 — daemon must not die on one bad turn
            print(f"BRAIN ERROR: {e}", flush=True)
            await channel.send("🤵 Hit a snag thinking about that — try me again "
                               "in a minute. (Logged for Mike.)")
            self._mark_seen(batch[-1].id)
            return
        for chunk in split_message(reply):
            await channel.send(chunk)
        self._mark_seen(batch[-1].id)

    async def _ritual_reply(self, lines: list[dict]) -> str:
        if not self.transcript.active():
            self.transcript.clear()  # fresh trigger after expiry/abandonment: never inherit a stale transcript
        batch_text = "\n".join(f"{l['author']}: {l['content']}" for l in lines)
        prior = render_turns(self.transcript.turns())
        self.transcript.append("user", batch_text)
        prompt = brain.build_prompt(
            "ritual",
            [{"author": "", "content": prior}] if prior else [],
            lines,
        )
        reply = await asyncio.to_thread(
            brain.run_brain, "ritual", [], [], prompt
        )
        done = ritual_complete(reply)
        reply = strip_sentinel(reply)
        self.transcript.append("assistant", reply)
        if done:
            self.transcript.clear()
        return reply


def main() -> None:
    load_env()
    import os
    RUNTIME.mkdir(exist_ok=True)
    attach_dir = RUNTIME / "attachments"
    if attach_dir.exists():
        cutoff = time.time() - 14 * 86400
        for f in attach_dir.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
    AlfredListener().run(os.environ["DISCORD_BOT_TOKEN"], log_handler=None)


if __name__ == "__main__":
    main()
