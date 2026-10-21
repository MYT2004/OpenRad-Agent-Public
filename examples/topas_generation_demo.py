"""End-to-End Demo: TOPAS Monte Carlo Input Deck Generation & Physics Validation.

Generates production-grade TOPAS parameter decks for proton and electron radiotherapy,
and demonstrates the autonomous self-correction loop when unphysical parameters are requested.
"""

import os
from openrad.tools.topas_tool import generate_topas_deck
from openrad.validation.physics_rules import BeamEnergyBoundsError


def run_demo():
    print("=" * 70)
    print("OpenRad Agent: TOPAS Monte Carlo Deck Generator Demo")
    print("=" * 70)

    artifacts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "artifacts"))
    os.makedirs(artifacts_dir, exist_ok=True)

    # 1. Generate 150 MeV Proton Beam Deck
    print("\n1. Generating 150 MeV Proton Beam in Water Phantom...")
    proton_deck = generate_topas_deck(
        particle_type="proton",
        energy_MeV=150.0,
        geometry_type="water_phantom",
        phantom_dimensions_cm=[30.0, 30.0, 30.0],
        number_of_histories=200000,
    )
    p_path = os.path.join(artifacts_dir, "proton_150MeV_water.txt")
    with open(p_path, "w", encoding="utf-8") as f:
        f.write(proton_deck)
    print(f"  [+] Saved: {p_path} ({len(proton_deck.splitlines())} lines)")

    # 2. Generate 12 MeV Electron Beam Deck with Heterogeneous Slabs
    print("\n2. Generating 12 MeV Electron Beam in Heterogeneous Phantom...")
    electron_deck = generate_topas_deck(
        particle_type="e-",
        energy_MeV=12.0,
        geometry_type="slab_heterogeneity",
        phantom_dimensions_cm=[20.0, 20.0, 20.0],
        number_of_histories=100000,
    )
    e_path = os.path.join(artifacts_dir, "electron_12MeV_heterogeneity.txt")
    with open(e_path, "w", encoding="utf-8") as f:
        f.write(electron_deck)
    print(f"  [+] Saved: {e_path} ({len(electron_deck.splitlines())} lines)")

    # 3. Demonstration of Physics Validation Guardrail & Self-Correction
    print("\n3. Testing Physics Guardrail: Attempting unphysical energy (500 MeV)...")
    unphysical_energy = 500.0
    try:
        generate_topas_deck(
            particle_type="proton",
            energy_MeV=unphysical_energy,
            geometry_type="water_phantom",
        )
        print("  [-] Error: Physics engine failed to flag unphysical energy!")
    except BeamEnergyBoundsError as e:
        print(f"  [+] Guardrail Intercepted: {e}")
        print("  [+] Self-Correction Action: Clamping energy to clinical upper bound (250 MeV)...")
        corrected_deck = generate_topas_deck(
            particle_type="proton",
            energy_MeV=250.0,
            geometry_type="water_phantom",
        )
        c_path = os.path.join(artifacts_dir, "proton_250MeV_corrected.txt")
        with open(c_path, "w", encoding="utf-8") as f:
            f.write(corrected_deck)
        print(f"  [+] Self-Correction Succeeded: Generated {c_path}")

    print("\n" + "=" * 70)
    print("TOPAS Generation Demo Completed Successfully.")
    print("=" * 70)


if __name__ == "__main__":
    run_demo()
