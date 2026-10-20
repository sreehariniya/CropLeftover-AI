"""SQLite storage for CropLeftover AI."""
import os
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
    is_demo INTEGER NOT NULL DEFAULT 0
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
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
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


def init_db(path: str | None = None) -> None:
    """Create tables and import the CSV datasets on first run."""
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM residues").fetchone()[0] == 0:
            pd.read_csv(DATA_DIR / "residues.csv").to_sql(
                "residues", conn, if_exists="append", index=False)
        if conn.execute("SELECT COUNT(*) FROM reuse_rules").fetchone()[0] == 0:
            rules = pd.read_csv(DATA_DIR / "reuse_rules.csv", keep_default_na=False)
            rules.to_sql("reuse_rules", conn, if_exists="append", index=False)
        if conn.execute("SELECT COUNT(*) FROM buyers").fetchone()[0] == 0:
            buyers = pd.read_csv(DATA_DIR / "demo_buyers.csv")
            buyers = buyers.rename(columns={"accepted_conditions": "accepted_conditions"})
            buyers["is_demo"] = 1
            buyers.to_sql("buyers", conn, if_exists="append", index=False)


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


def get_buyers_for(key: str, path=None) -> list[sqlite3.Row]:
    with connect(path) as conn:
        return conn.execute("SELECT * FROM buyers WHERE residue_key = ?", (key,)).fetchall()


def list_buyers(path=None) -> list[sqlite3.Row]:
    with connect(path) as conn:
        return conn.execute("SELECT * FROM buyers ORDER BY name").fetchall()


def get_buyer(buyer_id: int, path=None):
    with connect(path) as conn:
        return conn.execute("SELECT * FROM buyers WHERE id = ?", (buyer_id,)).fetchone()


def add_listing(farmer_name, phone, share_contact, residue_key, quantity_kg,
                condition, district, price_per_kg, path=None) -> int:
    with connect(path) as conn:
        cur = conn.execute(
            """INSERT INTO listings (farmer_name, phone, share_contact, residue_key,
               quantity_kg, condition, district, price_per_kg)
               VALUES (?,?,?,?,?,?,?,?)""",
            (farmer_name or None, phone or None, int(bool(share_contact and phone)),
             residue_key, quantity_kg, condition, district.strip(), price_per_kg))
        return cur.lastrowid


def get_listing(listing_id: int, path=None):
    with connect(path) as conn:
        return conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()


def listings_by_phone(phone: str, path=None) -> list[sqlite3.Row]:
    with connect(path) as conn:
        return conn.execute(
            "SELECT * FROM listings WHERE phone = ? ORDER BY id DESC", (phone,)).fetchall()


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


def requests_for_buyer(buyer_id: int, path=None) -> list[sqlite3.Row]:
    with connect(path) as conn:
        return conn.execute(
            """SELECT r.id, r.status, r.created_at, l.residue_key, l.quantity_kg,
                      l.condition, l.district, l.price_per_kg,
                      l.farmer_name, l.phone, l.share_contact
               FROM connection_requests r JOIN listings l ON l.id = r.listing_id
               WHERE r.buyer_id = ? ORDER BY r.id DESC""", (buyer_id,)).fetchall()


def set_request_status(request_id: int, status: str, path=None) -> None:
    if status not in ("accepted", "declined"):
        raise ValueError("status must be accepted or declined")
    with connect(path) as conn:
        conn.execute("UPDATE connection_requests SET status = ? WHERE id = ?", (status, request_id))
