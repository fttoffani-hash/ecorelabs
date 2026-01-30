import streamlit as st
import smtplib
from email.message import EmailMessage
from datetime import datetime

st.set_page_config(page_title="Edgecore KYB Portal")

EMAIL_USER = st.secrets["EMAIL_USER"]
EMAIL_PASSWORD = st.secrets["EMAIL_PASSWORD"]
COMPLIANCE_EMAIL = st.secrets["COMPLIANCE_EMAIL"]

st.title("Edgecore Labs – KYB Onboarding")

# ==============================
# AUTHORIZED REPRESENTATIVE
# ==============================

st.header("1. Authorized Representative")

first_name = st.text_input("First Name *")
last_name = st.text_input("Last Name *")
email = st.text_input("Email Address *")

# ==============================
# COMPANY INFO
# ==============================

st.header("2. Company Information")

company_name = st.text_input("Company Name *")
country = st.text_input("Country of Incorporation *")
registration_number = st.text_input("Registration Number *")
industry = st.text_input("Industry *")
expected_volume = st.text_input("Expected Monthly Volume (USD)")

# ==============================
# DOCUMENT UPLOAD (OBRIGATÓRIO)
# ==============================

st.header("3. Required Documents")

certificate = st.file_uploader(
    "Certificate of Incorporation * (PDF/JPG/PNG)",
    type=["pdf", "jpg", "jpeg", "png"]
)

bank_statement = st.file_uploader(
    "Recent Bank Statement (last 3 months) * (PDF/JPG/PNG)",
    type=["pdf", "jpg", "jpeg", "png"]
)

invoices = st.file_uploader(
    "2 Sample Invoices * (PDF/JPG/PNG)",
    type=["pdf", "jpg", "jpeg", "png"],
    accept_multiple_files=True
)

# ==============================
# SUBMIT
# ==============================

if st.button("Submit KYB"):

    # --------------------------
    # VALIDATION
    # --------------------------

    if not all([first_name, last_name, email, company_name, country, registration_number, industry]):
        st.error("Please complete all required fields.")
        st.stop()

    if not certificate:
        st.error("Certificate of Incorporation is required.")
        st.stop()

    if not bank_statement:
        st.error("Bank Statement is required.")
        st.stop()

    if not invoices or len(invoices) < 1:
        st.error("At least one sample invoice is required.")
        st.stop()

    # --------------------------
    # CREATE EMAIL
    # --------------------------

    msg = EmailMessage()
    msg["Subject"] = f"[KYB SUBMISSION] {company_name}"
    msg["From"] = EMAIL_USER
    msg["To"] = COMPLIANCE_EMAIL

    submission_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    msg.set_content(f"""
NEW KYB SUBMISSION
====================

Submission Time: {submission_time}

AUTHORIZED REPRESENTATIVE
--------------------------
Name: {first_name} {last_name}
Email: {email}

COMPANY INFORMATION
--------------------------
Company Name: {company_name}
Country: {country}
Registration Number: {registration_number}
Industry: {industry}
Expected Monthly Volume: {expected_volume}

Documents attached in this email.
""")

    # --------------------------
    # ATTACH FILES
    # --------------------------

    def attach_file(uploaded_file):
        file_data = uploaded_file.read()
        msg.add_attachment(
            file_data,
            maintype="application",
            subtype="octet-stream",
            filename=uploaded_file.name
        )

    attach_file(certificate)
    attach_file(bank_statement)

    for inv in invoices:
        attach_file(inv)

    # --------------------------
    # SEND EMAIL
    # --------------------------

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_USER, EMAIL_PASSWORD)
        smtp.send_message(msg)

    st.success("KYB submitted successfully. Compliance team has been notified.")
