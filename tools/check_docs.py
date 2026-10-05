"""Cross-reference consistency check over docs/.

Usage: python tools/check_docs.py  (from any directory)

Checks that every cited ID (policy rules, transitions, invariants, gold checks, fixture and
audit tests, hard negatives, golden flags, monitoring signals, matrix rows and gaps), every
backticked repo path and every "`docs/x.md` section N" reference resolves, that every policy
rule has a Tier (T1, T2 or T3) and that the "Rules by tier" counts in the policy header match
the Tier column. Exits 1 if any of those is broken. Version strings that are not current, and T1
rules that no test in backend/tests or ml/tests cites yet, are reported for review only and do
not affect the exit code.
"""

import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Paths cited in the docs for artifacts that are planned but do not exist yet.
NOT_YET = {
    "docs/data_card.md",
    "docs/writeup.md",
    "backend/.env",
    # Created at runtime and git-ignored (fallback queue of POL-REL-03).
    "backend/var",
    "backend/var/cola_casos.jsonl",
    "ml/tests/fixtures/update",
    "ml/tests/fixtures/update/expected",
    "ml/tests/pipelines/gold/test_incremental_update.py",
}

# Current contract and document versions.
CURRENT = {
    "cards-synthetic": "0.8",
    "sm": "0.4",
    "gold": "0.2",
    "fresh": "0.2",
    "audit": "0.2",
    "eval-report": "0.2",
    "eval-plan": "0.3",
    "golden": "0.5",
    "intents": "1.0",
    "ops": "0.3",
}
# Lines that legitimately cite older versions (change logs, history notes).
HISTORY = re.compile(
    r"(Changes in|change log|Change log|^\| 0\.\d |added in|\(new in|\(changed in|provisional name"
    r"|≤ `sm|of `gold-0\.1`|rewords|in `gold-0\.1`)",
    re.I,
)

# Provisional intent names replaced by the taxonomy in docs/intents.md.
OLD_ONLY = ["why_blocked", "dispute_charge", "talk_to_human", "unblock_card"]
OLD_SHARED = ["list_cards", "list_transactions", "describe_transaction", "block_card"]


def load_docs():
    paths = glob.glob("docs/*.md") + glob.glob("docs/contracts/*.md") + glob.glob("docs/contracts/*.json")
    text = {}
    for p in sorted(paths):
        with open(p, encoding="utf-8") as f:
            text[p.replace("\\", "/")] = f.read()
    return text


def headings(body):
    found = set()
    for line in body.splitlines():
        m = re.match(r"#{2,4} (\d+[a-z]?(?:\.\d+)*)\.?\s", line)
        if m:
            found.add(m.group(1))
    return found


def main():
    # Windows consoles default to cp1252, which cannot print some characters in the docs.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.chdir(ROOT)
    text = load_docs()
    problems = []

    def defined(pattern, doc):
        return set(re.findall(pattern, text[doc], flags=re.M))

    # --- definitions ---------------------------------------------------------
    pol = defined(r"^\| (POL-[A-Z]+-\d{2}) \|", "docs/policy_cards.md")
    trans = defined(r"^\| ([TG]-\d{2}) \|", "docs/contracts/state_machine.md")
    inv = defined(r"^\| (INV-\d{2}) \|", "docs/contracts/state_machine.md")
    gq = defined(r"^\| (GQ-\d{2}) \|", "docs/contracts/gold_tables.md")
    fx = defined(r"^\| (FX-\d) \|", "docs/contracts/freshness_policy.md")
    at = defined(r"^\| (AT-\d) \|", "docs/contracts/audit_log.md")
    alp = defined(r"^\| (AL-P\d) \|", "docs/contracts/audit_log.md")
    hn = defined(r"^\| (HN-\d{2}) \|", "docs/intents.md")
    mon = defined(r"^\| (M-\d+) \|", "docs/operations.md")
    gaps = defined(r"^\| (G-\d{1,2}) [A-Z]", "docs/requirements_matrix.md")
    flags = defined(r"^\| (F-\d{2}) \|", "docs/golden_conversations.md")
    matrix_rows = defined(r"^\| ([A-Z]\d?-\d+) \|", "docs/requirements_matrix.md")
    print(
        f"defined: POL {len(pol)}, T/G {len(trans)}, INV {len(inv)}, GQ {len(gq)}, FX {len(fx)}, "
        f"AT {len(at)}, AL-P {len(alp)}, HN {len(hn)}, M {len(mon)}, gaps {len(gaps)}, "
        f"flags {len(flags)}, matrix rows {len(matrix_rows)}"
    )

    # --- tiers: every rule row ends with T1/T2/T3, and the header counts match ---------------------
    policy = text["docs/policy_cards.md"]
    tiers = {}
    for line in policy.splitlines():
        m = re.match(r"^\| (POL-[A-Z]+-\d{2}) \|", line)
        if m:
            tier = line.rstrip().rstrip("|").rsplit("|", 1)[1].strip()
            if tier not in ("T1", "T2", "T3"):
                problems.append(f"docs/policy_cards.md: {m.group(1)} has no Tier (last cell {tier[:30]!r})")
            tiers[m.group(1)] = tier
    counts = {t: sum(1 for v in tiers.values() if v == t) for t in ("T1", "T2", "T3")}
    stated = re.search(
        r"^\| Rules by tier \| T1[^*]*\*\*(\d+)\*\*[^*]*T2[^*]*\*\*(\d+)\*\*[^*]*T3[^*]*\*\*(\d+)\*\*[^*]*total \*\*(\d+)\*\*",
        policy,
        flags=re.M,
    )
    if not stated:
        problems.append("docs/policy_cards.md: no 'Rules by tier' row in the header")
    elif tuple(map(int, stated.groups())) != (counts["T1"], counts["T2"], counts["T3"], len(tiers)):
        problems.append(
            f"docs/policy_cards.md: 'Rules by tier' says {'/'.join(stated.groups())} (T1/T2/T3/total), "
            f"the Tier column gives {counts['T1']}/{counts['T2']}/{counts['T3']}/{len(tiers)}"
        )
    print(f"tiers: T1 {counts['T1']}, T2 {counts['T2']}, T3 {counts['T3']}")

    # --- rule IDs, with short forms ("POL-ANS-01 to 18", "POL-ACT-01, 02 and 06", "POL-DEC-90/91")
    seq = re.compile(r"POL-([A-Z]+)-(\d{2})((?:(?:\s*,\s*|\s+and\s+|\s+to\s+|/)\d{2}\b)*)")
    for doc, t in text.items():
        for m in seq.finditer(t):
            area = m.group(1)
            for n in [m.group(2)] + re.findall(r"\d{2}", m.group(3)):
                rid = f"POL-{area}-{n}"
                if rid not in pol:
                    problems.append(f'{doc}: unknown rule {rid} (in "{m.group(0)}")')

    def check(pattern, known, label, docs=None):
        for doc, t in text.items():
            if docs and doc not in docs:
                continue
            for m in re.finditer(pattern, t):
                if m.group(1) not in known:
                    problems.append(f"{doc}: unknown {label} {m.group(1)}")

    check(r"\b(T-\d{2})\b", trans, "transition")
    check(r"\b(G-0\d)\b", trans, "global transition")
    check(r"\b(INV-\d{2})\b", inv, "invariant")
    check(r"\b(GQ-\d{2})\b", gq, "gold check")
    check(r"\b(FX-\d)\b", fx, "fixture test")
    check(r"\b(AT-\d)\b", at, "audit test")
    check(r"\b(AL-P\d)\b", alp, "audit privacy rule")
    check(r"\b(HN-\d{2})\b", hn, "hard negative")
    check(r"\b(F-\d{2})\b", flags, "golden flag")
    check(r"\b(M-\d{1,2})\b", mon, "monitoring signal", docs={"docs/operations.md", "docs/contracts/freshness_policy.md"})
    check(r"\b(G-[1-9]\d?)\b", gaps, "matrix gap")

    # ranges "INV-01 to 13", "GQ-01 to GQ-09": endpoints only (inner IDs are checked when cited)
    for doc, t in text.items():
        for m in re.finditer(r"\b(INV-\d{2}) to (\d{2})\b", t):
            if f"INV-{m.group(2)}" not in inv:
                problems.append(f"{doc}: unknown invariant INV-{m.group(2)} (range)")
        for m in re.finditer(r"\bGQ-\d{2} to GQ-(\d{2})\b", t):
            if f"GQ-{m.group(1)}" not in gq:
                problems.append(f"{doc}: unknown gold check GQ-{m.group(1)} (range)")

    # --- matrix row IDs cited as "row X" / "rows X" ---------------------------
    for doc, t in text.items():
        for m in re.finditer(r"\brows? ((?:[A-Z]\d?-\d+(?:,\s*|\s+and\s+|\s+to\s+)?)+)", t):
            for rid in re.findall(r"[A-Z]\d?-\d+", m.group(1)):
                if rid not in matrix_rows and not rid.startswith(("T-", "G-", "F-", "M-")):
                    problems.append(f"{doc}: unknown matrix row {rid}")

    # --- repo paths -------------------------------------------------------------
    for doc, t in text.items():
        for m in re.finditer(r"`((?:docs|ml|eval|backend|frontend)/[^`\s]+?)`", t):
            path = m.group(1).rstrip("/").split("#")[0]
            if any(c in path for c in "{*<"):
                continue
            if path.startswith(("ml/data", "eval/")) or path in NOT_YET:
                continue
            if not os.path.exists(path):
                problems.append(f"{doc}: missing path {path}")

    # --- section references "`docs/x.md` section N" / "`docs/x.md` N.M" --------
    sec = re.compile(
        r"`(docs/[a-z_/]+\.md)`(?:,? (?:sections?|§) | )(\d+[a-z]?(?:\.\d+)*)"
        r"(?:(?: and | to |, )(\d+[a-z]?(?:\.\d+)*))*"
    )
    for doc, t in text.items():
        for m in sec.finditer(t):
            target = m.group(1)
            if target not in text:
                continue
            hs = headings(text[target])
            for num in re.findall(r"\d+[a-z]?(?:\.\d+)*", m.group(0).split("`", 2)[2]):
                if num not in hs and num.split(".")[0] not in hs:
                    problems.append(f'{doc}: {target} has no section {num} ("{m.group(0)}")')

    # --- provisional intent names used as intents -------------------------------
    for doc, t in text.items():
        for i, line in enumerate(t.splitlines(), 1):
            if doc == "docs/intents.md" and line.startswith("| `"):
                continue  # mapping table from provisional to final names
            for name in OLD_ONLY:
                if name in line and "ejecuta unblock_card" not in line:
                    problems.append(f"{doc}:{i}: provisional intent name {name}")
            for name in OLD_SHARED:
                if re.search(r"(intent|conformal set|conformal_set|top_intent)[^|]{0,25}`?\{?\[?\"?" + name, line):
                    problems.append(f"{doc}:{i}: provisional intent name {name} used as an intent")

    # --- versions that are not current (warnings only) --------------------------
    stale = []
    for doc, t in text.items():
        for i, line in enumerate(t.splitlines(), 1):
            for name, cur in CURRENT.items():
                for m in re.finditer(r"`?\b" + re.escape(name) + r"-(\d+\.\d+)\b", line):
                    if m.group(1) != cur and not HISTORY.search(line):
                        stale.append(f"{doc}:{i}: {name}-{m.group(1)} (current {cur}): {line.strip()[:110]}")

    # --- T1 rules that no test cites yet (review only) ---------------------------
    test_text = ""
    for path in glob.glob("backend/tests/**/*.py", recursive=True) + glob.glob("ml/tests/**/*.py", recursive=True):
        with open(path, encoding="utf-8") as f:
            test_text += f.read()
    untested = sorted(r for r, t in tiers.items() if t == "T1" and not re.search(re.escape(r) + r"\b", test_text))

    print(f"\nproblems: {len(problems)}")
    for p in problems:
        print("  " + p)
    print(f"\nversion strings that are not current (review; history lines excluded): {len(stale)}")
    for p in stale:
        print("  " + p)
    print(f"\nT1 rules not cited by any test in backend/tests or ml/tests (review): {len(untested)} of {counts['T1']}")
    for i in range(0, len(untested), 8):
        print("  " + ", ".join(untested[i : i + 8]))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
