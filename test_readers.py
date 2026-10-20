import os
from src.tools import (
    parse_patient_json,
    parse_patient_pdf,
    parse_dicom_metadata,
    parse_clinical_notes_text,
    parse_patient_csv
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DATA_DIR = os.path.join(SCRIPT_DIR, "data", "raw")

def test_all_files(root_dir: str):
    print(f"Target directory: {root_dir}")
    if not os.path.exists(root_dir):
        print(f"Directory '{root_dir}' does not exist.")
        return

    found_files = []
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            # Skip hidden files, license files, and gitkeep
            if filename.startswith(".") or filename in [".gitkeep", "LICENSE"]:
                continue
            full_path = os.path.join(dirpath, filename)
            found_files.append(full_path)

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
                result = f"Unsupported file extension '{ext}'. File path: {filepath}"
            
            print(result[:400])
        except Exception as e:
            print(f"FAILED to parse {filepath}: {str(e)}")
            
        print("\n" + "=" * 50 + "\n")

if __name__ == "__main__":
    test_all_files(RAW_DATA_DIR)
