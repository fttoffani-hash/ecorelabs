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
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import black, white


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

# Colunas mínimas (IBAN é opcional; Account existe como coluna)
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

# Variações comuns para "Reference" (vamos tentar achar em qualquer uma)
REFERENCE_KEYS = [
    "Reference",
    "Reference Number",
    "Payment Reference",
    "Payment reference",
    "Customer Reference",
    "Client Reference",
    "Ref",
    "REF",
]

# Fonte opcional pra evitar “quadradinhos” (tofu) em nomes/endereços com acento
# Se você colocar o arquivo DejaVuSans.ttf na mesma pasta do app.py, ele usa.
TTF_FONT_PATH = "DejaVuSans.ttf"
TTF_FONT_NAME = "DejaVuSans"


# =========================================================
# HELPERS
# =========================================================
def load_counter() -> int:
    if not os.path.exists(COUNTER_FILE):
        return 1
    try:
        with open(COUNTER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return int(data.get("counter", 1))
    except Exception:
        return 1


def save_counter(counter: int) -> None:
    with open(COUNTER_FILE, "w", encoding="utf-8") as f:
        json.dump({"counter": counter}, f)


def next_reference(prefix: str) -> str:
    c = load_counter()
    ref = f"{prefix}{c:06d}"
    save_counter(c + 1)
    return ref


def normalize_text(value) -> str:
    """
    - Converte para string
    - Remove caracteres de controle/invisíveis que podem causar artefatos
    - Normaliza unicode
    - Remove quebras exageradas
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    s = str(value)

    # Normaliza unicode (ex: acentos)
    s = unicodedata.normalize("NFKC", s)

    # Remove caracteres de controle (exceto \n e \t se você quiser; aqui removo todos)
    s = "".join(ch for ch in s if ch.isprintable())

    # Remove alguns chars comuns invisíveis
    s = s.replace("\u200b", "").replace("\ufeff", "")

    # Colapsa espaços
    s = re.sub(r"[ \t]+", " ", s).strip()
    return s


def pick_reference_from_row(row: dict) -> str:
    # Procura em chaves candidatas
    for k in REFERENCE_KEYS:
        if k in row:
            v = normalize_text(row.get(k))
            if v:
                return v

    # fallback: tenta achar qualquer coluna que contenha "reference"
    for k in row.keys():
        if isinstance(k, str) and "reference" in k.lower():
            v = normalize_text(row.get(k))
            if v:
                return v

    return ""


def register_font_if_available() -> str:
    """
    Retorna o nome da fonte a ser usada.
    Se existir DejaVuSans.ttf na pasta, registra e usa.
    Caso contrário, usa Helvetica.
    """
    try:
        if os.path.exists(TTF_FONT_PATH):
            pdfmetrics.registerFont(TTFont(TTF_FONT_NAME, TTF_FONT_PATH))
            return TTF_FONT_NAME
    except Exception:
        pass
    return "Helvetica"


def validate_columns(df: pd.DataFrame) -> list:
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    return missing


def ensure_account_or_iban(row: dict) -> bool:
    """
    Garante que exista Account ou IBAN preenchido (IBAN pode existir ou não como coluna).
    """
    account = normalize_text(row.get("Account"))
    iban = normalize_text(row.get("IBAN")) if "IBAN" in row else ""
    return bool(account or iban)


def format_amount(value) -> str:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ""
        # Se vier como string, tenta limpar
        s = str(value).replace(",", "")
        x = float(s)
        return f"{x:,.2f}"
    except Exception:
        return normalize_text(value)


def safe_draw_label_value(c: canvas.Canvas, x_label, x_value, y, label, value, font_name, font_size=10):
    """
    Desenha label e value sem desenhar retângulos preenchidos (evita black boxes).
    """
    c.setFillColor(black)
    c.setFont(font_name, font_size)
    c.drawString(x_label, y, label)

    c.setFont(font_name, font_size)
    c.drawString(x_value, y, value)


def wrap_text(c: canvas.Canvas, text: str, max_width: float, font_name: str, font_size: int) -> list:
    """
    Quebra texto em linhas para caber em max_width.
    """
    c.setFont(font_name, font_size)
    words = text.split(" ")
    lines = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        if c.stringWidth(test, font_name, font_size) <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# =========================================================
# PDF GENERATION
# =========================================================
def build_pdf_bytes(data: dict, defaults: dict) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=LETTER)
    width, height = LETTER

    font_name = register_font_if_available()

    # Base layout
    margin = 0.7 * inch
    x_label = margin
    x_value = margin + 2.2 * inch
    y = height - margin

    # Header
    c.setFillColor(black)
    c.setFont(font_name, 16)
    c.drawString(margin, y, "Pre-Receipt")
    y -= 0.35 * inch

    c.setFont(font_name, 10)
    c.drawString(margin, y, f"Processed by: {normalize_text(defaults.get('processed_by'))}")
    y -= 0.2 * inch
    c.drawString(margin, y, f"Sender: {normalize_text(defaults.get('sender'))}")
    y -= 0.2 * inch
    c.drawString(margin, y, f"Status: {normalize_text(defaults.get('status'))}")
    y -= 0.2 * inch
    c.drawString(margin, y, f"Generated at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    y -= 0.35 * inch

    # Divider line (sem preenchimento, só linha)
    c.setStrokeColor(black)
    c.setLineWidth(1)
    c.line(margin, y, width - margin, y)
    y -= 0.35 * inch

    # Fields
    # (Use normalize_text e sem retângulos preenchidos para evitar "black box")
    fields = [
        ("Reference ID:", normalize_text(data.get("_generated_reference_id", ""))),
        ("Amount:", f"{format_amount(data.get('Amount'))} {normalize_text(data.get('Currency'))}".strip()),
        ("Purpose:", normalize_text(data.get("Purpose"))),
        ("Beneficiary Name:", normalize_text(data.get("Beneficiary Name"))),
        ("Beneficiary Address:", normalize_text(data.get("Beneficiary Address"))),
        ("Bank Name:", normalize_text(data.get("Bank Name"))),
        ("Bank Address:", normalize_text(data.get("Bank Address"))),
        ("SWIFT Code:", normalize_text(data.get("SWIFT Code"))),
        ("Account:", normalize_text(data.get("Account"))),
    ]

    # IBAN opcional (se tiver)
    if "IBAN" in data and normalize_text(data.get("IBAN")):
        fields.append(("IBAN:", normalize_text(data.get("IBAN"))))

    # Remarks
    fields.append(("REMARKS:", normalize_text(data.get("REMARKS"))))

    # ==========
    # Reference (customer payment reference) DEVE SER O ÚLTIMO
    # ==========
    customer_ref = normalize_text(data.get("_customer_reference", ""))
    if customer_ref:
        fields.append(("Payment Reference:", customer_ref))

    # render fields with wrapping
    max_width = (width - margin) - x_value
    for label, value in fields:
        if y < margin + 1.2 * inch:
            c.showPage()
            y = height - margin
            c.setFont(font_name, 10)

        # label line
        c.setFillColor(black)
        c.setFont(font_name, 10)
        c.drawString(x_label, y, label)

        # value (wrap)
        value = value if value else "-"
        lines = wrap_text(c, value, max_width, font_name, 10)
        first = True
        for line in lines:
            if first:
                c.drawString(x_value, y, line)
                first = False
            else:
                y -= 0.18 * inch
                c.drawString(x_value, y, line)

        y -= 0.26 * inch

    # Footer
    y = max(y, margin + 0.7 * inch)
    c.setFont(font_name, 8)
    c.setFillColor(black)
    c.drawString(margin, margin * 0.65, "This document is generated for pre-receipt purposes only.")

    c.showPage()
    c.save()

    pdf = buffer.getvalue()
    buffer.close()
    return pdf


# =========================================================
# STREAMLIT APP
# =========================================================
st.set_page_config(page_title="PDF Pre-Receipt Generator", layout="wide")
st.title("PDF Pre-Receipt Generator")

with st.sidebar:
    st.subheader("Defaults")
    processed_by = st.text_input("Processed by", DEFAULTS["processed_by"])
    sender = st.text_input("Sender", DEFAULTS["sender"])
    status = st.text_input("Status", DEFAULTS["status"])
    prefix = st.text_input("Reference ID prefix", DEFAULTS["prefix"])
    st.caption("Tip: add `DejaVuSans.ttf` in the app folder to avoid font squares in names/addresses.")

defaults = {
    "processed_by": processed_by,
    "sender": sender,
    "status": status,
    "prefix": prefix,
}

uploaded = st.file_uploader("Upload CSV or Excel", type=["csv", "xlsx"])

if uploaded:
    try:
        if uploaded.name.lower().endswith(".csv"):
            df = pd.read_csv(uploaded)
        else:
            df = pd.read_excel(uploaded)

        # Normalize columns (trim)
        df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]

        missing = validate_columns(df)
        if missing:
            st.error(f"Missing required columns: {missing}")
            st.stop()

        st.success(f"Loaded {len(df)} rows.")
        st.dataframe(df, use_container_width=True)

        col1, col2 = st.columns([1, 1])

        with col1:
            generate = st.button("Generate PDFs (ZIP)")

        with col2:
            preview_index = st.number_input(
                "Preview row index",
                min_value=0,
                max_value=max(0, len(df) - 1),
                value=0,
                step=1,
            )

        # Preview
        if len(df) > 0:
            row = df.iloc[int(preview_index)].to_dict()

            if not ensure_account_or_iban(row):
                st.warning("Preview row: missing Account/IBAN value. Fill at least one.")
            else:
                # inject generated ref id + customer reference
                row["_generated_reference_id"] = next_reference(prefix)
                row["_customer_reference"] = pick_reference_from_row(row)

                pdf_bytes = build_pdf_bytes(row, defaults)
                st.download_button(
                    label="Download preview PDF",
                    data=pdf_bytes,
                    file_name=f"pre_receipt_preview_{preview_index}.pdf",
                    mime="application/pdf",
                )

        # Batch ZIP
        if generate:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for i in range(len(df)):
                    row = df.iloc[i].to_dict()

                    if not ensure_account_or_iban(row):
                        # pula linha inválida
                        continue

                    row["_generated_reference_id"] = next_reference(prefix)
                    row["_customer_reference"] = pick_reference_from_row(row)

                    pdf_bytes = build_pdf_bytes(row, defaults)
                    filename = f"pre_receipt_{i+1}_{row['_generated_reference_id']}.pdf"
                    zf.writestr(filename, pdf_bytes)

            zip_buffer.seek(0)
            st.download_button(
                label="Download ZIP with PDFs",
                data=zip_buffer.getvalue(),
                file_name="pre_receipts.zip",
                mime="application/zip",
            )

    except Exception as e:
        st.error(f"Error processing file: {e}")

else:
    st.info("Upload a CSV or XLSX to start.")
