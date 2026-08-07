# -----------------------------------------------------------------------------
# mcview/ — portable entropy module
# -----------------------------------------------------------------------------
"""LEVEL 2 — from structural signals to GUARDS.

Level 1 (`mcview.py`) is a GRAPH question: who references whom. It finds what is left over
—dead, duplicated, badly grouped— and does not tell a `require_admin` from a CRUD.

This module is a PREDICATE question: **what does this code promise**. It does not replace
level 1, it CONSUMES it: the graph says where to look, the predicate says what to ask.

WHY THIS SHAPE AND NOT "A SECURITY AUDIT"
----------------------------------------------------
"Look for security bugs" is an infinite space and cannot be walked. What can be walked is one
CLASS: **a guard whose failure mode is silence.** It does not crash — it stops protecting and
looks identical to one that works.

Measured in one day over this monorepo, five real findings and all five of that kind:

  · an allowlist that came out EMPTY when given a YAML scalar — and empty meant "no
    restriction", so the bot replied in every channel;
  · four cross-tenant leaks where the isolation was a manual `.eq('tenant_id')` that
    10 de 31 paths no escribieron;
  · an SSRF re-check calling two nonexistent functions (`NameError`);
  · a write deny-list missing `auth.json` and `config.yaml` — the agent could overwrite
    its own guardrails — with its tests RED since the day they were written;
  · a typecheck that aborted before looking at a single line and exited with code 0.

Three of the five came out of LEVEL 1 signals (duplication, undefined names). What was
missing was not another metric: it was knowing which of those findings were GUARDS.

THE FOUR QUESTIONS
--------------------
    1. how many COPIES does it have?   a rule in N places is N places to forget it
    2. what is its PERMISSIVE state?   if empty/None/exception let through, it is fail-open
    3. is there a CHOKEPOINT or is it applied by hand?
    4. does it have RED tests?         a red test over a guard IS the finding

Questions 1 and 4 are implemented here, computed with what level 1 already measures. 2 and 3
need analysis of their own and are waiting for these two to prove they pay off.

WHAT IT DOES NOT DO
-----------
It does not find a logic bug inside a guard applied everywhere and with green tests. The
classifier is lexical: it has false positives (a `validate_email`) and false negatives (a
guard with a domain name). **It generates candidates, not verdicts** — like level 1, and for
the same reason.
"""
from __future__ import annotations

import re

# Names that PROMISE something. A guard verb, a list noun, or a gate suffix.
# Deliberately broad: a false positive costs one read, a false negative costs a fail-open
# nobody looks at.
_VERBS = r"require|verify|validate|sanitize|authorize|authenticate|ensure|assert|enforce|guard|check"
_LISTS = r"allow|denied|deny|blocked|blocklist|allowlist|whitelist|permitted|forbidden|disabled"
_GATES = r"gate|guard|policy|permission|acl|scope|tenant|secret|token|credential|auth"

_RE_GUARD = re.compile(
    rf"(?:^|_)(?:{_VERBS})(?:_|$|[A-Z])"      # require_admin, verifyUser, _validate
    rf"|(?:^|_)is_\w*(?:{_LISTS})"            # is_write_denied, is_allowed
    # The list word starts a token and admits ANY suffix. The previous
    # previous one required the word to end there (`allow(_|$)`) and therefore did NOT
    # recognize `_slack_allowed_channels` or `_telegram_allowed_chats` — the two allowlists
    # whose fail-open motivated this module. Validating against the known cases BEFORE using
    # it is what exposed that.
    rf"|(?:^|_)(?:{_LISTS})\w*"              # allowed_chats, denied_paths, blocklist
    rf"|(?:^|_)(?:{_GATES})(?:_|$)",         # _gate, tenant_id, auth_mode
    re.IGNORECASE)


def is_guard(name: str) -> bool:
    """Does the name PROMISE a guard?

    Purely lexical and on purpose: a semantic analyzer for "this is a guard" is a project in
    itself, and this classifier only has to beat reading 5,000 symbols by hand. Measured over
    the five real findings, all five match.
    """
    return bool(_RE_GUARD.search(name or ""))


def duplicated(grupos_dup: list, project) -> list[dict]:
    """QUESTION 1 — guards with more than one copy.

    It takes level 1's duplication groups and keeps the ones that are guards. An
    authorization rule in N copies does not cost lines: it costs that loosening ONE leaves
    the other N-1 looking perfect, and that the diff of the changed one shows nothing odd.
    """
    out = []
    for g in grupos_dup:
        names = [project.symbols[s].name for s in g] if not isinstance(g[0], str) or ":" in str(g[0]) else list(g)
        prot = [n for n in names if is_guard(n)]
        if prot:
            out.append({"copias": len(names), "guards": sorted(set(prot)),
                          "todos": sorted(set(names))})
    return sorted(out, key=lambda x: -x["copias"])


def with_red_tests(rojos: list[str]) -> list[dict]:
    """QUESTION 4 — red tests whose subject is a guard.

    It is the cheapest question and the highest-yielding, because **a red test over a guard is
    not noise: it is the guard saying it does not protect**. The measured case: 9 tests
    demanded that the write deny-list cover `auth.json` and `config.yaml`; they had failed
    since the day they were written because that coverage was never implemented. They stayed
    red for months, mixed in with 46 others, and that is why nobody read them.

    `rojos` are lines of the form `FAILED path::Class::test_name`. Classification uses the
    test's name AND its path: `test_cross_profile_guard.py` promises as much as the test.
    """
    out = []
    for line in rojos:
        m = re.match(r"FAILED\s+(\S+?)::(.+)$", line.strip())
        if not m:
            continue
        path, caso = m.groups()
        signals = [t for t in (path.split("/")[-1], caso) if is_guard(t)]
        if signals:
            out.append({"path": path, "caso": caso})
    return out


def report(rojos: list[str] | None = None, grupos_dup: list | None = None,
            project=None) -> str:
    """Both questions, in a readable report. Every finding is a CANDIDATE."""
    lines = ["", "  NIVEL 2 — guards", ""]

    if rojos is not None:
        hits = with_red_tests(rojos)
        lines.append(f"  ── RED tests over a guard: {len(hits)} of {len(rojos)}")
        if hits:
            lines.append("     a red test here is not noise: it is the guard saying it does not protect")
        for h in hits[:20]:
            lines.append(f"       {h['path'].split('/')[-1]:38s} {h['caso'][:60]}")
        if len(hits) > 20:
            lines.append(f"       … {len(hits)-20} more")
        lines.append("")

    if grupos_dup is not None and project is not None:
        dups = duplicated(grupos_dup, project)
        lines.append(f"  ── guards DUPLICADAS: {len(dups)} grupos")
        if dups:
            lines.append("     a rule in N copies is N places to loosen it unnoticed")
        for d in dups[:15]:
            lines.append(f"       ×{d['copias']}  {', '.join(d['guards'][:4])}")
        lines.append("")

    lines.append("  Candidates, NOT verdicts: the classifier is lexical and fails in both")
    lines.append("  directions. Every finding gets read before it is believed.")
    return "\n".join(lines)
