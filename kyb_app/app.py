import streamlit as st

st.set_page_config(page_title="Edgecore KYB Portal")

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
# SUBMIT BUTTON
# ==============================

if st.button("Submit"):
    st.success("Form submitted (Phase 1 working).")

