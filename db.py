"""SQLite storage for CropLeftover AI."""
import os
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = os.environ.get("CROPLEFTOVER_DB", str(BASE_DIR / "cropleftover.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS residues (
    residue_key TEXT PRIMARY KEY,
    category TEXT,
    source_status TEXT NOT NULL DEFAULT 'unverified',
    source_note TEXT
);
CREATE TABLE IF NOT EXISTS reuse_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    residue_key TEXT NOT NULL REFERENCES residues(residue_key),
    reuse_key TEXT NOT NULL,
    conditions TEXT NOT NULL,
    cautions TEXT DEFAULT '',
    priority INTEGER DEFAULT 99
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL CHECK (role IN ('farmer','buyer')),
    token TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    district TEXT NOT NULL,
    share_contact INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (role, phone)
);
CREATE TABLE IF NOT EXISTS buyers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    buyer_type TEXT,
    district TEXT NOT NULL,
    residue_key TEXT NOT NULL REFERENCES residues(residue_key),
    min_qty_kg REAL DEFAULT 0,
    max_qty_kg REAL,
    max_price_per_kg REAL,
    accepted_conditions TEXT NOT NULL,
    contact TEXT,
    is_demo INTEGER NOT NULL DEFAULT 0,
    user_id INTEGER,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    farmer_name TEXT,
    phone TEXT,
    share_contact INTEGER NOT NULL DEFAULT 0,
    residue_key TEXT NOT NULL REFERENCES residues(residue_key),
    quantity_kg REAL NOT NULL CHECK (quantity_kg > 0),
    condition TEXT NOT NULL,
    district TEXT NOT NULL,
    price_per_kg REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    user_id INTEGER
);
CREATE TABLE IF NOT EXISTS connection_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    buyer_id INTEGER NOT NULL REFERENCES buyers(id),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','declined')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (listing_id, buyer_id)
);
"""


@contextmanager
def connect(path: str | None = None):
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _add_column(conn, table: str, column: str, ddl: str) -> None:
    """Upgrade a database created by an older version of the app."""
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db(path: str | None = None) -> None:
    """Create tables, upgrade old databases, and import the CSV datasets on first run."""
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        _add_column(conn, "buyers", "user_id", "INTEGER")
        _add_column(conn, "buyers", "active", "INTEGER NOT NULL DEFAULT 1")
        _add_column(conn, "listings", "user_id", "INTEGER")
        if conn.execute("SELECT COUNT(*) FROM residues").fetchone()[0] == 0:
            pd.read_csv(DATA_DIR / "residues.csv").to_sql(
                "residues", conn, if_exists="append", index=False)
        if conn.execute("SELECT COUNT(*) FROM reuse_rules").fetchone()[0] == 0:
            rules = pd.read_csv(DATA_DIR / "reuse_rules.csv", keep_default_na=False)
            rules.to_sql("reuse_rules", conn, if_exists="append", index=False)
        if conn.execute("SELECT COUNT(*) FROM buyers WHERE is_demo = 1").fetchone()[0] == 0:
            buyers = pd.read_csv(DATA_DIR / "demo_buyers.csv")
            buyers["is_demo"] = 1
            buyers.to_sql("buyers", conn, if_exists="append", index=False)


# ---------- knowledge ----------
def residue_keys(path=None) -> list[str]:
    with connect(path) as conn:
        return [r[0] for r in conn.execute("SELECT residue_key FROM residues ORDER BY residue_key")]


def get_residue(key: str, path=None):
    with connect(path) as conn:
        return conn.execute("SELECT * FROM residues WHERE residue_key = ?", (key,)).fetchone()


def get_reuse_rules(key: str, path=None) -> list[sqlite3.Row]:
    with connect(path) as conn:
        return conn.execute(
            "SELECT * FROM reuse_rules WHERE residue_key = ? ORDER BY priority", (key,)).fetchall()


# ---------- users (farmers and buyers) ----------
def create_user(role: str, name: str, phone: str, district: str, share_contact=False, path=None):
    """Returns the new user as a dict, or None if this role already has that phone number."""
    token = secrets.token_urlsafe(16)
    with connect(path) as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (role, token, name, phone, district, share_contact) VALUES (?,?,?,?,?,?)",
                (role, token, name.strip(), phone, district.strip(), int(bool(share_contact))))
        except sqlite3.IntegrityError:
            return None
        return dict(conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone())


def user_by_token(token: str, role: str | None = None, path=None):
    if not token:
        return None
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM users WHERE token = ?", (token,)).fetchone()
    if row is None or (role and row["role"] != role):
        return None
    return dict(row)


def user_by_phone(role: str, phone: str, path=None):
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM users WHERE role = ? AND phone = ?", (role, phone)).fetchone()
    return dict(row) if row else None


def update_user(user_id: int, name: str, district: str, share_contact: bool, path=None):
    with connect(path) as conn:
        conn.execute("UPDATE users SET name = ?, district = ?, share_contact = ? WHERE id = ?",
                     (name.strip(), district.strip(), int(bool(share_contact)), user_id))
        return dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


# ---------- buyers ----------
def save_buyer_profile(user_id, name, buyer_type, district, phone, residues, conds,
                       min_qty, max_qty, max_price, path=None) -> None:
    """A registered buyer is stored as one row per residue they buy, all linked by user_id.
    Residues removed later are switched off (not deleted) so old requests keep working."""
    cond_s = "|".join(conds)
    with connect(path) as conn:
        existing = {r["residue_key"]: r for r in
                    conn.execute("SELECT * FROM buyers WHERE user_id = ?", (user_id,))}
        for key in residues:
            values = (name.strip(), buyer_type, district.strip(), min_qty, max_qty, max_price, cond_s, phone)
            if key in existing:
                conn.execute(
                    """UPDATE buyers SET name=?, buyer_type=?, district=?, min_qty_kg=?, max_qty_kg=?,
                       max_price_per_kg=?, accepted_conditions=?, contact=?, active=1 WHERE id=?""",
                    values + (existing[key]["id"],))
            else:
                conn.execute(
                    """INSERT INTO buyers (name, buyer_type, district, min_qty_kg, max_qty_kg,
                       max_price_per_kg, accepted_conditions, contact, residue_key, is_demo, user_id, active)
                       VALUES (?,?,?,?,?,?,?,?,?,0,?,1)""", values + (key, user_id))
        for key, row in existing.items():
            if key not in residues:
                conn.execute("UPDATE buyers SET active = 0 WHERE id = ?", (row["id"],))


def get_buyer_profile(user_id: int, path=None):
    with connect(path) as conn:
        rows = conn.execute("SELECT * FROM buyers WHERE user_id = ? AND active = 1 ORDER BY id",
                            (user_id,)).fetchall()
    if not rows:
        return None
    first = rows[0]
    return {
        "name": first["name"], "buyer_type": first["buyer_type"], "district": first["district"],
        "phone": first["contact"], "residues": [r["residue_key"] for r in rows],
        "conds": first["accepted_conditions"].split("|"),
        "min_qty": first["min_qty_kg"] or 0.0, "max_qty": first["max_qty_kg"] or 0.0,
        "max_price": first["max_price_per_kg"] or 0.0,
    }


def get_buyers_for(key: str, path=None) -> list[sqlite3.Row]:
    with connect(path) as conn:
        return conn.execute(
            "SELECT * FROM buyers WHERE residue_key = ? AND active = 1", (key,)).fetchall()


def list_buyers(path=None, demo_only: bool = False) -> list[sqlite3.Row]:
    sql = "SELECT * FROM buyers WHERE active = 1" + (" AND is_demo = 1" if demo_only else "") + " ORDER BY name"
    with connect(path) as conn:
        return conn.execute(sql).fetchall()


def get_buyer(buyer_id: int, path=None):
    with connect(path) as conn:
        return conn.execute("SELECT * FROM buyers WHERE id = ?", (buyer_id,)).fetchone()


def demo_buyers_with_requests(path=None) -> list[sqlite3.Row]:
    with connect(path) as conn:
        return conn.execute(
            """SELECT DISTINCT b.id, b.name FROM connection_requests r
               JOIN buyers b ON b.id = r.buyer_id WHERE b.is_demo = 1 ORDER BY b.name""").fetchall()


# ---------- listings ----------
def add_listing(farmer_name, phone, share_contact, residue_key, quantity_kg,
                condition, district, price_per_kg, path=None, user_id=None) -> int:
    with connect(path) as conn:
        cur = conn.execute(
            """INSERT INTO listings (farmer_name, phone, share_contact, residue_key,
               quantity_kg, condition, district, price_per_kg, user_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (farmer_name or None, phone or None, int(bool(share_contact and phone)),
             residue_key, quantity_kg, condition, district.strip(), price_per_kg, user_id))
        return cur.lastrowid


def get_listing(listing_id: int, path=None):
    with connect(path) as conn:
        return conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()


def listings_for_user(user_id: int, path=None) -> list[sqlite3.Row]:
    with connect(path) as conn:
        return conn.execute(
            "SELECT * FROM listings WHERE user_id = ? ORDER BY id", (user_id,)).fetchall()


def get_listings_for(residue_key: str, path=None) -> list[sqlite3.Row]:
    with connect(path) as conn:
        return conn.execute(
            "SELECT * FROM listings WHERE residue_key = ? ORDER BY id DESC", (residue_key,)).fetchall()


# ---------- connection requests ----------
def create_request(listing_id: int, buyer_id: int, path=None) -> bool:
    """Returns False if a request for this pair already exists."""
    with connect(path) as conn:
        try:
            conn.execute(
                "INSERT INTO connection_requests (listing_id, buyer_id) VALUES (?,?)",
                (listing_id, buyer_id))
            return True
        except sqlite3.IntegrityError:
            return False


def requested_buyer_ids(listing_id: int, path=None) -> set[int]:
    with connect(path) as conn:
        return {r[0] for r in conn.execute(
            "SELECT buyer_id FROM connection_requests WHERE listing_id = ?", (listing_id,))}


def requests_for_listings(listing_ids: list[int], path=None) -> list[sqlite3.Row]:
    if not listing_ids:
        return []
    marks = ",".join("?" * len(listing_ids))
    with connect(path) as conn:
        return conn.execute(
            f"""SELECT r.id, r.status, r.created_at, r.listing_id, l.residue_key,
                       l.quantity_kg, b.id AS buyer_id, b.name AS buyer_name,
                       b.contact AS buyer_contact, b.is_demo
                FROM connection_requests r
                JOIN listings l ON l.id = r.listing_id
                JOIN buyers b ON b.id = r.buyer_id
                WHERE r.listing_id IN ({marks}) ORDER BY r.id DESC""",
            listing_ids).fetchall()


_INCOMING = """SELECT r.id, r.status, r.created_at, l.residue_key, l.quantity_kg,
                      l.condition, l.district, l.price_per_kg,
                      l.farmer_name, l.phone, l.share_contact
               FROM connection_requests r
               JOIN listings l ON l.id = r.listing_id
               JOIN buyers b ON b.id = r.buyer_id"""


def requests_for_buyer(buyer_id: int, path=None) -> list[sqlite3.Row]:
    """Incoming requests for one buyer row (used for the demo buyers)."""
    with connect(path) as conn:
        return conn.execute(_INCOMING + " WHERE r.buyer_id = ? ORDER BY r.id DESC", (buyer_id,)).fetchall()


def requests_for_buyer_user(user_id: int, path=None) -> list[sqlite3.Row]:
    """Incoming requests for a registered buyer, across all residues they buy."""
    with connect(path) as conn:
        return conn.execute(_INCOMING + " WHERE b.user_id = ? ORDER BY r.id DESC", (user_id,)).fetchall()


def set_request_status(request_id: int, status: str, path=None, buyer_user_id=None) -> bool:
    """When buyer_user_id is given, only that buyer's own requests can be changed."""
    if status not in ("accepted", "declined"):
        raise ValueError("status must be accepted or declined")
    sql = "UPDATE connection_requests SET status = ? WHERE id = ?"
    args = [status, request_id]
    if buyer_user_id is not None:
        sql += " AND buyer_id IN (SELECT id FROM buyers WHERE user_id = ?)"
        args.append(buyer_user_id)
    with connect(path) as conn:
        return conn.execute(sql, args).rowcount > 0
