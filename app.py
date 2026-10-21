"""CropLeftover AI - Streamlit app (mobile-first, 4 languages, farmer and buyer sides)."""
import re

import streamlit as st

import ai_explain
import db
import matching
from i18n import (BUYER_TYPES, LANGUAGES, buyer_type_name, caution_text,
                  condition_name, residue_name, reuse_name, t)

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
PARAM = {"farmer": "f", "buyer": "b"}  # URL parameter that keeps a user signed in after a refresh
PAGES = {
    "farmer": ["add", "results", "requests", "profile"],
    "buyer": ["b_requests", "b_listings", "b_profile"],
}
PAGE_LABEL = {
    "add": "nav_add", "results": "nav_results", "requests": "nav_requests", "profile": "profile",
    "b_requests": "nav_b_requests", "b_listings": "nav_b_listings", "b_profile": "profile",
}
ICON = {"pending": "⏳", "accepted": "✅", "declined": "❌"}


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


def price_txt(p) -> str:
    return f"₹{p:g} {t(lang, 'per_kg').replace('₹', '')}" if p else "-"


def show_errors(keys):
    for k in keys:
        st.error(t(lang, k))


def flash():
    key = st.session_state.pop("flash", None)
    if key:
        st.success(t(lang, key))


# ---------- signed-in user (kept across refreshes with a URL token) ----------
def get_user(role):
    key = "user_" + role
    user = st.session_state.get(key)
    if user is None:
        token = st.query_params.get(PARAM[role])
        if token:
            user = db.user_by_token(token, role)
            if user:
                st.session_state[key] = user
    return user


def sign_in(user):
    st.session_state["user_" + user["role"]] = user
    st.query_params[PARAM[user["role"]]] = user["token"]
    st.session_state["goto"] = PAGES[user["role"]][0]


def sign_out(role):
    st.session_state.pop("user_" + role, None)
    if PARAM[role] in st.query_params:
        del st.query_params[PARAM[role]]


def signin_form(role):
    st.subheader(t(lang, "signin_header"))
    st.caption(t(lang, "signin_note"))
    with st.form(f"signin_{role}"):
        phone = st.text_input(t(lang, "phone_req"), placeholder="98765 43210")
        submitted = st.form_submit_button(t(lang, "signin_btn"))
    if submitted:
        p = normalize_phone(phone)
        user = db.user_by_phone(role, p) if p else None
        if not user:
            st.error(t(lang, "err_signin"))
            return
        sign_in(user)
        st.rerun()


# ---------- farmer ----------
def farmer_auth():
    st.subheader(t(lang, "reg_header"))
    st.caption(t(lang, "reg_note"))
    with st.form("farmer_register"):
        name = st.text_input(t(lang, "name_req"))
        phone = st.text_input(t(lang, "phone_req"), placeholder="98765 43210")
        district = st.text_input(t(lang, "district"))
        share = st.checkbox(t(lang, "share_contact"))
        submitted = st.form_submit_button(t(lang, "reg_btn"), type="primary")
    if submitted:
        errors = []
        phone_n = normalize_phone(phone)
        if not name.strip():
            errors.append("err_name")
        if not phone_n:
            errors.append("err_phone_req")
        if not district.strip():
            errors.append("err_district")
        if errors:
            show_errors(errors)
        else:
            user = db.create_user("farmer", name, phone_n, district, share)
            if user is None:
                st.error(t(lang, "err_phone_taken"))
            else:
                sign_in(user)
                st.session_state["flash"] = "profile_saved"
                st.rerun()
    st.divider()
    signin_form("farmer")


def page_add(user):
    st.subheader(t(lang, "add_header"))
    flash()
    st.caption(f"👤 {user['name']} · {user['phone']} · "
               + t(lang, "contact_shared" if user["share_contact"] else "contact_private"))
    with st.form("add_form"):
        residue = st.selectbox(
            t(lang, "residue_type"), db.residue_keys(),
            format_func=lambda k: residue_name(lang, k))
        qty = st.number_input(t(lang, "quantity"), min_value=0.0, value=100.0, step=50.0)
        cond = st.selectbox(t(lang, "condition"), CONDITIONS,
                            format_func=lambda k: condition_name(lang, k))
        district = st.text_input(t(lang, "district"), value=user["district"])
        price = st.number_input(t(lang, "price"), min_value=0.0, value=0.0, step=0.5,
                                help=t(lang, "price_help"))
        submitted = st.form_submit_button(t(lang, "submit"), type="primary")
    if not submitted:
        return
    errors = []
    if qty <= 0:
        errors.append("err_qty")
    if not district.strip():
        errors.append("err_district")
    if errors:
        show_errors(errors)
        return
    lid = db.add_listing(user["name"], user["phone"], user["share_contact"], residue, qty, cond,
                         district, price if price > 0 else None, user_id=user["id"])
    st.session_state["current_listing"] = lid
    st.session_state["flash"] = "saved_ok"
    st.session_state["goto"] = "results"
    st.rerun()


def sample_listing():
    return {"id": 0, "residue_key": "rice_straw", "quantity_kg": 1500.0, "condition": "dry",
            "district": "Thanjavur", "price_per_kg": 2.5}


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


def buyer_badge(b) -> str:
    if b["is_demo"]:
        return f"  `{t(lang, 'demo_badge')}`"
    return f"  `{t(lang, 'registered_badge')}`"


def buyer_card(m, listing_id, already, sample):
    b = m.buyer
    with st.container(border=True):
        st.markdown(f"**{b['name']}**{buyer_badge(b)}")
        st.caption(f"{buyer_type_name(lang, b['buyer_type'])} · {b['district']}")
        hi = fmt_kg(b["max_qty_kg"]) if b["max_qty_kg"] else "∞"
        st.write(f"{t(lang, 'buyer_wants')}: {fmt_kg(b['min_qty_kg'] or 0)}–{hi} {t(lang, 'kg')}"
                 + (f" · {t(lang, 'buyer_pays')} {price_txt(b['max_price_per_kg'])}"
                    if b["max_price_per_kg"] else ""))
        st.progress(m.score / 100, text=f"{t(lang, 'match_score')}: {m.score}%")
        st.caption(" · ".join(t(lang, "reason_" + r) for r in m.reasons))
        if sample:
            return
        if b["id"] in already:
            st.success("✓ " + t(lang, "request_sent"))
        else:
            st.button(t(lang, "request_btn"), key=f"req_{listing_id}_{b['id']}",
                      on_click=db.create_request, args=(listing_id, b["id"]))


def page_results(user):
    mine = db.listings_for_user(user["id"])
    sample = not mine
    if sample:
        listing = sample_listing()
        lid = 0
        st.info(t(lang, "sample_note"))
    else:
        ids = [r["id"] for r in mine]
        if st.session_state.get("current_listing") not in ids:
            st.session_state["current_listing"] = ids[-1]
        if len(ids) > 1:
            st.selectbox(
                t(lang, "your_listing"), ids[::-1], key="current_listing",
                format_func=lambda i: f"#{i}  {residue_name(lang, db.get_listing(i)['residue_key'])}")
        lid = st.session_state["current_listing"]
        listing = db.get_listing(lid)
        flash()

    badge = f"  `{t(lang, 'sample_badge')}`" if sample else ""
    with st.container(border=True):
        st.markdown(f"**{residue_name(lang, listing['residue_key'])}**{badge}")
        st.write(f"{fmt_kg(listing['quantity_kg'])} {t(lang, 'kg')} · "
                 f"{condition_name(lang, listing['condition'])} · {listing['district']} · "
                 f"{price_txt(listing['price_per_kg'])}")

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

    st.subheader("🤝 " + t(lang, "buyers_header"))
    st.caption(t(lang, "buyers_note"))
    matches = matching.match_buyers(
        listing["residue_key"], listing["quantity_kg"], listing["condition"],
        listing["district"], listing["price_per_kg"])
    if not matches:
        st.info(t(lang, "no_buyers"))
    already = set() if sample else db.requested_buyer_ids(lid)
    for m in matches[:12]:
        buyer_card(m, lid, already, sample)
    if len(matches) > 12:
        st.caption(f"+ {len(matches) - 12}")


def sample_requests():
    """Three example requests shown to a farmer who has not added a residue yet."""
    l = sample_listing()
    demo = [m for m in matching.match_buyers(l["residue_key"], l["quantity_kg"], l["condition"],
                                             l["district"], l["price_per_kg"]) if m.buyer["is_demo"]][:3]
    return list(zip(["accepted", "pending", "declined"], demo))


def page_requests(user):
    st.subheader(t(lang, "requests_header"))
    ids = [r["id"] for r in db.listings_for_user(user["id"])]
    rows = db.requests_for_listings(ids)
    if not ids:
        st.info(t(lang, "sample_note"))
        for status, m in sample_requests():
            with st.container(border=True):
                st.markdown(f"**{m.buyer['name']}**{buyer_badge(m.buyer)}")
                st.write(f"{residue_name(lang, 'rice_straw')}  `{t(lang, 'sample_badge')}` · 1,500 {t(lang, 'kg')}")
                st.write(f"{ICON[status]} {t(lang, 'status_' + status)}")
        return
    if not rows:
        st.info(t(lang, "no_requests"))
        return
    for r in rows:
        with st.container(border=True):
            st.markdown(f"**{r['buyer_name']}**" + (f"  `{t(lang, 'demo_badge')}`" if r["is_demo"] else f"  `{t(lang, 'registered_badge')}`"))
            st.write(f"{residue_name(lang, r['residue_key'])} · {fmt_kg(r['quantity_kg'])} {t(lang, 'kg')}")
            st.write(f"{ICON[r['status']]} {t(lang, 'status_' + r['status'])}")
            if r["status"] == "accepted" and r["buyer_contact"]:
                label = "buyer_contact" if r["is_demo"] else "phone_req"
                st.info(f"{t(lang, label)}: {r['buyer_contact']}")


def page_farmer_profile(user):
    st.subheader(t(lang, "profile"))
    flash()
    with st.form("farmer_profile"):
        name = st.text_input(t(lang, "name_req"), value=user["name"])
        st.text_input(t(lang, "phone_fixed"), value=user["phone"], disabled=True)
        district = st.text_input(t(lang, "district"), value=user["district"])
        share = st.checkbox(t(lang, "share_contact"), value=bool(user["share_contact"]))
        submitted = st.form_submit_button(t(lang, "save_changes"), type="primary")
    if submitted:
        errors = (["err_name"] if not name.strip() else []) + (["err_district"] if not district.strip() else [])
        if errors:
            show_errors(errors)
        else:
            st.session_state["user_farmer"] = db.update_user(user["id"], name, district, share)
            st.session_state["flash"] = "profile_saved"
            st.rerun()
    st.button(t(lang, "signout"), key="signout_farmer", on_click=sign_out, args=("farmer",))


# ---------- buyer ----------
def buyer_form(user=None):
    """Register (user is None) or edit a buyer business."""
    prof = db.get_buyer_profile(user["id"]) if user else None
    prof = prof or {"name": "", "buyer_type": list(BUYER_TYPES)[0], "district": "", "residues": [],
                    "conds": ["dry"], "min_qty": 100.0, "max_qty": 5000.0, "max_price": 3.0}
    types = list(BUYER_TYPES)
    with st.form("buyer_form"):
        name = st.text_input(t(lang, "b_name"), value=prof["name"])
        btype = st.selectbox(t(lang, "b_type"), types,
                             index=types.index(prof["buyer_type"]) if prof["buyer_type"] in types else 0,
                             format_func=lambda k: buyer_type_name(lang, k))
        if user:
            st.text_input(t(lang, "phone_fixed"), value=user["phone"], disabled=True)
            phone = user["phone"]
        else:
            phone = st.text_input(t(lang, "phone_req"), placeholder="98765 43210")
        district = st.text_input(t(lang, "district"), value=prof["district"])
        residues = st.multiselect(t(lang, "b_residues"), db.residue_keys(), default=prof["residues"],
                                  format_func=lambda k: residue_name(lang, k))
        conds = st.multiselect(t(lang, "b_conds"), CONDITIONS, default=prof["conds"],
                               format_func=lambda k: condition_name(lang, k))
        min_qty = st.number_input(t(lang, "b_min"), min_value=0.0, value=float(prof["min_qty"]), step=50.0)
        max_qty = st.number_input(t(lang, "b_max"), min_value=0.0, value=float(prof["max_qty"]), step=100.0)
        max_price = st.number_input(t(lang, "b_price"), min_value=0.0, value=float(prof["max_price"]), step=0.5)
        submitted = st.form_submit_button(t(lang, "b_save"), type="primary")
    if not submitted:
        return
    errors = []
    phone_n = normalize_phone(phone)
    if not name.strip():
        errors.append("err_b_name")
    if not phone_n:
        errors.append("err_phone_req")
    if not district.strip():
        errors.append("err_district")
    if not residues:
        errors.append("err_b_residue")
    if not conds:
        errors.append("err_b_cond")
    if max_qty <= 0 or max_qty < min_qty:
        errors.append("err_b_qty")
    if errors:
        show_errors(errors)
        return
    if user is None:
        user = db.create_user("buyer", name, phone_n, district, False)
        if user is None:
            st.error(t(lang, "err_phone_taken"))
            return
    else:
        user = db.update_user(user["id"], name, district, False)
    db.save_buyer_profile(user["id"], name, btype, district, phone_n, residues, conds,
                          min_qty, max_qty, max_price)
    sign_in(user)
    st.session_state["flash"] = "b_saved"
    st.rerun()


def buyer_auth():
    st.subheader(t(lang, "b_reg_header"))
    st.caption(t(lang, "b_reg_note"))
    buyer_form(None)
    st.divider()
    signin_form("buyer")


def _decide(request_id, status, buyer_user_id):
    db.set_request_status(request_id, status, buyer_user_id=buyer_user_id)


def incoming_card(r, buyer_user_id=None, can_act=True):
    with st.container(border=True):
        st.markdown(f"**{residue_name(lang, r['residue_key'])}**")
        if r["farmer_name"]:
            st.caption(f"{t(lang, 'farmer_label')}: {r['farmer_name']}")
        st.write(f"{fmt_kg(r['quantity_kg'])} {t(lang, 'kg')} · {condition_name(lang, r['condition'])} · "
                 f"{r['district']} · {price_txt(r['price_per_kg'])}")
        st.write(f"{ICON[r['status']]} {t(lang, 'status_' + r['status'])}")
        if r["status"] == "pending" and can_act:
            c1, c2 = st.columns(2)
            c1.button(t(lang, "accept"), key=f"acc_{r['id']}", on_click=_decide,
                      args=(r["id"], "accepted", buyer_user_id), type="primary")
            c2.button(t(lang, "decline"), key=f"dec_{r['id']}", on_click=_decide,
                      args=(r["id"], "declined", buyer_user_id))
        elif r["status"] == "accepted":
            if r["share_contact"] and r["phone"]:
                who = f"{r['farmer_name']} · " if r["farmer_name"] else ""
                st.info(f"{t(lang, 'farmer_contact')}: {who}{r['phone']}")
            else:
                st.caption(t(lang, "contact_hidden"))


def page_b_requests(user):
    st.subheader(t(lang, "b_requests_header"))
    flash()
    rows = db.requests_for_buyer_user(user["id"])
    if not rows:
        st.info(t(lang, "b_no_requests"))
    for r in rows:
        incoming_card(r, buyer_user_id=user["id"])

    demo = db.demo_buyers_with_requests()
    if demo:
        st.divider()
        st.subheader(t(lang, "demo_try"))
        st.caption(t(lang, "demo_try_note"))
        ids = [d["id"] for d in demo]
        names = {d["id"]: d["name"] for d in demo}
        if st.session_state.get("demo_sel") not in ids:
            st.session_state["demo_sel"] = ids[0]
        sel = st.selectbox(t(lang, "select_buyer"), ids, key="demo_sel", format_func=lambda i: names[i])
        for r in db.requests_for_buyer(sel):
            incoming_card(r, buyer_user_id=None)


def page_b_listings(user):
    st.subheader(t(lang, "b_listings_header"))
    prof = db.get_buyer_profile(user["id"])
    matches = matching.match_listings(prof) if prof else []
    if not matches:
        st.info(t(lang, "b_no_listings"))
    for m in matches[:20]:
        l = m.listing
        with st.container(border=True):
            st.markdown(f"**{residue_name(lang, l['residue_key'])}**")
            if l["farmer_name"]:
                st.caption(f"{t(lang, 'farmer_label')}: {l['farmer_name']}")
            st.write(f"{fmt_kg(l['quantity_kg'])} {t(lang, 'kg')} · {condition_name(lang, l['condition'])} · "
                     f"{l['district']} · {price_txt(l['price_per_kg'])}")
            st.progress(m.score / 100, text=f"{t(lang, 'match_score')}: {m.score}%")
            st.caption(" · ".join(t(lang, "reason_" + r) for r in m.reasons))


def page_b_profile(user):
    st.subheader(t(lang, "profile"))
    flash()
    buyer_form(user)
    st.button(t(lang, "signout"), key="signout_buyer", on_click=sign_out, args=("buyer",))


# ---------- header and routing ----------
st.selectbox(
    "🌐 Language / மொழி / భాష / भाषा",
    list(LANGUAGES),
    format_func=LANGUAGES.get,
    key="lang",
)
lang = st.session_state["lang"]

st.title("🌾 " + t(lang, "app_title"))
st.caption(t(lang, "tagline"))

st.session_state.setdefault("role", "farmer")
role = st.radio(
    "role", ["farmer", "buyer"], format_func=lambda r: t(lang, "role_" + r),
    horizontal=True, key="role", label_visibility="collapsed")

user = get_user(role)
if not user:
    (farmer_auth if role == "farmer" else buyer_auth)()
else:
    page_key = f"page_{role}"
    if "goto" in st.session_state:  # set by forms and callbacks before a rerun
        st.session_state[page_key] = st.session_state.pop("goto")
    if st.session_state.get(page_key) not in PAGES[role]:
        st.session_state[page_key] = PAGES[role][0]
    page = st.radio(
        "nav", PAGES[role], format_func=lambda p: t(lang, PAGE_LABEL[p]),
        horizontal=True, key=page_key, label_visibility="collapsed")
    {"add": page_add, "results": page_results, "requests": page_requests, "profile": page_farmer_profile,
     "b_requests": page_b_requests, "b_listings": page_b_listings, "b_profile": page_b_profile}[page](user)

st.divider()
st.caption(t(lang, "disclaimer"))
