"""Script runner for multimodal patient reader verification."""

import os
from openrad.tools.multimodal_readers import (
    parse_patient_json,
    parse_patient_pdf,
    parse_dicom_metadata,
    parse_clinical_notes_text,
    parse_patient_csv,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DATA_DIR = os.path.join(SCRIPT_DIR, "..", "..", "data", "raw")


def run_reader_smoke(root_dir: str):
    print(f"Target directory: {root_dir}")
    if not os.path.exists(root_dir):
        print(f"Directory '{root_dir}' does not exist.")
        return

    found_files = []
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.startswith(".") or filename in [".gitkeep", "LICENSE"]:
                continue
            found_files.append(os.path.join(dirpath, filename))

    print(f"Found {len(found_files)} printable file(s) inside '{root_dir}'\n")

    for filepath in found_files[:10]:
        ext = os.path.splitext(filepath)[1].lower()
        print(f"--- Testing File: {filepath} ---")
        try:
            if ext == ".json":
                result = parse_patient_json(filepath)
            elif ext == ".pdf":
                result = parse_patient_pdf(filepath)
            elif ext in [".dcm", ".dicom"]:
                result = parse_dicom_metadata(filepath)
            elif ext == ".csv":
                result = parse_patient_csv(filepath)
            elif ext in [".txt", ".md"]:
                result = parse_clinical_notes_text(filepath)
            else:
                result = f"Unsupported file extension '{ext}'."
            print(result[:400])
        except Exception as e:
            print(f"FAILED to parse {filepath}: {str(e)}")
        print("\n" + "=" * 50 + "\n")


if __name__ == "__main__":
    run_reader_smoke(RAW_DATA_DIR)
