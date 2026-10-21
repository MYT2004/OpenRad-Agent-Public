"""Multimodal Patient Data Readers for OpenRad Agent.

Supports parsing of patient JSON/FHIR records, PDF clinical reports,
DICOM metadata, raw clinical notes, and tabular CSV records.
"""

import json
import os
from typing import Any, Dict


def parse_patient_json(file_path: str) -> str:
    """Parses patient JSON or FHIR records."""
    if not os.path.exists(file_path):
        return f"Error: File not found at {file_path}"
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return json.dumps(data, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Error parsing JSON file: {str(e)}"


def parse_patient_pdf(file_path: str, max_pages: int = 10) -> str:
    """Extracts clinical text from patient PDF reports."""
    if not os.path.exists(file_path):
        return f"Error: File not found at {file_path}"
    try:
        import pypdf
        reader = pypdf.PdfReader(file_path)
        extracted_text = []
        num_pages = min(len(reader.pages), max_pages)
        for idx in range(num_pages):
            page_text = reader.pages[idx].extract_text() or ""
            extracted_text.append(f"--- PAGE {idx + 1} ---\n{page_text.strip()}")
        return "\n\n".join(extracted_text) if extracted_text else "Warning: No text found in PDF."
    except Exception as e:
        return f"Error reading PDF file: {str(e)}"


def parse_dicom_metadata(file_path: str) -> str:
    """Extracts metadata from DICOM (.dcm) files without reading heavy pixel arrays."""
    if not os.path.exists(file_path):
        return f"Error: File not found at {file_path}"
    try:
        import pydicom
        ds = pydicom.dcmread(file_path, stop_before_pixels=True)
        metadata = {
            "PatientID": getattr(ds, "PatientID", "N/A"),
            "PatientSex": getattr(ds, "PatientSex", "N/A"),
            "PatientAge": getattr(ds, "PatientAge", "N/A"),
            "Modality": getattr(ds, "Modality", "N/A"),
            "StudyDescription": getattr(ds, "StudyDescription", "N/A"),
            "SeriesDescription": getattr(ds, "SeriesDescription", "N/A"),
            "BodyPartExamined": getattr(ds, "BodyPartExamined", "N/A"),
            "StudyDate": getattr(ds, "StudyDate", "N/A"),
        }
        return json.dumps(metadata, indent=2)
    except Exception as e:
        return f"Error parsing DICOM file: {str(e)}"


def parse_clinical_notes_text(file_path: str) -> str:
    """Reads raw text or markdown patient notes."""
    if not os.path.exists(file_path):
        return f"Error: File not found at {file_path}"
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        return f"Error reading text file: {str(e)}"


def parse_patient_csv(file_path: str, max_rows: int = 5) -> str:
    """Reads tabular patient clinical data or metadata from CSV files."""
    if not os.path.exists(file_path):
        return f"Error: File not found at {file_path}"
    try:
        import pandas as pd
        df = pd.read_csv(file_path)
        summary = f"CSV Dimensions: {df.shape[0]} rows x {df.shape[1]} columns\n"
        summary += f"Columns: {list(df.columns)}\n\n"

        key_cols = [
            c for c in ["Subject ID", "Modality", "Series Description", "Number of Images", "File Size"]
            if c in df.columns
        ]
        display_df = df[key_cols] if key_cols else df

        summary += "Sample Data:\n" + display_df.head(max_rows).to_string(index=False)
        return summary
    except Exception as e:
        return f"Error reading CSV file: {str(e)}"
