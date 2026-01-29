import io
import os
import json
import zipfile
import unicodedata
from datetime import datetime

import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

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

# ✅ OPTION A: IBAN REMOVED (Account is the only column)
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
    "REMARKS",
]

# =========================================================
# HELPERS
# =========================================================
def normalize_text(value) -> str:
    """Safe text for PDF (avoid encoding/control chars)."""
    if value is None:
        return ""
    s = str(value).strip()

    # Replace weird line breaks/tabs
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")

    # Remove control chars (except \n)
    s = "".join(ch for ch in s if ch == "\n" or ord(ch) >= 32)

    # Normalize unicode (avoid PDF rendering issues)
    s = unicodedata.normalize("NFKD", s)
    return s


def load_counter() -> int:
    if not os.path.exists(COUNTER_FILE):
        return 0
    try:
        with open(COUNTER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return int(data.get("counter", 0))
    except Exception:
        return 0


def save_counter(counter: int) -> None:
    with open(COUNTER_FILE, "w", encoding="utf-8") as f:
        json.dump({"counter": counter}, f)


def next_reference_number(prefix: str) -> str:
    c = load_counter() + 1
    save_counter(c)
    return f"{prefix}{c:06d}"


def validate_columns(df: pd.DataFrame) -> list[str]:
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    return missing


def safe_filename(name: str) -> str:
    name = normalize_text(name)
    name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name)
    return name.strip("_") or "document"


# =========================================================
# PDF GENERATION
# =========================================================
def draw_label_value(c, x, y, label, value, max_width=520):
    """Draw label and value; wraps value."""
    label = normalize_text(label)
    value = normalize_text(value)

    c.setFont("Helvetica-Bold", 10)
    c.drawString(x, y, label)

    c.setFont("Helvetica", 10)
    text_obj = c.beginText(x + 140, y)
    text_obj.setLeading(12)

    # basic wrap
    words = value.replace("\n", " \n ").split(" ")
    line = ""
    for w in words:
        if w == "\n":
            text_obj.textLine(line.rstrip())
            line = ""
            continue

        candidate = (line + " " + w).strip()
        if c.stringWidth(candidate, "Helvetica", 10) <= (max_width - (x + 140)):
            line = candidate
        else:
            if line:
                text_obj.textLine(line)
            line = w

    if line:
        text_obj.textLine(line)

    c.drawText(text_obj)


def generate_pdf_bytes(row: dict, defaults: dict) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=LETTER)
    width, height = LETTER

    # Header
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, height - 50, "Payment Instruction")

    c.setFont("Helvetica", 10)
    c.drawString(40, height - 70, f"Processed by: {normalize_text(defaults['processed_by'])}")
    c.drawString(40, height - 85, f"Sender: {normalize_text(defaults['sender'])}")
    c.drawString(40, height - 100, f"Status: {normalize_text(defaults['status'])}")

    # Reference & date
    ref = next_reference_number(defaults["prefix"])
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, height - 125, "Reference Number:")
    c.setFont("Helvetica", 10)
    c.drawString(180, height - 125, ref)

    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, height - 140, "Generated:")
    c.setFont("Helvetica", 10)
    c.drawString(180, height - 140, now)

    # Body
    y = height - 175
    gap = 18

    # Pull fields (Account is the only one)
    data = {
        "Amount": row.get("Amount", ""),
        "Currency": row.get("Currency", ""),
        "Purpose": row.get("Purpose", ""),
        "Beneficiary Name": row.get("Beneficiary Name", ""),
        "Beneficiary Address": row.get("Beneficiary Address", ""),
        "Bank Name": row.get("Bank Name", ""),
        "Bank Address": row.get("Bank Address", ""),
        "SWIFT Code": row.get("SWIFT Code", ""),
        "Account": row.get("Account", ""),
        "REMARKS": row.get("REMARKS", ""),
    }

    draw_label_value(c, 40, y, "Amount:", f"{data['Amount']} {data['Currency']}")
    y -= gap * 2

    draw_label_value(c, 40, y, "Purpose:", data["Purpose"])
    y -= gap * 2

    draw_label_value(c, 40, y, "Beneficiary Name:", data["Beneficiary Name"])
    y -= gap * 2

    draw_label_value(c, 40, y, "Beneficiary Address:", data["Beneficiary Address"])
    y -= gap * 3

    draw_label_value(c, 40, y, "Bank Name:", data["Bank Name"])
    y -= gap * 2

    draw_label_value(c, 40, y, "Bank Address:", data["Bank Address"])
    y -= gap * 3

    draw_label_value(c, 40, y, "SWIFT Code:", data["SWIFT Code"])
    y -= gap * 2

    # ✅ Account (replaces IBAN)
    draw_label_value(c, 40, y, "Account:", data["Account"])
    y -= gap * 2

    draw_label_value(c, 40, y, "Remarks:", data["REMARKS"])
    y -= gap * 2

    # Footer
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(40, 30, "Generated by internal tool. Please verify bank details before execution.")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()


# =========================================================
# STREAMLIT APP
# =========================================================
st.set_page_config(page_title="PDF Generator", layout="centered")
st.title("PDF Generator (Batch)")

st.caption("Upload an Excel/CSV file. One PDF will be generated per row and downloaded as a ZIP.")

with st.expander("Defaults", expanded=True):
    processed_by = st.text_input("Processed by", value=DEFAULTS["processed_by"])
    sender = st.text_input("Sender", value=DEFAULTS["sender"])
    status = st.text_input("Status", value=DEFAULTS["status"])
    prefix = st.text_input("Reference Prefix", value=DEFAULTS["prefix"])

defaults = {
    "processed_by": processed_by,
    "sender": sender,
    "status": status,
    "prefix": prefix,
}

uploaded = st.file_uploader("Upload file", type=["xlsx", "xls", "csv"])

if uploaded:
    try:
        if uploaded.name.lower().endswith(".csv"):
            df = pd.read_csv(uploaded)
        else:
            df = pd.read_excel(uploaded)

        # Normalize column names exactly (trim spaces)
        df.columns = [str(c).strip() for c in df.columns]

        missing = validate_columns(df)
        if missing:
            st.error(f"Missing columns: {missing}")
            st.info(f"Required columns are: {REQUIRED_COLS}")
            st.stop()

        st.success(f"File loaded. Rows: {len(df)}")
        st.dataframe(df.head(20), use_container_width=True)

        if st.button("Generate ZIP of PDFs"):
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, row in df.iterrows():
                    row_dict = {k: row.get(k, "") for k in df.columns}
                    pdf_bytes = generate_pdf_bytes(row_dict, defaults)

                    ben = safe_filename(row_dict.get("Beneficiary Name", f"row_{i+1}"))
                    filename = f"{i+1:03d}_{ben}.pdf"
                    zf.writestr(filename, pdf_bytes)

            zip_buffer.seek(0)
            st.download_button(
                label="Download ZIP",
                data=zip_buffer.getvalue(),
                file_name="pdfs.zip",
                mime="application/zip",
            )

    except Exception as e:
        st.error(f"Error reading file: {e}")
