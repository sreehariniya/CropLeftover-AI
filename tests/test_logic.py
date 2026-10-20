"""Run with: python -m pytest tests -q   (or: python tests/test_logic.py)"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
import i18n  # noqa: E402
import matching  # noqa: E402

LANGS = list(i18n.LANGUAGES)


def fresh_db():
    path = os.path.join(tempfile.mkdtemp(), "test.db")
    db.init_db(path)
    return path


def test_all_translations_complete():
    for table in (i18n.UI, i18n.RESIDUES, i18n.CONDITIONS, i18n.REUSE, i18n.CAUTIONS, i18n.BUYER_TYPES):
        for key, entry in table.items():
            for lang in LANGS:
                assert entry.get(lang), f"missing {lang} for {key}"


def test_dataset_keys_have_translations():
    path = fresh_db()
    for k in db.residue_keys(path):
        assert k in i18n.RESIDUES
        for rule in db.get_reuse_rules(k, path):
            assert rule["reuse_key"] in i18n.REUSE
            for c in rule["conditions"].split("|"):
                assert c in i18n.CONDITIONS
            for c in rule["cautions"].split("|"):
                assert not c or c in i18n.CAUTIONS
    for b in db.list_buyers(path):
        assert b["buyer_type"] in i18n.BUYER_TYPES
        assert b["is_demo"] == 1
    for reason in ("same_district", "other_district", "qty_ok", "qty_over",
                   "qty_under", "price_ok", "price_high", "price_unknown"):
        assert "reason_" + reason in i18n.UI


def test_seed_is_idempotent():
    path = fresh_db()
    n = len(db.list_buyers(path))
    db.init_db(path)
    assert len(db.list_buyers(path)) == n


def test_moldy_only_compost_or_nothing_unsafe():
    path = fresh_db()
    for k in db.residue_keys(path):
        uses = {s.reuse_key for s in matching.suggest_reuse(k, "moldy", path)}
        assert uses <= {"composting"}, (k, uses)
    # groundnut shells must never be offered as feed when moldy or wet
    for cond in ("moldy", "wet", "fresh_green"):
        uses = {s.reuse_key for s in matching.suggest_reuse("groundnut_shells", cond, path)}
        assert "animal_feed" not in uses


def test_suggestions_carry_cautions():
    path = fresh_db()
    feed = [s for s in matching.suggest_reuse("groundnut_shells", "dry", path) if s.reuse_key == "animal_feed"][0]
    assert "aflatoxin" in feed.cautions and "feed_check" in feed.cautions


def test_matching_filters_and_scores():
    path = fresh_db()
    district = db.get_buyers_for("rice_straw", path)[0]["district"]
    m = matching.match_buyers("rice_straw", 500, "dry", district, None, path)
    assert m and [x.score for x in m] == sorted((x.score for x in m), reverse=True)
    assert all(x.buyer["residue_key"] == "rice_straw" for x in m)
    assert all("dry" in x.buyer["accepted_conditions"].split("|") for x in m)
    assert all(x.score <= 100 for x in m)
    assert "same_district" in m[0].reasons  # same-district buyers rank first
    # wet / moldy residue only matches buyers that accept it
    for cond in ("wet", "moldy"):
        for x in matching.match_buyers("rice_straw", 500, cond, district, None, path):
            assert cond in x.buyer["accepted_conditions"].split("|")
    # price above every buyer's cap is flagged, never scored for price
    hi = matching.match_buyers("rice_straw", 500, "dry", district, 999, path)
    assert all("price_high" in x.reasons for x in hi)
    # quantity below minimum / above maximum are flagged
    tiny = matching.match_buyers("rice_straw", 1, "dry", district, None, path)
    assert any("qty_under" in x.reasons for x in tiny)
    huge = matching.match_buyers("rice_straw", 10_000_000, "dry", district, None, path)
    assert all("qty_over" in x.reasons for x in huge)


def test_request_workflow_and_contact_consent():
    path = fresh_db()
    lid = db.add_listing("Ravi", "9876543210", True, "rice_straw", 1000, "dry", "Thanjavur", 2.0, path)
    other = db.add_listing("Anu", "9123456780", False, "rice_straw", 500, "dry", "Erode", None, path)
    buyer = matching.match_buyers("rice_straw", 1000, "dry", "Thanjavur", 2.0, path)[0].buyer["id"]
    assert db.create_request(lid, buyer, path) is True
    assert db.create_request(lid, buyer, path) is False  # no duplicates
    db.create_request(other, buyer, path)
    assert db.requested_buyer_ids(lid, path) == {buyer}
    rows = db.requests_for_buyer(buyer, path)
    assert {r["status"] for r in rows} == {"pending"}
    db.set_request_status(rows[0]["id"], "accepted", path)
    assert db.requests_for_listings([lid, other], path)[0]["status"] in ("accepted", "pending")
    assert [r["phone"] for r in db.listings_by_phone("9876543210", path)] == ["9876543210"]
    # consent flag stored only when a phone exists
    l2 = db.add_listing("", "", True, "rice_straw", 10, "dry", "X", None, path)
    assert db.get_listing(l2, path)["share_contact"] == 0
    try:
        db.set_request_status(1, "hacked", path)
        assert False
    except ValueError:
        pass


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
