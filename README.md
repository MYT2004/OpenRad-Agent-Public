# OpenRad-Agent

> **Autonomous AI Agent for Radiation Oncology & Medical Imaging Intelligence**  
> Developed for the Open Scientific Intelligence (OSI) Hackathon 2026.

---

## Project Overview

**OpenRad-Agent** is an intelligent, agentic workflow system designed to assist medical physicists and radiation oncologists by automating the ingestion, parsing, and clinical reasoning across heterogeneous patient records. 

In modern radiation therapy, patient data spans complex DICOM imaging series (CT simulation scans, RT structure sets), clinical lab reports (PDF/JSON), and longitudinal metadata (CSV/FHIR). **OpenRad-Agent** unifies these data streams using custom LLM tool-calling architectures, allowing scientific researchers and clinicians to query patient histories, analyze DICOM headers, and extract diagnostic insights seamlessly.

---

## Key Features

* **Multi-Modal Clinical File Ingestion:** Custom parsing pipelines for DICOM (`.dcm`), PDF lab/discharge reports, JSON/FHIR health records, and CSV clinical metadata.
* **DICOM Metadata Extraction:** Lightweight header parsing without loading heavy pixel arrays into memory—extracting modality, study dates, body parts examined, and patient demographics.
* **Agentic Decision Pipeline:** Built with tool-calling capabilities to dynamically route clinical queries to specialized parser tools.
* **Interactive Dashboard:** Built-in Streamlit UI (`app.py`) for uploading patient files, inspecting parsed outputs, and tracking agent execution logs in real time.

---

## Repository Structure

```text
OpenRad-Agent/
├── .env.example             # Template for required environment API keys
├── .gitignore               # Configured to exclude heavy local datasets (>700MB) & secrets
├── LICENSE                  # Apache License 2.0 / MIT
├── README.md                # Project documentation & pitch
├── requirements.txt         # Python package dependencies
├── app.py                   # Streamlit interactive UI dashboard
├── test_readers.py          # Validation script for multi-format data parsers
│
├── data/
│   ├── raw/                 # Local raw datasets (DICOM series, CSV metadata, PDFs)
│   └── processed/           # Pipeline output cache and generated reports
│
└── src/                     # Core application package
    ├── __init__.py
    ├── tools.py             # Data parsing tools (DICOM, JSON, PDF, CSV)
    ├── agents.py            # Agent state machines & decision logic
    └── prompts.py           # System prompts & tool definitions
