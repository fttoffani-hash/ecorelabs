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

# -----------------------------
# Config (fixos)
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
# Helpers (corrigidos)
# -----------------------------
def safe_str(v) -> str:
    """Converte valores para string, tratando NaN/None e evitando 'nan'."""
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    s = str(v).strip()
    return "" if s.lower() == "nan" else s

def money_fmt(x) -> str:
    """Formata valor monetário. Se vazio/NaN/inválido -> vazio."""
    try:
        if x is None or pd.isna(x):
            return ""
        return f"{float(x):,.2f}"
    except Exception:
        return ""

def clean_account_text(s: str) -> str:
    """Remove prefixos tipo 'acc:', 'acct:', 'account:' etc."""
    s = safe_str(s)
    s = re.sub(r"^(acc|acct|account)\s*[:\-]?\s*", "", s, flags=re.IGNORECASE)
    return s.strip()

def pick_account(iban, acct) -> str:
    """Prefere IBAN se existir; senão Account. Limpa prefixos."""
    v = safe_str(iban) if safe_str(iban) else safe_str(acct)
    return clean_account_text(v)

def load_counter():
    """SEQ contínuo (global) salvo em counter.json."""
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
    cur = safe_str(currency).upper()
    return f"{prefix}{cur}{dt.strftime('%m%d%y')}{seq:06d}"

def append_country_once(address: str, country: str) -> str:
    """
    Evita duplicar país e evita quebra de linha (mais estável no PDF).
    Se 'country' já estiver no address, não adiciona.
    """
    addr = safe_str(address).strip()
    cty = safe_str(country).strip()
    if not cty:
        return addr
    if cty.lower() in addr.lower():
        return addr
    if not addr:
        return cty
    return f"{addr}, {cty}"

def wrap_text(text: str, max_len: int = 85):
    """Quebra texto em linhas por tamanho (simples e suficiente pro template)."""
    t = safe_str(text)
    if not t:
        return []
    return [t[i:i + max_len] for i in range(0, len(t), max_len)]

def gen_pdf(data: dict) -> bytes:
    """
    Gera PDF em memória e devolve bytes.
    - Não imprime linhas vazias (layout mais limpo)
    - Não imprime 'nan'
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    _, h = LETTER

    # Título
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, h - 60, "WIRE TRANSFER CONFIRMATION")

    y = h - 95

    def field(label, value):
        nonlocal y
        # NÃO imprime linhas vazias -> evita PDF “morto”
        if not safe_str(value):
            return

        c.setFont("Helvetica-Bold", 10)
        c.drawString(50, y, label)

        c.setFont("Helvetica", 10)
        lines = wrap_text(value, max_len=90)
        if not lines:
            return

        c.drawString(200, y, lines[0])
        y -= 16
        for extra in lines[1:]:
            c.drawString(200, y, extra)
            y -= 16

    # Campos
    field("Processed By:", data.get("processed_by"))
    field("Date:", data.get("date_str"))
    field("Status:", data.get("status"))
    field("Reference Number:", data.get("reference_number"))_
