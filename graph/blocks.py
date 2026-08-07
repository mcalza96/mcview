"""Collapse what does not decide: a linear chain is ONE fact, not fourteen.

This is a compiler's basic-block condensation, with one rule that cannot be skipped:
**only a chain where every node has one entry and one exit gets collapsed**. A node that
receives from two sides is not part of a chain — it is a confluence, and fusing it merges
two stories into a single one that never happened.

FOUR CUTS, and none of them is redundant:

    proven fork      the flow really chooses there (branches of the same conditional)
    confluence       in-degree > 1 — mandatory, it is the rule above
    seam             the system changes hands; not a branch, but an edge
    lane change      responsibility changes — without this a block spans four modules
                     and cannot be given a name

The fourth is what separates a correct condensation from a useful one. With only the first
two, a 102-node route collapses to two or three: technically impeccable and unreadable.
With all four, the block gets an honest name — "from `grounded_answer` to `gather`,
14 steps, all inside Retrieval".

WHERE IT IS USED AND WHERE IT IS NOT. In MAP views, yes: there the question is the shape of
the system and a linear chain is a single fact. In the sequence and the journey, NO: there
the question is what happens, and the steps ARE the content — collapsing them leaves
"14 things happen", which is exactly what those views exist not to say.
"""
from __future__ import annotations

from collections import defaultdict


def condense(nodes: list[dict], edges: list[dict], lane_of,
             forking: set[str]) -> tuple[list[dict], list[dict]]:
    by_id = {n["id"]: n for n in nodes}
    out_edges: dict[str, list[dict]] = defaultdict(list)
    in_edges: dict[str, list[dict]] = defaultdict(list)
    for a in edges:
        if a["from"] in by_id and a["to"] in by_id:
            out_edges[a["from"]].append(a)
            in_edges[a["to"]].append(a)

    def cuts(prev: str, nxt: str, edge: dict) -> bool:
        return (len(in_edges[nxt]) != 1
                or len(out_edges[prev]) != 1
                or prev in forking
                or bool(edge.get("seam"))
                or lane_of(prev) != lane_of(nxt))

    # Block heads: everything that cannot be anyone's continuation.
    heads = []
    for n in nodes:
        i = n["id"]
        inbound = in_edges[i]
        if len(inbound) != 1 or cuts(inbound[0]["from"], i, inbound[0]):
            heads.append(i)

    seen: set[str] = set()
    blocks: list[dict] = []
    of_block: dict[str, int] = {}
    for head in heads:
        if head in seen:
            continue
        chain = [head]
        seen.add(head)
        current = head
        while len(out_edges[current]) == 1:
            a = out_edges[current][0]
            nxt = a["to"]
            if nxt in seen or cuts(current, nxt, a):
                break
            chain.append(nxt)
            seen.add(nxt)
            current = nxt
        k = len(blocks)
        for i in chain:
            of_block[i] = k
        blocks.append({"idx": k, "members": chain})

    # Pure cycles: nothing outside reaches into them, so they have no head. They are
    # emitted as their own block instead of vanishing — a cycle that is not drawn is a hole.
    for n in nodes:
        if n["id"] not in seen:
            of_block[n["id"]] = len(blocks)
            blocks.append({"idx": len(blocks), "members": [n["id"]], "cycle": True})
            seen.add(n["id"])

    out_nodes = []
    for b in blocks:
        ms = [by_id[i] for i in b["members"]]
        head, tail = ms[0], ms[-1]
        n = dict(head)
        n["id"] = f"block{b['idx']}"
        n["members"] = [m["id"] for m in ms]
        n["steps"] = len(ms)
        n["name"] = (head["name"] if len(ms) == 1
                     else f"{head['name']} → {tail['name']}")
        # A block's mass is its HEAD's, not the sum: the flow enters once and walks the
        # chain; summing would count the same step once per link.
        n["pct"] = head.get("pct", 0.0)
        n["lane"] = lane_of(head["id"])
        n["collapsed"] = len(ms) > 1
        out_nodes.append(n)

    weight: dict[tuple[int, int], dict] = {}
    for a in edges:
        if a["from"] not in of_block or a["to"] not in of_block:
            continue
        i, j = of_block[a["from"]], of_block[a["to"]]
        if i == j:
            continue
        k = (i, j)
        prev = weight.get(k)
        if prev is None:
            weight[k] = {"from": f"block{i}", "to": f"block{j}",
                         "weight": a.get("weight", 1), "seam": a.get("seam", False)}
            if "p" in a:
                weight[k]["p"] = a["p"]
        else:
            prev["weight"] = max(prev["weight"], a.get("weight", 1))
            prev["seam"] = prev["seam"] or a.get("seam", False)
    return out_nodes, list(weight.values())
