r"""Does 'related words' search beat plain search? Run it and read the numbers.

Run from the project folder with the project's Python:
    .\.venv\Scripts\python.exe testing_setup\eval_expand.py

It builds a throwaway in-memory database (your real thoughts.db is never touched),
runs every query two ways, and compares them against the answers you wrote below.

IMPORTANT: THOUGHTS and QUERIES are a STARTER SET. Replace as many as you can with
your own wording, because that is what the search has to cope with in real use.
The "relevant" lists are the thoughts YOU judge should come back (0-based positions).
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import sqlite3

import thought  # the real search() / related() / keywords() functions

THOUGHTS = [
    "nervous about the interview on Friday",             # 0
    "need to buy groceries: milk, eggs, bread",          # 1
    "idea: a recursion visualizer for my portfolio",     # 2
    "forgot to dry my clothes on the balcony",           # 3
    "revise SQL joins before the lab exam",              # 4
    "feeling anxious about falling behind my batch",     # 5
    "call mom about the weekend plan",                   # 6
    "maybe use a binary heap for the scheduling problem",# 7
    "laptop battery is dying, order a new charger",      # 8
    "can't sleep, brain keeps replaying the demo",       # 9
    "read about how indexes speed up database queries",  # 10
    "tea at the cafe near college was really good",      # 11
    "submit the internship form before the deadline",    # 12
    "what if my wifi drops during the online test",      # 13
    "idea: weekly review screen for the dump app",       # 14
    "email the professor about an extension",            # 15
]

# (query, [positions of thoughts that SHOULD come back])
QUERIES = [
    ("worried job", [0, 5]),
    ("food shopping", [1]),
    ("tired at night", [9]),
    ("database speed", [10]),        # control: shares a word with its answer
    ("exam prep", [4]),              # control
    ("project ideas", [2, 14]),      # plain search misses: "ideas" is not a prefix of "idea"
    ("phone charger", [8]),          # control
    ("deadline", [12, 15]),
    ("scared test fails", [13]),
    ("family", [6]),
    ("internet problem", [13]),
    ("restaurant", [11]),
]


def main():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    thought.init_db(con)
    for t in THOUGHTS:
        thought.add(con, t)  # ids become position + 1 in a fresh database

    print("warm-up (downloads/loads the model once so it is not counted)...")
    thought.related(["warm"])

    rows = []
    for q, rel_pos in QUERIES:
        relevant = {p + 1 for p in rel_pos}
        words = thought.keywords(q)

        plain = {r["id"] for r in thought.search(con, words)}

        start = time.perf_counter()
        extra = thought.related(words)  # includes load + inference + unload, as in real use
        secs = time.perf_counter() - start
        more = {r["id"] for r in thought.search(con, extra, exclude=plain)} if extra else set()
        combined = plain | more

        rows.append(dict(q=q, extra=extra, secs=secs, rel=relevant, plain=plain, comb=combined))
        print(f"\n{q!r}  related={extra}  ({secs:.1f}s)")
        print(f"  plain    found {len(plain & relevant)}/{len(relevant)}, extra noise {len(plain - relevant)}")
        print(f"  expanded found {len(combined & relevant)}/{len(relevant)}, extra noise {len(combined - relevant)}")

    total_rel = sum(len(r["rel"]) for r in rows)
    def tally(key):
        hit = sum(len(r[key] & r["rel"]) for r in rows)
        noise = sum(len(r[key] - r["rel"]) for r in rows)
        return hit, noise

    ph, pn = tally("plain")
    ch, cn = tally("comb")
    print("\n================ SUMMARY ================")
    print(f"queries: {len(rows)}   relevant thoughts to find: {total_rel}")
    print(f"plain search   : found {ph}/{total_rel}, irrelevant results {pn}")
    print(f"with related   : found {ch}/{total_rel}, irrelevant results {cn}")
    print(f"queries where related words found something plain missed: "
          f"{sum(1 for r in rows if (r['comb'] & r['rel']) - (r['plain'] & r['rel']))}")
    print(f"queries where related words only added noise: "
          f"{sum(1 for r in rows if (r['comb'] - r['plain']) and not ((r['comb'] & r['rel']) - (r['plain'] & r['rel'])))}")
    avg = sum(r['secs'] for r in rows) / len(rows)
    print(f"average related-words time (load + answer + unload): {avg:.1f}s, "
          f"slowest {max(r['secs'] for r in rows):.1f}s")
    print("\nSmall test, my own judgement of 'relevant'. Report counts, not percentages.")


if __name__ == "__main__":
    main()