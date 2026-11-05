"""Offline self-test: classifier + extractor on synthetic data (no network).

Run:  python -m onchain_scanner.selftest
"""

from __future__ import annotations

import tempfile
from dataclasses import asdict

from .classify import classify, normalize
from .extract import from_transaction, from_log
from .store import Store


def _w(hex_body: str) -> str:
    return normalize(hex_body)  # type: ignore[return-value]


def check(label: str, got: str, want: str) -> bool:
    ok = got == want
    print(f"  [{'OK ' if ok else 'XX '}] {label:22s} -> {got}"
          + ("" if ok else f"   (expected {want})"))
    return ok


def main() -> int:
    passed = 0
    total = 0

    cases = [
        ("zero",
         "0" * 64, "zero"),
        ("bool true",
         "0" * 63 + "1", "bool"),
        ("address word",
         "000000000000000000000000d8da6bf26964af9d7eed9e03e53415d37aa96045",
         "address"),
        ("small amount",
         f"{10**18:064x}", "uint256_small"),
        ("timestamp",
         f"{1_700_000_000:064x}", "timestamp"),
        ("selector word",
         "a9059cbb" + "0" * 56, "selector_word"),
        ("bytes32 string",
         b"Hello".hex() + "0" * (64 - len(b"Hello".hex())), "bytes32_string"),
        ("opaque digest",
         "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
         "opaque_hash"),
    ]
    for label, word, want in cases:
        total += 1
        c = classify(_w(word))
        passed += check(label, c.category, want)

    # context: tx hash match
    total += 1
    txh = "a" * 64
    c = classify(txh, known_tx_hashes=frozenset({txh}))
    passed += check("tx hash (context)", c.category, "tx_hash")

    # extractor: a transfer(address,uint256) calldata
    total += 1
    calldata = ("0x"
                "a9059cbb"
                "000000000000000000000000d8da6bf26964af9d7eed9e03e53415d37aa96045"
                f"{10**18:064x}")
    tx = {"hash": "0x" + "b" * 64, "to": "0x" + "c" * 40, "input": calldata}
    founds = from_transaction("ethereum", 100, tx)
    ok = len(founds) == 2 and founds[0].selector == "0xa9059cbb"
    print(f"  [{'OK ' if ok else 'XX '}] extract calldata      -> "
          f"{len(founds)} words, selector {founds[0].selector}")
    passed += ok

    # extractor: a log with one indexed topic + data word
    total += 1
    log = {
        "address": "0x" + "d" * 40,
        "topics": ["0x" + "e" * 64, "0x" + "f" * 64],
        "data": "0x" + f"{42:064x}",
        "transactionHash": "0x" + "b" * 64,
    }
    lf = from_log("ethereum", 100, log["transactionHash"], log)
    ok = len(lf) == 3 and lf[0].source == "log_topic" and lf[-1].source == "log_data"
    print(f"  [{'OK ' if ok else 'XX '}] extract log           -> {len(lf)} words")
    passed += ok

    # store round-trip: build rows the way scanner.scan_block does, persist,
    # read back, and confirm the `word` column is populated (not NULL).
    total += 1
    with tempfile.TemporaryDirectory() as d:
        st = Store(f"{d}/t.db")
        rows = []
        for f in founds:
            c = classify(f.hex64)
            r = asdict(f)
            r["word"] = r.pop("hex64")
            r["category"], r["note"], r["value_dec"] = c.category, c.note, c.value_dec
            rows.append(r)
        st.add_many(rows)
        got = st.conn.execute(
            "SELECT COUNT(*) FROM bytes32_hits WHERE word IS NOT NULL AND word != ''"
        ).fetchone()[0]
        n = st.export_csv(f"{d}/t.csv")
        st.close()
    ok = got == len(founds) and n == len(founds) and got > 0
    print(f"  [{'OK ' if ok else 'XX '}] store round-trip      -> "
          f"{got}/{len(founds)} rows with word, csv {n}")
    passed += ok

    print("-" * 50)
    print(f"{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
