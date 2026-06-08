# /// script
# requires-python = ">=3.11"
# dependencies = ["certifi"]
# ///
"""Alfred plumbing self-test — live read-only APIs, pure logic, guards.

ZERO side effects on real state: no real Woolies fill, no Discord post,
no LLM call, no writes to real inbox.md or state/carts/pending.json.

Exit 0 if all (non-skipped) checks pass, 1 otherwise.
"""
import http.cookiejar
import json
import pathlib
import ssl
import subprocess
import sys
import tempfile
import urllib.request

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
PROJECT_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

results: list[tuple[str, bool, str]] = []   # (label, passed, reason)
skipped: list[str] = []


def record(label: str, passed: bool, reason: str = "") -> None:
    mark = "PASS" if passed else f"FAIL {reason}"
    print(f"  {'PASS' if passed else 'FAIL'} [{label}] {reason if not passed else ''}")
    results.append((label, passed, reason))


def skip(label: str, reason: str) -> None:
    print(f"  SKIP [{label}] {reason}")
    skipped.append(label)


# ---------------------------------------------------------------------------
# Check 1: Woolies search (live)
# ---------------------------------------------------------------------------
def check_woolies_search() -> None:
    label = "woolies_search"
    try:
        import woolies_search as ws
        data = ws.fetch("brown onion")
        products = ws.parse_products(data)
        ranked = ws.rank(products, "brown onion")
        assert len(ranked) >= 3, f"expected ≥3 products, got {len(ranked)}"
        top = ranked[0]
        assert "onion" in top["name"].lower(), (
            f"top product name {top['name']!r} doesn't contain 'onion'"
        )
        assert isinstance(top["stockcode"], int), (
            f"stockcode {top['stockcode']!r} is not int"
        )
        assert isinstance(top["price"], (int, float)), (
            f"price {top['price']!r} is not numeric"
        )
        record(label, True)
    except AssertionError as e:
        record(label, False, str(e))
    except Exception as e:
        record(label, False, f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Check 2: Asian Pantry search (live)
# ---------------------------------------------------------------------------
_ap_variant_id: int | None = None   # passed to check 3


def check_asianpantry_search() -> None:
    global _ap_variant_id
    label = "asianpantry_search"
    try:
        import asianpantry as ap
        results_ap = ap.search("tapioca starch", 3)
        assert len(results_ap) >= 1, f"expected ≥1 result, got {len(results_ap)}"
        # prefer available item to reduce check-3 flakiness
        item = next((r for r in results_ap if r.get("available")), results_ap[0])
        assert isinstance(item["variant_id"], int), (
            f"variant_id {item['variant_id']!r} is not int"
        )
        assert isinstance(item["price"], float), (
            f"price {item['price']!r} is not float"
        )
        _ap_variant_id = item["variant_id"]
        record(label, True)
    except AssertionError as e:
        record(label, False, str(e))
    except Exception as e:
        record(label, False, f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Check 3: Asian Pantry permalink resolves (live, ephemeral session)
# ---------------------------------------------------------------------------
def check_asianpantry_permalink() -> None:
    label = "asianpantry_permalink"
    if _ap_variant_id is None:
        record(label, False, "skipped — check 2 produced no variant_id")
        return
    try:
        import asianpantry as ap
        url = ap.permalink([(_ap_variant_id, 2)])

        # Fresh throwaway cookie jar — NOT Mike's session
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=_SSL_CTX),
            urllib.request.HTTPCookieProcessor(jar),
        )
        opener.addheaders = [("User-Agent",
                              "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                              "AppleWebKit/605.1")]

        # Visit permalink URL (follows redirects, plants session cookie in jar)
        with opener.open(url, timeout=20) as _:
            pass

        # Fetch the session cart via same opener/jar
        cart_url = "https://asianpantry.com.au/cart.js"
        with opener.open(cart_url, timeout=20) as r:
            cart = json.load(r)

        cart_items = cart.get("items", [])
        match = next(
            (i for i in cart_items
             if i.get("id") == _ap_variant_id or i.get("variant_id") == _ap_variant_id),
            None,
        )
        assert match is not None, (
            f"variant_id {_ap_variant_id} not found in cart.js items; "
            f"got {[i.get('id') for i in cart_items]}"
        )
        assert match.get("quantity") == 2, (
            f"expected qty 2, got {match.get('quantity')}"
        )
        record(label, True)
    except AssertionError as e:
        record(label, False, str(e))
    except Exception as e:
        record(label, False, f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Check 4: cart_logic finalize + validate (pure, temp path)
# ---------------------------------------------------------------------------
def check_cart_logic() -> None:
    label = "cart_logic"
    tmp = pathlib.Path(tempfile.mktemp(suffix=".json", prefix="alfred_selftest_"))
    try:
        import cart_logic as cl

        sample = {
            "week_of": "2026-06-09",
            "status": "proposed",
            "woolies": {
                "items": [
                    {"stockcode": 123456, "name": "Brown Onion", "qty": 2, "price": 2.10},
                    {"stockcode": 789012, "name": "Garlic Bulb", "qty": 1, "price": 1.50},
                ],
                "threshold": 75,
            },
            "asianpantry": {
                "items": [],
                "threshold": 130,
                "permalink": None,
            },
            "fresh_asian": [],
        }
        tmp.write_text(json.dumps(sample))

        # Run finalize via subprocess on temp path (safe — never touches real pending.json)
        proc = subprocess.run(
            ["uv", "run", str(SCRIPTS_DIR / "cart_logic.py"), "finalize", str(tmp)],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_DIR),
        )
        assert proc.returncode == 0, (
            f"finalize exited {proc.returncode}: {proc.stderr.strip()}"
        )

        # Validate the output
        updated = json.loads(tmp.read_text())
        w_sub = updated["woolies"]["est_subtotal"]
        assert isinstance(w_sub, (int, float)), f"woolies est_subtotal not numeric: {w_sub}"
        expected = round(2 * 2.10 + 1.50, 2)
        assert w_sub == expected, f"est_subtotal {w_sub} != expected {expected}"

        ts = updated["woolies"]["threshold_status"]
        assert "met" in ts and "gap" in ts, f"threshold_status malformed: {ts}"

        # validate_pending should accept the updated cart
        cl.validate_pending(updated)
        record(label, True)
    except AssertionError as e:
        record(label, False, str(e))
    except Exception as e:
        record(label, False, f"{type(e).__name__}: {e}")
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Check 5: capture append (pure, temp path)
# ---------------------------------------------------------------------------
def check_capture() -> None:
    label = "capture_append"
    tmp = pathlib.Path(tempfile.mktemp(suffix=".md", prefix="alfred_selftest_"))
    try:
        import capture

        # Write to a temp path — never the real inbox
        capture.append_note(tmp, "2026-06-09", "lesson", "selftest smoke test")

        content = tmp.read_text()
        assert "selftest smoke test" in content, "note text not found in temp inbox"
        assert "2026-06-09" in content, "date not found in temp inbox"
        assert "[lesson]" in content, "kind tag not found in temp inbox"
        record(label, True)
    except AssertionError as e:
        record(label, False, str(e))
    except Exception as e:
        record(label, False, f"{type(e).__name__}: {e}")
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Check 6: fill guard (safe) — only run when pending.json is absent/non-approved
# ---------------------------------------------------------------------------
def check_fill_guard() -> None:
    label = "fill_guard"
    pending = PROJECT_DIR / "state" / "carts" / "pending.json"

    # Safety check: read pending.json BEFORE deciding whether to run fill_runner
    try:
        if pending.exists():
            p = json.loads(pending.read_text())
            status = p.get("status", "")
        else:
            status = "absent"
    except Exception:
        status = "unreadable"

    if status == "approved":
        skip(label, "pending.json is approved — skipping to avoid triggering real fill")
        return

    # Safe to run: non-approved/absent pending.json → fill_runner exits 0 immediately
    try:
        proc = subprocess.run(
            ["bash", str(SCRIPTS_DIR / "fill_runner.sh")],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_DIR),
            timeout=15,
        )
        assert proc.returncode == 0, (
            f"fill_runner.sh exited {proc.returncode}: "
            f"stdout={proc.stdout[:200]!r} stderr={proc.stderr[:200]!r}"
        )
        # The "nothing to fill" message goes to the log file, not stdout.
        # Exit 0 is the contract we're verifying here.
        record(label, True)
    except AssertionError as e:
        record(label, False, str(e))
    except subprocess.TimeoutExpired:
        record(label, False, "fill_runner.sh timed out (10s) — did not exit promptly")
    except Exception as e:
        record(label, False, f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Check 7: .env deny present + Grep not in CHAT_TOOLS
# ---------------------------------------------------------------------------
def check_env_deny_and_chat_tools() -> None:
    label = "env_deny_and_chat_tools"
    try:
        settings_path = PROJECT_DIR / ".claude" / "settings.json"
        assert settings_path.exists(), f"settings.json not found at {settings_path}"
        settings = json.loads(settings_path.read_text())
        deny_list = settings.get("permissions", {}).get("deny", [])

        # Must have at least one Read(.env…) denial
        env_denials = [d for d in deny_list if "Read(" in d and ".env" in d]
        assert env_denials, (
            f"no Read(.env…) denial found in settings.json deny list; got: {deny_list}"
        )

        # brain.py: extract CHAT_TOOLS value from file text; don't import the module
        brain_path = SCRIPTS_DIR / "brain.py"
        assert brain_path.exists(), f"brain.py not found at {brain_path}"
        brain_text = brain_path.read_text()

        # Find the CHAT_TOOLS assignment line and extract the value
        import re
        m = re.search(r'^CHAT_TOOLS\s*=\s*["\']([^"\']+)["\']', brain_text, re.MULTILINE)
        assert m, "CHAT_TOOLS assignment not found in brain.py"
        chat_tools_value = m.group(1)
        assert "Grep" not in chat_tools_value, (
            f"Grep found in CHAT_TOOLS={chat_tools_value!r}; brain.py should not allow Grep"
        )

        record(label, True)
    except AssertionError as e:
        record(label, False, str(e))
    except Exception as e:
        record(label, False, f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("=== Alfred selftest ===")
    print()

    checks = [
        ("1. woolies_search (live)",          check_woolies_search),
        ("2. asianpantry_search (live)",       check_asianpantry_search),
        ("3. asianpantry_permalink (live)",    check_asianpantry_permalink),
        ("4. cart_logic finalize+validate",    check_cart_logic),
        ("5. capture_append (temp)",           check_capture),
        ("6. fill_guard (safe)",               check_fill_guard),
        ("7. env_deny_and_chat_tools",         check_env_deny_and_chat_tools),
    ]

    for title, fn in checks:
        print(f"[{title}]")
        fn()
        print()

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)

    print("-" * 40)
    if skipped:
        print(f"SKIPPED: {', '.join(skipped)}")
    print(f"selftest: {passed}/{total} passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
