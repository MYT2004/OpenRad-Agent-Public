# Synthetic DICOM-RT showcase

Artificial teaching data only. Minimal objects for OpenRad's supported subset; not a real patient, complete clinical IOD, commissioned treatment plan or independent model validation. All objects carry explicit synthetic markers. No patient data was copied or repaired.

| Select this case folder | Intended demonstration | Expected intake |
|---|---|---|
| `01_clean_case` | Five matching CT slices, RTPLAN, RTSTRUCT and RTDOSE; Brainstem/PTV DVHs | READY_FOR_RESEARCH_ANALYSIS |
| `02_missing_image` | One deliberately omitted referenced CT slice | BLOCKED |
| `03_frame_mismatch` | Incompatible contour frame | BLOCKED |
| `04_invalid_scaling` | Invalid negative dose scaling | BLOCKED |
| `05_gamma_controls` | Two controlled dose variants; use with the clean case reference | Gamma workflow only |

Select **one case folder**, not `data/demo/` as a single patient. Examples deliberately share teaching identifiers while their content differs. Outputs must stay outside the input folders. `SHA256SUMS.json` records the distributed DICOM bytes.

## Start ready to demonstrate

From the repository root, after installing `.[app,api,test]`:

```bash
OPENRAD_DATA_ROOTS="[\"$PWD/data/demo/01_clean_case\"]" \
STORAGE_DIR="$PWD/storage/sessions" \
python -m streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8502
```

1. Open **Patient-file Verification**. The clean folder is prefilled by the environment setting. Keep pixel decoding enabled and click **Verify patient files**.
2. Expect READY_FOR_RESEARCH_ANALYSIS, explicit synthetic/research disclosures and an informational completeness limitation.
3. Click **Continue to DVH and structure review**, select **Brainstem** and **PTV**, then **Compute DVH**.
4. Return to verification and select the absolute path to `data/demo/02_missing_image`. Show the BLOCKED state and required follow-up action. The original clean case remains unchanged.
5. Optionally use **Gamma Index QA**: reference `data/demo/01_clean_case/synthetic_dose.dcm`, evaluation `data/demo/05_gamma_controls/small_controlled_difference.dcm` or `large_controlled_difference.dcm`. At 3%/2 mm and 10% cutoff the supplied controls yield 100% and 0% passing. They are constructed numerical demonstrations, not measured dose or model inference.

If port 8502 is occupied, choose another available local port. The app also offers **Create an explicitly synthetic demo case**, which regenerates a clean case in fresh runtime storage. No Gemini key is needed for intake, DVH or gamma.

[Verified outputs and previews](../../validation/evidence/showcase/README.md) · [Patient-file review policy](../../docs/PATIENT_DATA_QA.md)
