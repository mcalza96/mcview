"""The chain, used for what it was not being used for yet: WHERE the system DECIDES.

PageRank's walker already traverses this graph, but its result is read as a single figure
per node —the mass— and that loses what the chain knows and nobody asked it: **how the flow
splits at each fork**. A turn is not a list of steps, it is a decision tree, and the useful
question at a node is not "how much does it weigh" but "if I get here, where do I go next,
and with what probability?".

That is already in the graph. `weights[(i,j)]` is the quota each reference distributes —an
ambiguous reference splits 1 across its N homonyms rather than giving 1 to each— so
normalized per row it gives the SPLIT of references.

⚠️ And that split IS NOT a branch probability, even though it has the shape of one. The AST
cannot tell a call inside an `if` from the one on the next line: `run_conversation` calls
`_cire_grounded_passthrough` and `_cire_fidelity_flag` once each and comes out 50/50, but it
calls BOTH — it does not choose. For "decision" to mean what it says, you need to know which
BRANCH of which conditional each call is in, and that is not recorded today. Until it is,
this ranks candidates and does not rule; the view's name promises more than the measurement
supports, and the output says so.

TWO QUANTITIES, and both are needed:

    split(i→j)        what fraction of i's references go to j.
    expected visits   how many times j is passed through, starting from the entry, before
                      exiting. It is the PATH's weight, and it is not the same as global
                      mass: a node can be central in the project and absent from this turn.

Expected visits are the classic absorbing chain (the fundamental matrix N = (I−Q)⁻¹), but
computed by iterating rather than inverting: a route's subgraph has hundreds of nodes,
converges in a few passes, and —the deciding factor— **does not need numpy**. Inverting the
matrix would force a dependency onto the tool's main path, and that path runs on the bare
stdlib on purpose.
"""
from __future__ import annotations

from collections import defaultdict

TOLERANCE = 1e-9
MAX_PASSES = 200


def transitions(project, inside: set[str] | None = None,
                seams: set[tuple[str, str]] | None = None
                ) -> dict[str, list[tuple[str, float]]]:
    """`{i: [(j, P(i→j)), …]}` — the matrix row, normalized.

    Restricted to the subgraph if `inside` is passed: a branch's probability depends on what
    it competes with, and branches leaving the route do not compete for this flow.
    Normalizing over the whole graph would give probabilities that do not add up to what is
    on screen.
    """
    # A SEAM IS NOT A TRANSITION. It is "this name is mentioned here", and the weight it
    # carries was put there by me (1.0), not derived from counting anything. Fed into the
    # matrix it becomes flow with a probability, and that produced a very concrete false
    # finding: `_cire_grounded_passthrough` showed up deciding 50/50 between
    # `grounded_answer` and `web_research`. It decides nothing — both names sit there as
    # literals inside `str(_name).endswith(...)`, and the real choice is made by the LLM
    # when it emits the tool call, which no static analysis sees. Two seams of equal weight
    # give 50/50 by construction; the number was the shape of the artifact, not a
    # measurement.
    seams = seams or set()
    raw: dict[str, dict[str, float]] = defaultdict(dict)
    for (i, j), w in project.weights.items():
        if inside is not None and (i not in inside or j not in inside):
            continue
        if i == j or (i, j) in seams:
            continue          # a self-loop is not a decision, and neither is a seam
        raw[i][j] = raw[i].get(j, 0.0) + w
    out: dict[str, list[tuple[str, float]]] = {}
    for i, ds in raw.items():
        total = sum(ds.values())
        if total <= 0:
            continue
        out[i] = sorted(((j, w / total) for j, w in ds.items()),
                        key=lambda kv: -kv[1])
    return out


def expected_visits(P: dict[str, list[tuple[str, float]]], entry: set[str],
                    damping: float = 0.85) -> dict[str, float]:
    """How many times each node is expected to be passed through, starting from the entry.

    This is the absorbing chain: at each step the flow can continue (with probability
    `damping`) or terminate. Without that factor a cycle would make the count diverge — and
    in a call graph cycles are normal, not a defect.

    It iterates until it stops moving. The alternative is inverting (I−Q), which gives the
    same result and requires numpy; here the main path runs with no dependencies.
    """
    # SORTED, and the reason is arithmetic, not cosmetic: `entry` is a set, so the insertion
    # order of `visits` —and therefore of `front`— varied between processes, and floating-point
    # addition is NOT associative. The same chain over the same graph returned shares that
    # differed in the last bits, which is enough to change a rounded percentage and to make two
    # identical runs disagree.
    visits: dict[str, float] = {e: 1.0 for e in sorted(entry)}
    front: dict[str, float] = dict(visits)
    for _ in range(MAX_PASSES):
        nxt: dict[str, float] = defaultdict(float)
        for i, mass in front.items():
            for j, p in P.get(i, ()):
                nxt[j] += mass * p * damping
        movement = sum(nxt.values())
        if movement < TOLERANCE:
            break
        for j, v in nxt.items():
            visits[j] = visits.get(j, 0.0) + v
        front = dict(nxt)
    return visits


def decisions(P: dict[str, list[tuple[str, float]]], visits: dict[str, float],
              threshold: float = 0.98, min_branches: int = 2) -> list[dict]:
    """The nodes where the flow REALLY forks, ordered by how much flow they decide.

    A node with two outputs where one takes 99% is not a decision: it is a step with an
    exception. What matters is where the flow genuinely splits, and that is measured by the
    LARGEST branch's probability — the lower it is, the wider the fan.
    """
    out = []
    for i, branches in P.items():
        if len(branches) < min_branches or branches[0][1] >= threshold:
            continue
        out.append({
            "id": i,
            "branches": branches,
            "largest": branches[0][1],
            # How much flow passes through here × how open the decision is. A node that
            # forks a lot but that almost nothing passes through does not explain the system.
            "weight": visits.get(i, 0.0) * (1.0 - branches[0][1]),
        })
    return sorted(out, key=lambda d: -d["weight"])


def forks(project, inside: set[str] | None = None) -> list[dict]:
    """Where the system really CHOOSES: calls in DIFFERENT branches of the SAME conditional.

    This is what the reference split could not say. Two consecutive calls both execute; two
    calls in the `if` and the `else` of the same conditional are alternatives — the flow goes
    one way or the other, never both. The difference was in the tree and was being thrown
    away: `core.branches` keeps it now, in the same shape the call order was recovered in.

    NO probability is reported. Knowing there are two alternatives does not say how often
    each is taken — that depends on runtime data, and claiming it from the AST would repeat
    the very error this module just corrected. What is asserted is what can be: there is a
    choice here, and these are the options.
    """
    out = []
    for sid, calls in project.call_order.items():
        if inside is not None and sid not in inside:
            continue
        file = project.symbols[sid].file
        # conditional → {branch → [targets]}
        by_cond: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for line, target in calls:
            if inside is not None and target not in inside:
                continue
            mark = project.branches.get(f"{file}:{line}")
            if not mark:
                continue                      # outside every conditional: it is sequential
            cond, _, branch = mark.partition("#")
            by_cond[cond][branch].append(target)
        for cond, branches in by_cond.items():
            if len(branches) < 2:
                continue                      # one branch with calls is not a choice
            out.append({
                "id": sid, "conditional": f"{file}:{cond}",
                "options": [{"branch": r, "targets": sorted(set(ds))}
                            for r, ds in sorted(branches.items())],
            })
    return out


def annotate_with_runtime(forks: list[dict], observed: dict[str, int]) -> list[dict]:
    """Marks which branch is COMPATIBLE with what was seen executing.

    ⚠️ It does not say "this branch ran". The probe records functions, not branches: what is
    known is whether a branch's targets ever executed, and a target may have run called from
    somewhere else. That is why the verdict is «compatible» and not «taken», and something is
    only asserted when one branch has seen targets and the OTHERS have none — there the
    inference stands on its own.

    With both branches seen, the honest answer is "both happen", which also tends to be true:
    a conditional executed many times takes both outputs.
    """
    for b in forks:
        with_, without = [], []
        for o in b["options"]:
            o["seen"] = sum(1 for d in o["targets"] if d in observed)
            (with_ if o["seen"] else without).append(o["branch"])
        if with_ and not without:
            b["runtime"] = f"every branch happens ({', '.join(with_)})"
        elif len(with_) == 1 and without:
            b["runtime"] = (f"compatible with «{with_[0]}»: its targets were seen running "
                            f"and those of {', '.join(without)} were not")
        elif not with_:
            b["runtime"] = "no branch observed — outside the measured window"
        else:
            b["runtime"] = (f"{', '.join(with_)} happen; no evidence for "
                            f"{', '.join(without)}")
    return forks
