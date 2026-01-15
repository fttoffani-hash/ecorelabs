import io
import os
import json
import zipfile
import re
import unicodedata
from datetime import datetime

import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics

# =========================================================
# CONFIG
# =========================================================
COUNTER_FILE = "counter.json"

DEFAULTS = {
    "processed_by": "Edgecore Labs Inc.",
    "sender": "ENOR",
    "status": "Processing",
    "prefix": "EDG-",
}

REQUIRED_COLS = [
    "Amount",
    "Currency",
    "Purpose",
    "Beneficiary Name",
    "Beneficiary Address",
    "Bank Name",
    "Bank Address",
    "SWIFT Code",
    "Account",
    "IBAN",
    "REMARKS/OBSERVATIONS",
]

# =========================================================
# TEXT SANITIZATION (remove black boxes)
# =========================================================
def safe_isna(v) -> bool:
    try:
        return pd.isna(v)
    except Exception:
        return False

def sanitize_text(v) -> str:
    if v is None or safe_isna(v):
        return ""

    s = str(v)
    s = unicodedata.normalize("NFKC", s)

    cleaned = []
    for ch in s:
        cat = unicodedata.category(ch)
        if cat.startswith("C"):
            continue
        cleaned.append(ch)
    s = "".join(cleaned)

    s = s.replace("\u00A0", " ").strip()
    s = re.sub(r"\s+", " ", s)

    # Helvetica safe
    s = s.encode("latin-1", errors="replace").decode("latin-1")
    s = s.strip()
    return "" if s.lower() == "nan" else s

def money_fmt(v) -> str:
    try:
        if v is None or safe_isna(v):
            return ""
        return f"{float(v):,.2f}"
    except Exception:
        return ""

def clean_account(v: str) -> str:
    s = sanitize_text(v)
    s = re.sub(r"^(acc|acct|account)\s*[:\-]\s*", "", s, flags=re.IGNORECASE)
    return s.strip()

def pick_account(iban, account) -> str:
    return clean_account(iban) if sanitize_text(iban) else clean_account(account)

def append_country(address, country) -> str:
    a = sanitize_text(address)
    c = sanitize_text(country)
    if not c:
        return a
    if c.lower() in a.lower():
        return a
    if not a:
        return c
    return f"{a}, {c}"

def normalize_swift(v) -> str:
    s = sanitize_text(v).upper()
    return re.sub(r"[^A-Z0-9]", "", s)

# =========================================================
# COUNTER (RESET DIÁRIO)
# counter.json vai ficar assim, por exemplo:
# {"last_date": "011426", "last_seq": 8}
# =========================================================
def load_counter():
    if not os.path.exists(COUNTER_FILE):
        return {"last_date": "", "last_seq": 0}
    try:
        with open(COUNTER_FILE, "r") as f:
            c = json.load(f)
        if "last_date" not in c:
            c["last_date"] = ""
        if "last_seq" not in c:
            c["last_seq"] = 0
        return c
    except Exception:
        return {"last_date": "", "last_seq": 0}

def save_counter(counter):
    with open(COUNTER_FILE, "w") as f:
        json.dump(counter, f)

def next_sequence_for_today(counter, today_mmddyy: str) -> int:
    """
    Se mudou o dia (MMDDYY), reseta para 1.
    """
    if counter.get("last_date") != today_mmddyy:
        counter["last_date"] = today_mmddyy
        counter["last_seq"] = 0
    counter["last_seq"] += 1
    return counter["last_seq"]

def build_reference(currency, mmddyy, seq):
    cur = sanitize_text(currency).upper()
    return f"{DEFAULTS['prefix']}{cur}{mmddyy}{seq:03d}"

# =========================================================
# WRAP POR LARGURA (EVITA CORTE)
# =========================================================
def wrap_to_width(text: str, font_name: str, font_size: int, max_width: float):
    t = sanitize_text(text)
    if not t:
        return []

    def width(s):
        return pdfmetrics.stringWidth(s, font_name, font_size)

    words = t.split(" ")
    lines = []
    cur = ""

    for w in words:
        if not cur:
            cur = w
        else:
            test = f"{cur} {w}"
            if width(test) <= max_width:
                cur = test
            else:
                lines.append(cur)
                cur = w

        while cur and width(cur) > max_width:
            cut = len(cur)
            while cut > 1 and width(cur[:cut]) > max_width:
                cut -= 1
            lines.append(cur[:cut])
            cur = cur[cut:]

    if cur:
        lines.append(cur)

    return lines

# =========================================================
# PDF
# =========================================================
def generate_pdf(data):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=LETTER)
    page_w, page_h = LETTER

    left_margin = 50
    right_margin = 50
    label_x = left_margin
    value_x = 220
    max_value_width = page_w - right_margin - value_x

    title_font = ("Helvetica-Bold", 14)
    label_font = ("Helvetica-Bold", 10)
    value_font = ("Helvetica", 10)
    footer_font = ("Helvetica", 9)

    c.setFont(*title_font)
    c.drawString(left_margin, page_h - 60, "WIRE TRANSFER CONFIRMATION")

    y = page_h - 95
    line_gap = 16

    def field(label, value):
        nonlocal y
        value = sanitize_text(value)
        if not value:
            return

        c.setFont(*label_font)
        c.drawString(label_x, y, label)

        c.setFont(*value_font)
        lines = wrap_to_width(value, value_font[0], value_font[1], max_value_width)
        c.drawString(value_x, y, lines[0])
        y -= line_gap
        for ln in lines[1:]:
            c.drawString(value_x, y, ln)
            y -= line_gap

    field("Processed By:", data["processed_by"])
    field("Date:", data["date"])
    field("Status:", data["status"])
    field("Reference Number:", data["reference"])
    field("Sender:", data["sender"])
    field("Currency:", data["currency"])
    field("Amount:", data["amount"])
    field("Beneficiary Name:", data["beneficiary_name"])
    field("Beneficiary Address:", data["beneficiary_address"])
    field("Beneficiary Account No.:", data["beneficiary_account"])
    field("Beneficiary Bank:", data["bank_name"])
    field("Bank Address:", data["bank_address"])
    field("SWIFT Code:", data["swift"])
    field("Intermediary Bank:", "-")
    field("Intermediary Bank SWIFT:", "-")
    field("Purpose of Payment:", data["purpose"])
    field("Additional Remarks:", data["remarks"])

    y -= 10
    c.setFont(*footer_font)
    c.drawString(
        left_margin,
        y,
        "This document confirms the wire transfer has been placed in pursuant to our standard terms and conditions."
    )
    y -= 14
    c.drawString(left_margin, y, f"Generated on {sanitize_text(data['generated_on'])}")

    c.showPage()
    c.save()

    buffer.seek(0)
    return buffer.read()

# =========================================================
# STREAMLIT UI
# =========================================================
st.set_page_config(page_title="Pre-Receipt Generator", layout="centered")
st.title("Pre-Receipt Generator (Excel → PDF)")

uploaded = st.file_uploader("Upload Excel file", type=["xlsx"])

if uploaded:
    df = pd.read_excel(uploaded)

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        st.error(f"Missing columns: {missing}")
        st.stop()

    counter = load_counter()
    now = datetime.now()

    mmddyy = now.strftime("%m%d%y")  # MMDDYY do dia
    date_str = now.strftime("%m/%d/%Y")

    zip_buffer = io.BytesIO()
    generated = 0
    skipped = 0

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for _, row in df.iterrows():
            currency = sanitize_text(row.get("Currency")).upper()
            amount = money_fmt(row.get("Amount"))

            if not currency or not amount:
                skipped += 1
                continue

            seq = next_sequence_for_today(counter, mmddyy)  # RESSETA DIÁRIO
            ref = build_reference(currency, mmddyy, seq)

            data = {
                "processed_by": DEFAULTS["processed_by"],
                "sender": DEFAULTS["sender"],
                "status": DEFAULTS["status"],
                "date": date_str,
                "generated_on": now.strftime("%m/%d/%Y at %H:%M:%S"),
                "reference": ref,
                "currency": currency,
                "amount": amount,
                "beneficiary_name": sanitize_text(row.get("Beneficiary Name")),
                "beneficiary_address": append_country(
                    row.get("Beneficiary Address"),
                    row.get("Beneficiary Country")
                ),
                "beneficiary_account": pick_account(
                    row.get("IBAN"),
                    row.get("Account")
                ),
                "bank_name": sanitize_text(row.get("Bank Name")),
                "bank_address": append_country(
                    row.get("Bank Address"),
                    row.get("Bank Country")
                ),
                "swift": normalize_swift(row.get("SWIFT Code")),
                "purpose": sanitize_text(row.get("Purpose")),
                "remarks": sanitize_text(row.get("REMARKS/OBSERVATIONS")),
            }

            pdf = generate_pdf(data)

            # Nome do arquivo: MMDDYY + seq 001 (e inclui currency pra evitar colisão)
            filename = f"{mmddyy}_{seq:03d}_{currency}.pdf"
            zipf.writestr(filename, pdf)
            generated += 1

    save_counter(counter)

    zip_buffer.seek(0)
    st.success(f"PDFs generated: {generated} | Skipped lines: {skipped}")

    st.download_button(
        "Download ZIP",
        zip_buffer,
        file_name=f"pre_receipts_{mmddyy}.zip",
        mime="application/zip",
        data=zip_buffer.getvalue(),
    )
