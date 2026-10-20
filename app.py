"""CropLeftover AI - Streamlit app (mobile-first, 4 languages)."""
import re

import streamlit as st

import ai_explain
import db
import matching
from i18n import (LANGUAGES, buyer_type_name, caution_text, condition_name,
                  residue_name, reuse_name, t)

st.set_page_config(page_title="CropLeftover AI", page_icon="🌾", layout="centered")


@st.cache_resource
def _setup() -> bool:
    db.init_db()
    return True


_setup()

st.markdown(
    """
<style>
.block-container {max-width: 720px; padding-top: 1.2rem; padding-bottom: 3rem;}
.stButton > button, .stFormSubmitButton > button {width: 100%; min-height: 2.9rem; font-size: 1.05rem;}
div[data-testid="stRadio"] label {font-size: 1.0rem;}
</style>
""",
    unsafe_allow_html=True,
)

CONDITIONS = ["dry", "fresh_green", "wet", "moldy"]
PAGES = ["add", "results", "requests", "buyer"]


# ---------- helpers ----------
def normalize_phone(raw: str) -> str | None:
    """Return a 10-digit Indian mobile number, '' if empty, None if invalid."""
    s = re.sub(r"[\s\-]", "", raw or "")
    if not s:
        return ""
    s = re.sub(r"^(\+91|91|0)(?=\d{10}$)", "", s)
    return s if re.fullmatch(r"[6-9]\d{9}", s) else None


def fmt_kg(n) -> str:
    return f"{n:,.0f}"


def my_listing_ids() -> list[int]:
    return st.session_state.setdefault("my_listing_ids", [])


# ---------- header ----------
st.selectbox(
    "🌐 Language / மொழி / భాష / भाषा",
    list(LANGUAGES),
    format_func=LANGUAGES.get,
    key="lang",
)
lang = st.session_state["lang"]

st.title("🌾 " + t(lang, "app_title"))
st.caption(t(lang, "tagline"))

if "goto" in st.session_state:  # set by callbacks/forms before rerun
    st.session_state["page"] = st.session_state.pop("goto")
st.session_state.setdefault("page", "add")
page = st.radio(
    "nav", PAGES, format_func=lambda p: t(lang, "nav_" + p),
    horizontal=True, key="page", label_visibility="collapsed",
)


# ---------- pages ----------
def page_add():
    st.subheader(t(lang, "add_header"))
    with st.form("add_form"):
        residue = st.selectbox(
            t(lang, "residue_type"), db.residue_keys(),
            format_func=lambda k: residue_name(lang, k))
        qty = st.number_input(t(lang, "quantity"), min_value=0.0, value=100.0, step=50.0)
        cond = st.selectbox(t(lang, "condition"), CONDITIONS,
                            format_func=lambda k: condition_name(lang, k))
        district = st.text_input(t(lang, "district"))
        price = st.number_input(t(lang, "price"), min_value=0.0, value=0.0, step=0.5,
                                help=t(lang, "price_help"))
        name = st.text_input(t(lang, "your_name"))
        phone = st.text_input(t(lang, "phone"), placeholder="98765 43210")
        share = st.checkbox(t(lang, "share_contact"))
        submitted = st.form_submit_button(t(lang, "submit"), type="primary")

    if not submitted:
        return

    errors = []
    if qty <= 0:
        errors.append("err_qty")
    if not district.strip():
        errors.append("err_district")
    if price < 0:
        errors.append("err_price")
    phone_norm = normalize_phone(phone)
    if phone_norm is None:
        errors.append("err_phone")
    elif share and not phone_norm:
        errors.append("err_share_phone")
    if errors:
        for e in errors:
            st.error(t(lang, e))
        return

    lid = db.add_listing(name.strip(), phone_norm, share, residue, qty, cond,
                         district, price if price > 0 else None)
    my_listing_ids().append(lid)
    st.session_state["current_listing"] = lid
    st.session_state["flash"] = "saved_ok"
    st.session_state["goto"] = "results"
    st.rerun()


def build_ai_summary(listing, suggestions) -> str:
    lines = [
        f"Residue: {residue_name('en', listing['residue_key'])}, "
        f"{fmt_kg(listing['quantity_kg'])} kg, condition: {condition_name('en', listing['condition'])}, "
        f"district: {listing['district']}.",
        "Suggested uses:",
    ]
    for s in suggestions:
        cautions = " ".join(caution_text("en", c) for c in s.cautions)
        lines.append(f"- {reuse_name('en', s.reuse_key)}. {cautions}".strip())
    return "\n".join(lines)


def page_results():
    ids = my_listing_ids()
    if not ids:
        st.info(t(lang, "no_listing"))
        return
    if st.session_state.get("current_listing") not in ids:
        st.session_state["current_listing"] = ids[-1]
    if len(ids) > 1:
        st.selectbox(
            t(lang, "your_listing"), ids[::-1], key="current_listing",
            format_func=lambda i: f"#{i}  {residue_name(lang, db.get_listing(i)['residue_key'])}")
    lid = st.session_state["current_listing"]
    listing = db.get_listing(lid)

    if st.session_state.pop("flash", None):
        st.success(t(lang, "saved_ok"))

    price_txt = (f"₹{listing['price_per_kg']:g} {t(lang, 'per_kg')}"
                 if listing["price_per_kg"] else "-")
    with st.container(border=True):
        st.markdown(f"**{residue_name(lang, listing['residue_key'])}**")
        st.write(f"{fmt_kg(listing['quantity_kg'])} {t(lang, 'kg')} · "
                 f"{condition_name(lang, listing['condition'])} · {listing['district']} · {price_txt}")

    # --- reuse suggestions ---
    st.subheader("♻️ " + t(lang, "reuse_header"))
    suggestions = matching.suggest_reuse(listing["residue_key"], listing["condition"])
    if not suggestions:
        st.info(t(lang, "no_reuse"))
    else:
        if listing["condition"] == "moldy":
            st.warning(t(lang, "only_compost"))
        for s in suggestions:
            with st.container(border=True):
                st.markdown(f"**{reuse_name(lang, s.reuse_key)}**")
                for c in s.cautions:
                    st.caption("⚠️ " + caution_text(lang, c))
    residue = db.get_residue(listing["residue_key"])
    if residue["source_status"] == "verified":
        st.caption("✅ " + t(lang, "source_verified") + ": " + (residue["source_note"] or ""))
    else:
        st.caption("ℹ️ " + t(lang, "source_unverified"))

    if suggestions and ai_explain.is_configured():
        ai_key = f"ai_{lid}_{lang}"
        if st.button(t(lang, "ai_btn"), key=f"aibtn_{lid}"):
            try:
                with st.spinner("..."):
                    st.session_state[ai_key] = ai_explain.explain(
                        build_ai_summary(listing, suggestions), lang)
            except Exception:
                st.error(t(lang, "ai_error"))
        if st.session_state.get(ai_key):
            st.write(st.session_state[ai_key])
            st.caption("🤖 " + t(lang, "ai_disclaimer"))

    # --- buyers ---
    st.subheader("🤝 " + t(lang, "buyers_header"))
    st.caption(t(lang, "buyers_note"))
    matches = matching.match_buyers(
        listing["residue_key"], listing["quantity_kg"], listing["condition"],
        listing["district"], listing["price_per_kg"])
    if not matches:
        st.info(t(lang, "no_buyers"))
    already = db.requested_buyer_ids(lid)
    for m in matches:
        b = m.buyer
        with st.container(border=True):
            badge = f"  `{t(lang, 'demo_badge')}`" if b["is_demo"] else ""
            st.markdown(f"**{b['name']}**{badge}")
            st.caption(f"{buyer_type_name(lang, b['buyer_type'])} · {b['district']}")
            hi = fmt_kg(b["max_qty_kg"]) if b["max_qty_kg"] else "∞"
            st.write(f"{t(lang, 'buyer_wants')}: {fmt_kg(b['min_qty_kg'] or 0)}–{hi} {t(lang, 'kg')}"
                     + (f" · {t(lang, 'buyer_pays')} ₹{b['max_price_per_kg']:g} {t(lang, 'per_kg')}"
                        if b["max_price_per_kg"] else ""))
            st.progress(m.score / 100, text=f"{t(lang, 'match_score')}: {m.score}%")
            st.caption(" · ".join(t(lang, "reason_" + r) for r in m.reasons))
            if b["id"] in already:
                st.success("✓ " + t(lang, "request_sent"))
            else:
                st.button(t(lang, "request_btn"), key=f"req_{lid}_{b['id']}",
                          on_click=db.create_request, args=(lid, b["id"]))


def page_requests():
    st.subheader(t(lang, "requests_header"))
    ids = list(my_listing_ids())
    lookup = st.text_input(t(lang, "lookup_phone"), placeholder="98765 43210")
    if lookup:
        p = normalize_phone(lookup)
        if p:
            ids += [r["id"] for r in db.listings_by_phone(p) if r["id"] not in ids]
        else:
            st.error(t(lang, "err_phone"))
    rows = db.requests_for_listings(ids)
    if not rows:
        st.info(t(lang, "no_requests"))
        return
    for r in rows:
        with st.container(border=True):
            demo = f"  `{t(lang, 'demo_badge')}`" if r["is_demo"] else ""
            st.markdown(f"**{r['buyer_name']}**{demo}")
            st.write(f"{residue_name(lang, r['residue_key'])} · {fmt_kg(r['quantity_kg'])} {t(lang, 'kg')}")
            icon = {"pending": "⏳", "accepted": "✅", "declined": "❌"}[r["status"]]
            st.write(f"{icon} {t(lang, 'status_' + r['status'])}")
            if r["status"] == "accepted" and r["buyer_contact"]:
                st.info(f"{t(lang, 'buyer_contact')}: {r['buyer_contact']}")


def _set_status(request_id, status):
    db.set_request_status(request_id, status)


def page_buyer():
    st.subheader(t(lang, "buyer_view_header"))
    st.caption(t(lang, "buyer_view_note"))
    buyers = db.list_buyers()
    bid = st.selectbox(t(lang, "select_buyer"), [b["id"] for b in buyers],
                       format_func=lambda i: next(b["name"] for b in buyers if b["id"] == i))
    buyer = db.get_buyer(bid)
    st.caption(f"{residue_name(lang, buyer['residue_key'])} · {buyer['district']}")
    st.markdown("**" + t(lang, "incoming") + "**")
    rows = db.requests_for_buyer(bid)
    if not rows:
        st.info(t(lang, "no_requests"))
    for r in rows:
        with st.container(border=True):
            price_txt = f"₹{r['price_per_kg']:g} {t(lang, 'per_kg')}" if r["price_per_kg"] else "-"
            st.markdown(f"**{residue_name(lang, r['residue_key'])}**")
            st.write(f"{fmt_kg(r['quantity_kg'])} {t(lang, 'kg')} · {condition_name(lang, r['condition'])} · "
                     f"{r['district']} · {price_txt}")
            icon = {"pending": "⏳", "accepted": "✅", "declined": "❌"}[r["status"]]
            st.write(f"{icon} {t(lang, 'status_' + r['status'])}")
            if r["status"] == "pending":
                c1, c2 = st.columns(2)
                c1.button(t(lang, "accept"), key=f"acc_{r['id']}", on_click=_set_status,
                          args=(r["id"], "accepted"), type="primary")
                c2.button(t(lang, "decline"), key=f"dec_{r['id']}", on_click=_set_status,
                          args=(r["id"], "declined"))
            elif r["status"] == "accepted":
                if r["share_contact"] and r["phone"]:
                    who = f"{r['farmer_name']} · " if r["farmer_name"] else ""
                    st.info(f"{t(lang, 'farmer_contact')}: {who}{r['phone']}")
                else:
                    st.caption(t(lang, "contact_hidden"))


{"add": page_add, "results": page_results, "requests": page_requests, "buyer": page_buyer}[page]()

st.divider()
st.caption(t(lang, "disclaimer"))
