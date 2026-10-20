import glob
import os
from src.tools import parse_patient_json, parse_patient_pdf, parse_dicom_metadata, parse_clinical_notes_text

files = glob.glob("data/raw/*")
print(f"Found {len(files)} file(s) in data/raw/\n")

for filepath in files:
    ext = os.path.splitext(filepath)[1].lower()
    print(f"--- Testing {filepath} ---")
    if ext == ".json":
        print(parse_patient_json(filepath)[:300])
    elif ext == ".pdf":
        print(parse_patient_pdf(filepath)[:300])
    elif ext in [".dcm", ".dicom"]:
        print(parse_dicom_metadata(filepath)[:300])
    else:
        print(parse_clinical_notes_text(filepath)[:300])
    print("\n" + "="*40 + "\n")
