# Local dataset workflows

Install `pip install ".[app,api,test]"` and run `streamlit run frontend/app.py --server.address 127.0.0.1 --browser.gatherUsageStats false`.

Set `OPENRAD_DATA_ROOTS` to a JSON list of local folders in an ignored `.env`, or enter folders in the sidebar. Scan folders, select a linked pair and use the DVH workflow. Pairing follows SOP references from dose to plan to structure; directory names are not used as clinical identities. Source files are never modified. Documents and metadata never grant tool permissions or executable instructions.

Each requested ROI needs an unambiguous TG-263 identity; legacy aliases require human review. Physical frame, course linkage, contour shape and full dose coverage are checked separately. Unsupported geometry returns diagnostics instead of fabricated values. The axial sampler uses contour-plane slab thickness, union/XOR masks and linear dose interpolation in z. This is a research sampling method, not a commissioned clinical algorithm.

Gamma requires independent files. Non-DICOM dose arrays need explicit spacing per axis in mm and dose in Gy (zero origin assumed); DICOM inputs need matching patient/frame identities. Radiobiology requires explicit DVH semantics and model parameters. No patient results use synthetic defaults. The REPL is restricted to explicitly selected, trusted local code; it is not process isolation.

Local verification: `python -m scripts.verify_local_datasets folder1 folder2 --reference`. The optional `--reference` comparison uses dicompyler-core 0.5.6 (requires a compatible pydicom version, tested with 2.4.4). Reports include source hashes and are written under ignored `data/processed/`. Do not commit patient records or local verification outputs.

Run `python -m pytest tests -q` for reproducible synthetic, API and Streamlit workflow tests. Local patient datasets are not required in CI. CT headers are inventoried, but CT image quality/calibration, clinical uncertainties and TOPAS runtime execution remain outside the verified scope. Keyhole/self-intersecting contours and frame mismatches are quarantined for review. The optional frontend is local-only. The REST entry point binds all interfaces for Cloud Run; deploy with Cloud Run IAM and configured CORS origins.
