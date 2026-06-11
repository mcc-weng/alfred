# /// script
# requires-python = ">=3.11"
# dependencies = ["discord.py", "google-genai"]
# ///
"""Alfred's ears: Discord gateway daemon.

#alfred messages → debounce → brain (chat or ritual mode) → reply in-channel.
Backfills missed messages on connect. Ritual mode = multi-turn transcript replay
persisted to .runtime/ritual.json (survives daemon restarts).
"""
import asyncio
import datetime
import fcntl
import json
import os
import pathlib
import re
import time

import discord

import brain
import recipe_intake
from discord_io import load_env, split_message

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNTIME = ROOT / ".runtime"
CFG = json.loads((ROOT / "config.json").read_text())
ALFRED = int(CFG["channels"]["alfred"])
DEBOUNCE = CFG.get("debounce_seconds", 8)
RITUAL_TIMEOUT = CFG.get("ritual_timeout_hours", 3) * 3600
CHAT_IDLE = CFG.get("chat_idle_minutes", 20) * 60

TRIGGER = re.compile(
    r"\b(plan the week|alfred plan)\b|排菜單|規劃本週|規劃這週", re.IGNORECASE
)
CART_TRIGGER = re.compile(r"裝車|裝購物車|fill the cart", re.IGNORECASE)
APPROVE_TRIGGER = re.compile(r"裝吧|送出購物車|確認裝車|確認送出|全加|approve cart|confirm cart", re.IGNORECASE)
SENTINEL = "<<<RITUAL_COMPLETE>>>"


def is_ritual_trigger(text: str) -> bool:
    return bool(TRIGGER.search(text))


def is_cart_trigger(text: str) -> bool:
    return bool(CART_TRIGGER.search(text))


def is_approve_trigger(text: str) -> bool:
    return bool(APPROVE_TRIGGER.search(text))


def ritual_complete(text: str) -> bool:
    return SENTINEL in text


def strip_sentinel(text: str) -> str:
    return text.replace(SENTINEL, "").strip()


def render_turns(turns: list[dict]) -> str:
    out = []
    for t in turns:
        out.append(t["content"] if t["role"] == "user" else f"Alfred: {t['content']}")
    return "\n".join(out)


# Recipe-source links (IG reel/post, YouTube). Used to DETERMINISTICALLY fetch the
# caption for the link in THIS message before the brain runs — so the brain enriches
# the exact dropped recipe instead of anchoring on a recipe in the chat history
# (the 2026-06-10 bug: a 鹽水雞 reel was dropped, brain re-saved milk-mochi from history).
RECIPE_URL_RE = re.compile(
    r"https?://(?:www\.|m\.)?(?:"
    r"instagram\.com/(?:reel|reels|p|tv)/"
    r"|youtube\.com/(?:watch|shorts)"
    r"|youtu\.be/"
    r")[^\s]*",
    re.IGNORECASE,
)


def extract_recipe_url(text: str) -> str | None:
    m = RECIPE_URL_RE.search(text)
    return m.group(0) if m else None


def format_caption_injection(url: str, caption: dict) -> str:
    """Inline annotation appended to the message content the brain sees, carrying the
    pre-fetched recipe for `url` plus a hard guard against history-anchoring."""
    if caption.get("error"):
        return (f"\n[系統:已嘗試抓取 {url} 但沒拿到文字食譜({caption['error'][:80]})。"
                f"→ 改用 recipe_intake.py frames 看影格,或請對方截圖/說菜名。]")
    return (
        f"\n[系統已自動抓取「這則訊息裡的連結」{url} 的食譜 — "
        f"**請只用這一份來做食譜卡,絕對不要從聊天記錄挪用別道菜**:\n"
        f"title: {caption.get('title', '')}\n"
        f"is_thin: {caption.get('is_thin', False)}\n"
        f"description:\n{caption.get('description', '')}\n]"
    )


def format_understanding_injection(url: str, result: dict) -> str | None:
    """Inject Gemini's comprehensive video understanding for the brain. Returns None on
    error so the caller can fall back to the caption."""
    if result.get("error") or not result.get("understanding"):
        return None
    return (
        f"\n[系統已用 Gemini 看完「這則訊息裡的影片」{url},完整理解如下 — "
        f"**請只用這一份來做食譜卡,絕對不要從聊天記錄挪用別道菜**;"
        f"把其中「原文食譜」那段的食材/步驟原文放進 📌 原始食譜區塊:\n"
        f"{result['understanding']}\n]"
    )


class Transcript:
    """Ritual conversation persisted to disk — replay-based multi-turn."""

    def __init__(self, path: pathlib.Path, timeout: float | None = None):
        self.path = path
        self._timeout = timeout  # None means "use RITUAL_TIMEOUT global at call time"

    def _effective_timeout(self) -> float:
        return self._timeout if self._timeout is not None else RITUAL_TIMEOUT

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {"started": None, "turns": []}

    def active(self) -> bool:
        d = self._load()
        if not d["turns"]:
            return False
        if time.time() - (d["started"] or 0) > self._effective_timeout():
            return False
        return True

    def turns(self) -> list[dict]:
        return self._load()["turns"]

    def append(self, role: str, content: str) -> None:
        d = self._load()
        if not d["turns"]:
            d["started"] = time.time()
        d["turns"].append({"role": role, "content": content})
        d["turns"] = d["turns"][-200:]
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
        self.chat_thread = Transcript(RUNTIME / "chat.json", timeout=CHAT_IDLE)
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
        # cart is one-shot (only when no active ritual); ritual precedence below
        ritual_now = self.transcript.active() or any(
            is_ritual_trigger(l["content"]) for l in lines
        )
        cart_now = not self.transcript.active() and any(
            is_cart_trigger(l["content"]) or is_approve_trigger(l["content"]) for l in lines
        )
        ritual_done = False
        try:
            async with channel.typing():
                if cart_now:
                    history = await self._recent_history(channel, {m.id for m in batch})
                    reply = await asyncio.to_thread(
                        brain.run_brain, "cart", history, lines
                    )
                elif ritual_now:
                    reply, ritual_done = await self._ritual_reply(lines)
                else:
                    reply = await self._chat_reply(channel, batch, lines)
        except Exception as e:  # noqa: BLE001 — daemon must not die on one bad turn
            print(f"BRAIN ERROR: {e}", flush=True)
            await channel.send("🤵 Hit a snag thinking about that — try me again "
                               "in a minute. (Logged for Mike.)")
            self._mark_seen(batch[-1].id)
            return
        for chunk in split_message(reply):
            await channel.send(chunk)
        self._mark_seen(batch[-1].id)
        if cart_now:
            await self._maybe_fill_if_awake()
        if ritual_done:
            await self._auto_propose_cart(channel, batch)

    async def _maybe_fill_if_awake(self) -> None:
        pending = ROOT / "state" / "carts" / "pending.json"
        try:
            status = json.loads(pending.read_text()).get("status") if pending.exists() else None
        except Exception:
            status = None
        if status == "approved":
            # awake path: best-effort kick; fill_runner.sh is the real idempotency guard.
            # (fill_runner.sh is created in v2b Task 2; until then this no-ops harmlessly.)
            await asyncio.create_subprocess_exec(
                "bash", str(ROOT / "scripts" / "fill_runner.sh"),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)

    async def _inject_recipe_context(self, lines: list[dict]) -> None:
        """For any IG/YT link, pre-fetch the recipe BEFORE the brain — Gemini watches the
        video (richest); fall back to caption if Gemini errors/times-out/has no key. Either
        way the brain enriches the EXACT dropped recipe, never one from chat history."""
        for line in lines:
            url = extract_recipe_url(line["content"])
            if not url:
                continue
            try:
                g = await asyncio.to_thread(recipe_intake.cmd_gemini, url)
            except Exception as e:  # noqa: BLE001
                g = {"error": str(e)[:120]}
            inj = format_understanding_injection(url, g)
            if inj is None:  # Gemini unavailable → deterministic caption fallback
                try:
                    cap = await asyncio.to_thread(recipe_intake.cmd_caption, url)
                except Exception as e:  # noqa: BLE001 — never let intake prep crash the turn
                    print(f"recipe pre-fetch failed for {url}: {e}", flush=True)
                    continue
                inj = format_caption_injection(url, cap)
            line["content"] += inj

    async def _chat_reply(self, channel, batch, lines: list[dict]) -> str:
        if not self.chat_thread.active():
            self.chat_thread.clear()  # idle → fresh conversation
        prior = render_turns(self.chat_thread.turns()[-30:])  # bounded
        if prior:
            history = [{"author": "", "content": prior}]
        else:
            history = await self._recent_history(channel, {m.id for m in batch})  # cold-start fallback
        batch_text = "\n".join(f"{l['author']}: {l['content']}" for l in lines)  # store original — no caption bloat
        await self._inject_recipe_context(lines)  # deterministic: Gemini/caption pre-fetch before the brain
        reply = await asyncio.to_thread(brain.run_brain, "chat", history, lines)
        self.chat_thread.append("user", batch_text)
        self.chat_thread.append("assistant", reply)
        return reply

    async def _ritual_reply(self, lines: list[dict]) -> tuple[str, bool]:
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
        return reply, done

    async def _auto_propose_cart(self, channel, batch) -> None:
        """After the ritual completes, auto-run cart mode to propose the cart."""
        plans_dir = ROOT / "state" / "plans"
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        plan_files = sorted(plans_dir.glob("*.md")) if plans_dir.exists() else []
        if not plan_files or not plan_files[-1].stem.startswith(today):
            print("auto-cart: no fresh plan written today — skipping (ritual may have errored)", flush=True)
            return
        try:
            await channel.send("🛒 菜單鎖定!我來看看要買什麼…")
            history = await self._recent_history(channel, {m.id for m in batch})
            reply = await asyncio.to_thread(
                brain.run_brain, "cart", history,
                [{"author": "小當家", "content": "(ritual just finished — 自動裝車:讀最新計畫,配對商品,提出採買提案,status 先寫 proposed)"}])
            for chunk in split_message(reply):
                await channel.send(chunk)
        except Exception as e:  # never let the auto-chain crash the daemon
            print(f"AUTO-CART ERROR: {e}", flush=True)
            await channel.send("🛒 (自動裝車沒成功,你直接說「裝車」我再來一次。)")


def _acquire_single_instance_lock():
    """Refuse to start if another listener is already running.

    Holds an exclusive flock on .runtime/listener.lock for the whole process
    lifetime. The OS releases the lock the instant this process dies — even on
    SIGKILL — so there is no stale-lock to clean up and a crashed daemon never
    blocks its own launchd respawn. The caller MUST keep the returned handle
    alive; closing it drops the lock. This is what stops a stray
    `uv run scripts/listener.py` from overlapping launchd's copy and
    double-processing every message (the bug found in the 2026-06-09 dry run).
    """
    # Open WITHOUT truncating so a stray instance that bails never wipes the
    # holder's diagnostic PID. Only after we own the lock do we rewrite it.
    fd = os.open(RUNTIME / "listener.lock", os.O_RDWR | os.O_CREAT, 0o644)
    lock_file = os.fdopen(fd, "r+")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("listener: another instance already holds .runtime/listener.lock "
              "— exiting to avoid duplicate message processing", flush=True)
        raise SystemExit(0)
    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(f"{os.getpid()}\n")
    lock_file.flush()
    return lock_file


def main() -> None:
    load_env()
    RUNTIME.mkdir(exist_ok=True)
    _lock = _acquire_single_instance_lock()  # noqa: F841 — held for process lifetime
    attach_dir = RUNTIME / "attachments"
    if attach_dir.exists():
        cutoff = time.time() - 14 * 86400
        for f in attach_dir.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
    AlfredListener().run(os.environ["DISCORD_BOT_TOKEN"], log_handler=None)


if __name__ == "__main__":
    main()
