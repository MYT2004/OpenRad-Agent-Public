# README.md
# OpenRad Agent ⚛️🤖

> **Autonomous AI Research Assistant for Computational Radiation Physics & Dosimetry**  
> *Built for the Open Scientific Intelligence (OSI) Hackathon using the Google Antigravity SDK & Gemini.*

---

## 📌 Executive Summary

**OpenRad Agent** bridges the gap between frontier Large Language Models and rigorous physical science workflows in radiation therapy and medical physics. Current clinical and research workflows require manual script writing across fragmented libraries (`pydicom`, `PyMedPhys`, Monte Carlo codes) to extract dose metrics or configure beam transport models.

Powered by **Google Antigravity**, **Gemini 3.5 Pro**, and a closed-loop **Physics Validation Engine**, OpenRad Agent autonomously parses DICOM-RT matrices, computes Dose-Volume Histograms (DVH), performs Gamma Index agreement evaluations, and writes verified TOPAS/Geant4 simulation decks.

---

## 📐 System Architecture

  +-----------------------+
  |   User Prompt / API   |
  +-----------+-----------+
                          |
                          v
                      +---------------+---------------+
                      |    Google Antigravity Runtime |
                      |   (Gemini 3.5 Pro Core Engine)|
                      +---------------+---------------+
                                               |
                      +------------------------+------------------------+
                      |                                                 |
                      v                                                 v
        +-------------+-------------+                     +-------------+-------------+
        |   Deterministic Tools     |                     |    Stateful REPL / Shell   |
        |  (pydicom / PyMedPhys)    |                     | (Code Exec & Visualization)|
        +-------------+-------------+                     +-------------+-------------+
                  |                                                 |
                  +------------------------+------------------------+
                                |
                                v
                +---------------+---------------+
                |   Physics Validation Engine   |
                |  (Bounds & Unit Checks)       |
                +---------------+---------------+
                                |
                    [Pass / Fail Guardrail]
                          /         
              (Pass)     /           \     (Fail: Auto-Correction)
                        v             v
              +-----------+---+   +-----+-------------------+
              | JSON / Plots  |   | Re-prompt Agent with    |
              | Artifacts     |   | Trajectory Feedback     |
              +---------------+   +-------------------------+

---

## 🗂️ Repository Directory Structure

```text
openrad-agent/
├── SKILL.md                   # Top-level Antigravity Skill specification
├── server.py                  # FastAPI server wrapper for Cloud Run deployment
├── agent_main.py              # CLI & local execution agent driver
├── Dockerfile                 # Container setup for GCP Cloud Run
├── requirements.txt           # Dependency management
├── skills/
│   └── radiation_physics/
│       └── SKILL.md           # Domain physics parameters & instructions
├── storage/
│   ├── manager.py             # Session persistence & artifact tracking
│   └── sessions/              # Generated logs, plots, and script decks
└── data/                      # Sample DICOM-RT files for testing
