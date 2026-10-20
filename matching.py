"""Rule-based reuse suggestions and buyer matching. No ML model involved."""
from dataclasses import dataclass, field

import db


@dataclass
class Suggestion:
    reuse_key: str
    cautions: list[str] = field(default_factory=list)


@dataclass
class BuyerMatch:
    buyer: object
    score: int
    reasons: list[str]


def suggest_reuse(residue_key: str, condition: str, path=None) -> list[Suggestion]:
    """Uses allowed for this residue in this condition, in priority order."""
    out = []
    for rule in db.get_reuse_rules(residue_key, path):
        if condition in rule["conditions"].split("|"):
            cautions = [c for c in rule["cautions"].split("|") if c]
            out.append(Suggestion(rule["reuse_key"], cautions))
    return out


def match_buyers(residue_key: str, quantity_kg: float, condition: str,
                 district: str, price_per_kg: float | None, path=None) -> list[BuyerMatch]:
    """Hard filters: same residue and an accepted condition.
    Score (0-100): district 40/10, quantity 35/25/5, price 25/15/0."""
    matches = []
    for b in db.get_buyers_for(residue_key, path):
        if condition not in b["accepted_conditions"].split("|"):
            continue
        score, reasons = 0, []

        if b["district"].strip().lower() == district.strip().lower():
            score += 40
            reasons.append("same_district")
        else:
            score += 10
            reasons.append("other_district")

        lo, hi = b["min_qty_kg"] or 0, b["max_qty_kg"]
        if quantity_kg < lo:
            score += 5
            reasons.append("qty_under")
        elif hi is not None and quantity_kg > hi:
            score += 25
            reasons.append("qty_over")
        else:
            score += 35
            reasons.append("qty_ok")

        cap = b["max_price_per_kg"]
        if not price_per_kg:
            score += 15
            reasons.append("price_unknown")
        elif cap is None or price_per_kg <= cap:
            score += 25
            reasons.append("price_ok")
        else:
            reasons.append("price_high")

        matches.append(BuyerMatch(b, score, reasons))
    return sorted(matches, key=lambda m: m.score, reverse=True)
