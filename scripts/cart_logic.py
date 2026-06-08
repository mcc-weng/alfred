# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Pure cart logic: subtotal, threshold status, pending.json validation.

No I/O beyond the optional load/save helpers. Imported by `cart` mode and Plan B.
"""
import json
import pathlib

VALID_STATUS = {"proposed", "approved", "filled", "failed"}
REQUIRED = ("week_of", "status", "woolies", "asianpantry", "fresh_asian")


def subtotal(items: list[dict]) -> float:
    return round(sum(i["qty"] * i["price"] for i in items), 2)


def threshold_status(sub: float, threshold: int) -> dict:
    met = sub >= threshold
    return {"met": met, "gap": round(max(0.0, threshold - sub), 2)}


def validate_pending(p: dict) -> None:
    missing = [k for k in REQUIRED if k not in p]
    if missing:
        raise ValueError(f"pending.json missing keys: {missing}")
    if p["status"] not in VALID_STATUS:
        raise ValueError(f"bad status {p['status']!r}; allowed {sorted(VALID_STATUS)}")
    for section in ("woolies", "asianpantry"):
        if "items" not in p[section] or "threshold" not in p[section]:
            raise ValueError(f"{section} needs items + threshold")
    for item in p["woolies"]["items"]:
        if "stockcode" not in item or "qty" not in item:
            raise ValueError(f"woolies item missing stockcode/qty: {item}")


def save_pending(p: dict, path: pathlib.Path) -> None:
    validate_pending(p)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(p, ensure_ascii=False, indent=1))


def load_pending(path: pathlib.Path) -> dict:
    p = json.loads(path.read_text())
    validate_pending(p)
    return p


def main() -> None:
    import argparse
    import sys
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("path")
    a = ap.parse_args()
    if a.cmd == "validate":
        try:
            load_pending(pathlib.Path(a.path))
        except (ValueError, OSError, json.JSONDecodeError) as e:
            print(f"INVALID: {e}", file=sys.stderr)
            sys.exit(1)
        print("OK")


if __name__ == "__main__":
    main()
