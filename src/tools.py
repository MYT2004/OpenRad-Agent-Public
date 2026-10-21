"""Backward-compatible proxy to openrad.tools.multimodal_readers."""

from openrad.tools.multimodal_readers import (
    parse_patient_json,
    parse_patient_pdf,
    parse_dicom_metadata,
    parse_clinical_notes_text,
    parse_patient_csv,
)

__all__ = [
    "parse_patient_json",
    "parse_patient_pdf",
    "parse_dicom_metadata",
    "parse_clinical_notes_text",
    "parse_patient_csv",
]
