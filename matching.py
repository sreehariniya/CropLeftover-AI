"""Rule-based reuse suggestions and matching between farmers and buyers. No ML model involved."""
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


@dataclass
class ListingMatch:
    listing: object
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


def _score(farmer_district, buyer_district, quantity_kg, min_qty, max_qty, price_per_kg, max_price):
    """Score (0-100): district 40/10, quantity 35/25/5, price 25/15/0."""
    score, reasons = 0, []
    if (buyer_district or "").strip().lower() == (farmer_district or "").strip().lower():
        score += 40
        reasons.append("same_district")
    else:
        score += 10
        reasons.append("other_district")

    lo = min_qty or 0
    if quantity_kg < lo:
        score += 5
        reasons.append("qty_under")
    elif max_qty and quantity_kg > max_qty:
        score += 25
        reasons.append("qty_over")
    else:
        score += 35
        reasons.append("qty_ok")

    if not price_per_kg:
        score += 15
        reasons.append("price_unknown")
    elif not max_price or price_per_kg <= max_price:
        score += 25
        reasons.append("price_ok")
    else:
        reasons.append("price_high")
    return score, reasons


def match_buyers(residue_key: str, quantity_kg: float, condition: str,
                 district: str, price_per_kg: float | None, path=None) -> list[BuyerMatch]:
    """Hard filters: same residue and an accepted condition. Then scored. Registered buyers
    rank above demo buyers when scores tie."""
    matches = []
    for b in db.get_buyers_for(residue_key, path):
        if condition not in b["accepted_conditions"].split("|"):
            continue
        score, reasons = _score(district, b["district"], quantity_kg, b["min_qty_kg"],
                                b["max_qty_kg"], price_per_kg, b["max_price_per_kg"])
        matches.append(BuyerMatch(b, score, reasons))
    return sorted(matches, key=lambda m: (m.score, not m.buyer["is_demo"]), reverse=True)


def match_listings(profile: dict, path=None) -> list[ListingMatch]:
    """For a registered buyer: farmer listings for the residues they buy, in conditions they accept."""
    matches = []
    for key in profile["residues"]:
        for l in db.get_listings_for(key, path):
            if l["condition"] not in profile["conds"]:
                continue
            score, reasons = _score(l["district"], profile["district"], l["quantity_kg"],
                                    profile["min_qty"], profile["max_qty"],
                                    l["price_per_kg"], profile["max_price"])
            matches.append(ListingMatch(l, score, reasons))
    return sorted(matches, key=lambda m: m.score, reverse=True)
