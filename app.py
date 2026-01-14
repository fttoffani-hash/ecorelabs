import io
import os
import json
import zipfile
from datetime import datetime

import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

# -----------------------------
# Config
# -----------------------------
COUNTER_FILE = "counter.json"

DEFAULTS = {
    "processed_by": "Edgecore Labs Inc.",
    "status": "Processing",
    "sender": "ENOR",
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

# -----------------------------
# Helpers
# -----------------------------
def safe_str(v) -> str:
    return "" if pd.isna(v) else str(v)

def money_fmt(x) -> str:
    try:
        return f"{float(x):,.2f}"
    except Exception:
        return safe_str(x)

def pick_account(iban, acct) -> str:
    iban = safe_str(iban).strip()
    acct = safe_str(acct).strip()
    return iban if iban else acct

def load_counter():
    # no Streamlit Cloud, esse arquivo fica no mesmo diretório do app
    if not os.path.exists(COUNTER_FILE):
        return {"last_seq": 0}

    try:
        with open(COUNTER_FILE, "r") as f:
            c = json.load(f)
        if "last_seq" not in c:
            c["last_seq"] = 0
        return c
    except Exception:
        return {"last_seq": 0}

def save_counter(c):
    with open(COUNTER_FILE, "w") as f:
        json.dump(c, f)

def next_sequence(counter) -> int:
    counter["last_seq"] += 1
    return counter["last_seq"]

def build_reference(prefix: str, currency: str, dt: datetime, seq: int) -> str:
    # EDG-{CUR}{MMDDYY}{SEQ6}
    return f"{prefix}{currency}{dt.strftime('%m%d%y')}{seq:06d}"

def gen_pdf(data: dict) -> bytes:
    """
    Gera PDF em memória e devolve bytes.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    w, h = LETTER

    # Título
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, h - 60, "WIRE TRANSFER CONFIRMATION")

    y = h - 95

    def field(label, value):
        nonlocal y
        c.setFont("Helvetica-Bold", 10)
        c.drawString(50, y, label)
        c.setFont("Helvetica", 10)

        txt = str(value) if value is not None else ""

        # quebra simples para caber
        max_len = 85
        lines = [txt[i:i + max_len] for i in range(0, len(txt), max_len)] or [""]

        c.drawString(200, y, lines[0])
        y -= 16
        for extra in lines[1:]:
            c.drawString(200, y, extra)
            y -= 16

    # Campos
    field("Processed By:", data["processed_by"])
    field("Date:", data["date_str"])
    field("Status:", data["status"])
    field("Reference Number:", data["reference_number"])
    field("Sender:", data["sender"])
    field("Currency:", data["currency"])
    field("Amount:", data["amount_str"])
    field("Beneficiary Name:", data["beneficiary_name"])
    field("Beneficiary Address:", data["beneficiary_address"])
    field("Beneficiary Account No.:", data["beneficiary_account_no"])
    field("Beneficiary Bank:", data["beneficiary_bank"])
    field("Bank Address:", data["bank_address"])
    field("SWIFT Code:", data["swift"])
    field("Intermediary Bank:", "-")
    field("Intermediary Bank SWIFT:", "-")
    field("Purpose of Payment:", data["purpose"])
    field("Details:", "")
    field("Additional Remarks:", data.get("remarks", ""))

    # Rodapé
    y -= 10
    c.setFont("Helvetica", 9)
    c.drawString(
        50, y,
        "This document confirms the wire transfer has been placed in pursuant to our standard terms and conditions."
    )
    y -= 14
    c.drawString(50, y, f"Generated on {data['generated_on']}")

    c.showPage()
    c.save()

    buf.seek(0)
    return buf.read()

# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="Pré-recibos via Excel", layout="centered")
st.title("Gerador de Pré-Recibos (Excel → PDFs)")
st.write(
    f"**Processed By:** {DEFAULTS['processed_by']}  |  "
    f"**Sender:** {DEFAULTS['sender']}  |  "
    f"**Status:** {DEFAULTS['status']}  |  "
    f"**SEQ:** contínuo (6 dígitos)"
)

uploaded = st.file_uploader("Envie o Excel (template do cliente)", type=["xlsx"])

if uploaded:
    df = pd.read_excel(uploaded)

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        st.error(f"Faltando colunas no Excel: {missing}")
        st.stop()

    if df.empty:
        st.warning("A planilha veio sem linhas.")
        st.stop()

    counter = load_counter()
    dt = datetime.now()

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for _, r in df.iterrows():
            seq = next_sequence(counter)
            currency = safe_str(r["Currency"]).strip()
            ref = build_reference(DEFAULTS["prefix"], currency, dt, seq)

            beneficiary_address = safe_str(r["Beneficiary Address"]).strip()
            beneficiary_country = safe_str(r.get("Beneficiary Country", "")).strip()
            if beneficiary_country:
                beneficiary_address = f"{beneficiary_address}\n{beneficiary_country}"

            bank_address = safe_str(r["Bank Address"]).strip()
            bank_country = safe_str(r.get("Bank Country", "")).strip()
            if bank_country:
                bank_address = f"{bank_address}\n{bank_country}"

            data = {
                "processed_by": DEFAULTS["processed_by"],
                "sender": DEFAULTS["sender"],
                "status": DEFAULTS["status"],
                "date_str": dt.strftime("%m/%d/%Y"),
                "generated_on": dt.strftime("%m/%d/%Y at %H:%M:%S"),
                "reference_number": ref,
                "currency": currency,
                "amount_str": money_fmt(r["Amount"]),
                "beneficiary_name": safe_str(r["Beneficiary Name"]).strip(),
                "beneficiary_address": beneficiary_address,
                "beneficiary_account_no": pick_account(r.get("IBAN"), r.get("Account")),
                "beneficiary_bank": safe_str(r["Bank Name"]).strip(),
                "bank_address": bank_address,
                "swift": safe_str(r["SWIFT Code"]).strip(),
                "purpose": safe_str(r["Purpose"]).strip(),
                "remarks": safe_str(r.get("REMARKS/OBSERVATIONS", "")).strip(),
            }

            pdf_bytes = gen_pdf(data)
            zf.writestr(f"{ref}.pdf", pdf_bytes)

    save_counter(counter)

    zip_buf.seek(0)
    st.success(f"Pronto! Gereis {len(df)} PDFs (1 por linha).")

    st.download_button(
        "Baixar ZIP com os PDFs",
        data=zip_buf.getvalue(),
        file_name=f"pre-receipts_{dt.strftime('%Y%m%d_%H%M%S')}.zip",
        mime="application/zip",
    )
