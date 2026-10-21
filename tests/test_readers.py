"""Test suite for multimodal clinical data readers."""

import os
import pytest
from openrad.tools.multimodal_readers import (
    parse_patient_json,
    parse_patient_pdf,
    parse_dicom_metadata,
    parse_clinical_notes_text,
    parse_patient_csv,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
RAW_DATA_DIR = os.path.join(PROJECT_ROOT, "data", "raw")


def test_dicom_metadata_reader():
    sample_dcm = os.path.join(
        RAW_DATA_DIR,
        "HNSCC-01-0199/10-26-2002-NA-RT SIMULATION-18560/3.000000-NA-58373/1-013.dcm",
    )
    if os.path.exists(sample_dcm):
        meta = parse_dicom_metadata(sample_dcm)
        assert "HNSCC-01-0199" in meta
        assert "Modality" in meta


def test_csv_reader():
    meta_csv = os.path.join(RAW_DATA_DIR, "metadata.csv")
    if os.path.exists(meta_csv):
        res = parse_patient_csv(meta_csv)
        assert "CSV Dimensions" in res
        assert "Subject ID" in res


def test_missing_files_error_handling():
    res = parse_patient_json("non_existent_file.json")
    assert "Error: File not found" in res

    res = parse_patient_pdf("non_existent_file.pdf")
    assert "Error: File not found" in res
