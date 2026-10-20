# CropLeftover AI

Reuse ideas and buyer matching for crop residues, in English, Tamil, Telugu and Hindi.
Two versions live in this repository:

| Folder / file | What it is |
|---|---|
| `app.py` and friends | Streamlit app (Python). Farmer side with reuse suggestions, buyer matching and connection requests. |
| `web/index.html` | Single-file browser app with farmer **and buyer** registration. Open it in any browser. Offline mode keeps data on the device; it only shares data between users when published as a Claude artifact. |
| `docs/` | Excel datasets: 500 fictional demo buyers, and a 32-residue knowledge dataset (all rows unverified, see the README sheet). |


Multilingual (English, Tamil, Telugu, Hindi) Streamlit app that suggests reuse options for crop residues
and matches farmer listings with buyers. Rule-based, text-only. No ML model, no image or voice input.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Open the URL Streamlit prints. On a phone on the same Wi-Fi, use the "Network URL".
The database (`cropleftover.db`) is created and filled from `data/*.csv` on first run.

## Optional: AI explanations (Gemini)

The app works fully without this. If you set a key, a button appears on the Results page that
rewrites the rule-based suggestions in simple words in the chosen language. The model is told to add no new facts.

```bash
export GEMINI_API_KEY="your-key"        # Windows: set GEMINI_API_KEY=your-key
export GEMINI_MODEL="gemini-2.5-flash"  # optional; change if Google retires this name
```

On Streamlit Community Cloud, put `GEMINI_API_KEY = "..."` in the app's Secrets. Never commit the key.
Calls happen only when the farmer taps the button, and each result is cached per listing and language.

## How it works

| File | Purpose |
|---|---|
| `app.py` | Screens: Add residue, Results, My requests, Buyer view (demo) |
| `db.py` | SQLite tables: residues, reuse_rules, buyers, listings, connection_requests |
| `matching.py` | Condition-aware reuse rules and buyer scoring (0-100) |
| `i18n.py` | All text in 4 languages |
| `ai_explain.py` | Optional Gemini explanation |
| `data/residues.csv` | 8 starter residues |
| `data/reuse_rules.csv` | Which uses are allowed for which condition, plus caution keys |
| `data/demo_buyers.csv` | 18 fictional buyers, labelled DEMO in the app |
| `tests/test_logic.py` | `python tests/test_logic.py` checks rules, matching, workflow, translations |

**Matching:** buyers must want the same residue and accept its condition. Score = district (40 same / 10 other)
+ quantity (35 fits / 25 you have more / 5 under minimum) + price (25 within range / 15 no price / 0 too high).

**Safety rules built in:** moldy residue only gets composting. Groundnut shells are never suggested as feed unless dry,
and carry an aflatoxin warning. Feed uses always say to ask a veterinarian. A farmer's phone number is shown to a
buyer only if the farmer ticked consent and the buyer accepted the request.

## Before real farmers use it

1. **Verify the dataset.** `reuse_rules.csv` is a starter based on general knowledge. Every residue is marked
   `unverified` and the app says so. Review each row with your agricultural university, ICAR or a KVK, add real
   source notes, then set `source_status` to `verified` in `residues.csv`.
2. **Replace demo buyers** with real, consenting buyers (set `is_demo` to 0 for those rows).
3. **Have native speakers review** the Tamil, Telugu and Hindi text in `i18n.py`.
4. **Add logins.** There are no accounts: "My requests" works from the current browser session or by phone number,
   and the Buyer view is a demo. Real use needs authentication and OTP verification.
5. **Hosting:** Streamlit Community Cloud's disk is not permanent, so listings can be lost on restart. Use a
   hosted database for anything beyond a demo.

## Changing the data

Edit the CSVs, delete `cropleftover.db`, and restart. To add a residue, add rows to `residues.csv` and
`reuse_rules.csv` and a translation entry in `RESIDUES` in `i18n.py`.
