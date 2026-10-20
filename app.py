import streamlit as st

st.set_page_config(page_title="OSI Medical AI Shell", layout="wide")

st.sidebar.title("Control Panel")
st.sidebar.info("System Ready. Awaiting hackathon launch.")

st.title("Patient Intelligence Dashboard")

uploaded_files = st.file_uploader(
    "Upload Patient Data Files (JSON, PDF, DICOM)", 
    accept_multiple_files=True
)

tab1, tab2 = st.tabs(["Analysis Results", "Execution Logs"])

with tab1:
    if uploaded_files:
        st.success(f"{len(uploaded_files)} file(s) loaded successfully.")
    else:
        st.info("Upload sample patient records above or select pre-loaded files.")

with tab2:
    st.text("Agent logs will appear here during execution.")
