"""End-to-End Demo: DICOM-RT & DVH Analysis with Radiobiological Modeling.

Uses real patient dataset (HNSCC-01-0199) from TCIA / local repository.
"""

import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from openrad.tools.dicom_tool import analyze_dvh
from openrad.tools.radiobio_tool import calculate_tcp_ntcp


def run_demo():
    print("=" * 70)
    print("OpenRad Agent: DVH Analysis & Radiobiology Demo")
    print("=" * 70)

    # Locate sample DICOM-RT files
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, ".."))

    rtstruct_path = os.path.join(
        project_root,
        "data/raw/HNSCC-01-0199/10-26-2002-NA-RT SIMULATION-18560/1.000000-NA-59395/1-1.dcm",
    )
    rtdose_path = os.path.join(
        project_root,
        "data/raw/HNSCC-01-0199/10-26-2002-NA-RT SIMULATION-18560/1.000000-NA-67954/1-1.dcm",
    )

    if not os.path.exists(rtstruct_path) or not os.path.exists(rtdose_path):
        print(f"Error: Sample DICOM files not found at {rtstruct_path}")
        return

    target_rois = ["PTV 69.96 Gy", "Cord", "Brainstem", "Rt Parotid"]
    print(f"\n1. Analyzing DVH for structures: {target_rois}...")
    dvh_results = analyze_dvh(rtstruct_path, rtdose_path, target_rois)

    print(f"Dose Grid Dimensions: {dvh_results['dose_grid_shape']}")
    print(f"Max Plan Dose: {dvh_results['max_dose_Gy']:.2f} Gy\n")

    plt.figure(figsize=(9, 6))

    for roi_name, s_data in dvh_results["structures"].items():
        if not s_data.get("found"):
            print(f"  [-] {roi_name}: Not found.")
            continue

        print(f"  [+] {s_data['structure_name']}:")
        print(f"      Volume: {s_data['volume_cc']:.2f} cc | Mean Dose: {s_data['mean_dose_Gy']:.2f} Gy")
        print(f"      D95%: {s_data['D95_Gy']:.2f} Gy | D50%: {s_data['D50_Gy']:.2f} Gy | D2%: {s_data['D2_Gy']:.2f} Gy")
        print(f"      V50 Gy: {s_data['V50_percent']:.1f}% ({s_data['V50_cc']:.2f} cc)")

        # Plot DVH curve
        curve = s_data.get("dvh_curve")
        if curve:
            plt.plot(curve["dose_bins_Gy"], curve["volume_percent"], label=s_data["structure_name"], lw=2.2)

    plt.title("Dose Volume Histogram (DVH) - Patient HNSCC-01-0199", fontsize=13, fontweight="bold")
    plt.xlabel("Dose (Gy)", fontsize=11)
    plt.ylabel("Volume (%)", fontsize=11)
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.legend(fontsize=10)
    plt.xlim(0, max(dvh_results["max_dose_Gy"] * 1.05, 75.0))
    plt.ylim(0, 105)

    os.makedirs(os.path.join(project_root, "artifacts"), exist_ok=True)
    out_plot = os.path.join(project_root, "artifacts/dvh_analysis_demo.png")
    plt.savefig(out_plot, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nSaved DVH plot artifact: {out_plot}")

    # Radiobiological Evaluation
    print("\n2. Evaluating Radiobiology (TCP / NTCP)...")
    if "Cord" in dvh_results["structures"] and dvh_results["structures"]["Cord"].get("found"):
        cord_dvh = dvh_results["structures"]["Cord"]["dvh_curve"]
        # QUANTEC myelopathy parameters: TD50 = 65 Gy, m = 0.175, n = 0.05
        cord_ntcp = calculate_tcp_ntcp(cord_dvh, "LKB", {"TD50": 65.0, "m": 0.175, "n": 0.05})
        print(f"  - Spinal Cord Myelopathy NTCP: {cord_ntcp['NTCP'] * 100:.3f}% (EUD: {cord_ntcp['EUD_Gy']} Gy)")

    if "PTV 69.96 Gy" in dvh_results["structures"] and dvh_results["structures"]["PTV 69.96 Gy"].get("found"):
        ptv_dvh = dvh_results["structures"]["PTV 69.96 Gy"]["dvh_curve"]
        ptv_tcp = calculate_tcp_ntcp(ptv_dvh, "Poisson_LQ", {"TCD50": 65.0, "gamma_50": 2.5})
        print(f"  - PTV Tumor Control Probability (TCP): {ptv_tcp['TCP'] * 100:.1f}% (EUD: {ptv_tcp['EUD_Gy']} Gy)")

    print("\n" + "=" * 70)
    print("DVH Demo Completed Successfully.")
    print("=" * 70)


if __name__ == "__main__":
    run_demo()
