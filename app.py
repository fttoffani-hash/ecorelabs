import io
import os
import json
import zipfile
import re
from datetime import datetime

import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

# =========================================================
# CONFIGURAÇÃO
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
# FUNÇÕES UTILITÁRIAS (ANTI-ERRO)
# =========================================================
def safe_str(v):
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


def money_fmt(v):
    try:
        if v is None or pd.isna(v):
            return ""
        return f"{float(v):,.2f}"
    except Exception:
        return ""


def clean_account(v):
    s = safe_str(v)
    return re.sub(r"^(acc|acct|account)\s*[:\-]?\s*", "", s, flags=re.IGNORECASE).strip()


def pick_account(iban, account):
    return clean_account(iban) if safe_str(iban) else clean_account(account)


def append_country(address, country):
    a = safe_str(address)
    c = safe_str(country)
    if not c:
        return a
    if c.lower() in a.lower():
        return a
    if not a:
        return c
    return f"{a}, {c}"


def load_counter():
    if not os.path.exists(COUNTER_FILE):
        return {"last_seq": 0}
    try:
        with open(COUNTER_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"last_seq": 0}


def save_counter(counter):
    with open(COUNTER_FILE, "w") as f:
        json.dump(counter, f)


def next_sequence(counter):
    counter["last_seq"] += 1
    return counter["last_seq"]


def build_reference(currency, date, seq):
    return f"{DEFAULTS['prefix']}{currency}{date.strftime('%m%d%y')}{seq:06d}"


def wrap_text(text, limit=90):
    t = safe_str(text)
    return [t[i:i + limit] for i in range(0, len(t), limit)] if t else []


# =========================================================
# PDF
# =========================================================
def generate_pdf(data):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=LETTER)
    _, h = LETTER

    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, h - 60, "WIRE TRANSFER CONFIRMATION")

    y = h - 95

    def field(label, value):
        nonlocal y
        if not safe_str(value):
            return
        c.setFont("Helvetica-Bold", 10)
        c.drawString(50, y, label)
        c.setFont("Helvetica", 10)
        lines = wrap_text(value)
        c.drawString(200, y, lines[0])
        y -= 16
        for line in lines[1:]:
            c.drawString(200, y, line)
            y -= 16

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
    c.setFont("Helvetica", 9)
    c.drawString(
        50,
        y,
        "This document confirms the wire transfer has been placed in pursuant to our standard terms and conditions."
    )
    y -= 14
    c.drawString(50, y, f"Generated on {data['generated_on']}")

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

    zip_buffer = io.BytesIO()
    generated = 0
    skipped = 0

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for _, row in df.iterrows():
            currency = safe_str(row.get("Currency")).upper()
            amount = money_fmt(row.get("Amount"))

            if not currency or not amount:
                skipped += 1
                continue

            seq = next_sequence(counter)
            ref = build_reference(currency, now, seq)

            data = {
                "processed_by": DEFAULTS["processed_by"],
                "sender": DEFAULTS["sender"],
                "status": DEFAULTS["status"],
                "date": now.strftime("%m/%d/%Y"),
                "generated_on": now.strftime("%m/%d/%Y at %H:%M:%S"),
                "reference": ref,
                "currency": currency,
                "amount": amount,
                "beneficiary_name": safe_str(row.get("Beneficiary Name")),
                "beneficiary_address": append_country(
                    row.get("Beneficiary Address"),
                    row.get("Beneficiary Country")
                ),
                "beneficiary_account": pick_account(
                    row.get("IBAN"),
                    row.get("Account")
                ),
                "bank_name": safe_str(row.get("Bank Name")),
                "bank_address": append_country(
                    row.get("Bank Address"),
                    row.get("Bank Country")
                ),
                "swift": safe_str(row.get("SWIFT Code")),
                "purpose": safe_str(row.get("Purpose")),
                "remarks": safe_str(row.get("REMARKS/OBSERVATIONS")),
            }

            pdf = generate_pdf(data)
            zipf.writestr(f"{ref}.pdf", pdf)
            generated += 1

    save_counter(counter)

    zip_buffer.seek(0)

    st.success(f"PDFs generated: {generated} | Skipped lines: {skipped}")

    st.download_button(
        "Download ZIP",
        zip_buffer,
        file_name=f"pre_receipts_{now.strftime('%Y%m%d_%H%M%S')}.zip",
        mime="application/zip"
    )
