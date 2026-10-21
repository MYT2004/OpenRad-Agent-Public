"""Canonical, deterministic OSI tools with scrubbed inputs and physics hooks."""
from __future__ import annotations
from pathlib import Path
from uuid import uuid4
import numpy as np
import pydicom
import pymedphys
from src.hooks import post_tool_call, validate_tool_output
from src.privacy import scrub_analysis_copies
from src.storage import current_session
from src.demo import has_synthetic_teaching_marker
from openrad.tools.dicom_tool import analyze_dvh_datasets
from openrad.tools.dose_geometry import validate_axial_dose
from openrad.tools.topas_tool import generate_topas_deck
from openrad.validation.nomenclature import check_structure_name
from openrad.validation.physics_rules import PhysicsValidationEngine, PhysicsValidationError, DoseIntegrityError
# Legacy reader imports remain available for existing callers.
from openrad.tools.multimodal_readers import (
    parse_patient_json, parse_patient_pdf, parse_dicom_metadata,
    parse_clinical_notes_text, parse_patient_csv,
)

# Built-in aliases for common non-standard ROI names to minimize manual JSON mapping
BUILTIN_ROI_ALIASES: dict[str, str] = {
    'cord': 'SpinalCord',
    'spinal cord': 'SpinalCord',
    'spinal_cord': 'SpinalCord',
    'rt parotid': 'Parotid_R',
    'parotid rt': 'Parotid_R',
    'right parotid': 'Parotid_R',
    'parotid_r': 'Parotid_R',
    'r parotid': 'Parotid_R',
    'lt parotid': 'Parotid_L',
    'parotid lt': 'Parotid_L',
    'left parotid': 'Parotid_L',
    'parotid_l': 'Parotid_L',
    'l parotid': 'Parotid_L',
    'brain stem': 'Brainstem',
    'brain_stem': 'Brainstem',
    'stem': 'Brainstem',
    'chiasm': 'OpticChiasm',
    'optic chiasm': 'OpticChiasm',
    'opt chiasm': 'OpticChiasm',
    'l optic nerve': 'OpticNrv_L',
    'lt optic nerve': 'OpticNrv_L',
    'optic nerve l': 'OpticNrv_L',
    'r optic nerve': 'OpticNrv_R',
    'rt optic nerve': 'OpticNrv_R',
    'optic nerve r': 'OpticNrv_R',
    'l lens': 'Lens_L',
    'lt lens': 'Lens_L',
    'lens l': 'Lens_L',
    'r lens': 'Lens_R',
    'rt lens': 'Lens_R',
    'lens r': 'Lens_R',
    'l eye': 'Eye_L',
    'lt eye': 'Eye_L',
    'eye l': 'Eye_L',
    'r eye': 'Eye_R',
    'rt eye': 'Eye_R',
    'eye r': 'Eye_R',
    'l cochlea': 'Cochlea_L',
    'lt cochlea': 'Cochlea_L',
    'cochlea l': 'Cochlea_L',
    'r cochlea': 'Cochlea_R',
    'rt cochlea': 'Cochlea_R',
    'cochlea r': 'Cochlea_R',
    'l submandibular': 'Glnd_Submand_L',
    'lt submandibular': 'Glnd_Submand_L',
    'submandibular l': 'Glnd_Submand_L',
    'r submandibular': 'Glnd_Submand_R',
    'rt submandibular': 'Glnd_Submand_R',
    'submandibular r': 'Glnd_Submand_R',
    'l brachial plexus': 'BrachialPlex_L',
    'lt brachial plexus': 'BrachialPlex_L',
    'r brachial plexus': 'BrachialPlex_R',
    'rt brachial plexus': 'BrachialPlex_R',
    'rectum': 'Rectum',
    'bladder': 'Bladder',
}


def resolve_save_path(target: str | Path, patient_id: str | None = None) -> Path:
    """Strict path resolver enforcing raw data immutability.

    Raises a hard PermissionError if any save or export operation attempts to write
    into 'data/raw/'. Directs all processed files, modified DICOMs, and cached DVH
    outputs to 'data/processed/{patient_id}/'.
    """
    if not target:
        raise ValueError("Target path must be a non-empty string or Path.")

    target_str = str(target).strip()
    norm_str = target_str.replace('\\', '/')

    # Check normalized string representation for any data/raw patterns
    raw_patterns = ['data/raw', '/raw/', 'data/raw/', './data/raw']
    if any(pat in norm_str for pat in raw_patterns) or norm_str.startswith('data/raw') or norm_str.startswith('raw/'):
        raise PermissionError(f"Write operations into 'data/raw/' are strictly prohibited for data safety and immutability: {target_str}")

    target_path = Path(target_str)

    pid = str(patient_id).strip() if patient_id else 'default'
    pid = Path(pid).name or 'default'
    processed_base = (Path.cwd() / 'data' / 'processed' / pid).resolve()

    # Route processed files
    if target_path.is_absolute():
        out_path = target_path
    elif 'data/processed' in norm_str:
        out_path = (Path.cwd() / target_path).resolve()
    else:
        out_path = processed_base / target_path.name

    from src.readonly import assert_output_path
    try:
        out_path = assert_output_path(out_path)
    except ValueError as exc:
        raise PermissionError('Raw data is read-only; choose a separate output directory') from exc
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return out_path


@post_tool_call
def parse_and_evaluate_dvh(rtdose_path: str, rtstruct_path: str, rois: list[str], *,
                           rtplan_path=None, reviewed_name_map=None) -> dict:
    """Compute scoped axial DVHs and save a PHI-scrubbed session plot.

    V50 means V50Gy[%] and V50Gy[cc]. An optional RTPLAN verifies course
    linkage; without it the result explicitly records unverified linkage.
    Source DICOMs are never modified or exported. This analysis projection
    is not a general DICOM de-identification service or clinical certification.
    """
    if not rois or any(not isinstance(name, str) or not name for name in rois):
        raise ValueError('At least one nonempty ROI name is required.')
    try:
        dose = pydicom.dcmread(rtdose_path)
        struct = pydicom.dcmread(rtstruct_path)
        plan = pydicom.dcmread(rtplan_path, stop_before_pixels=True) if rtplan_path else None
        teaching_markers = [has_synthetic_teaching_marker(ds) for ds in [dose,struct] + ([plan] if plan is not None else [])]
        if any(teaching_markers) and not all(teaching_markers):
            raise ValueError('Synthetic teaching and unmarked sources must not be mixed')
        synthetic = all(teaching_markers)
        dose, struct, plan, name_map = scrub_analysis_copies(dose, struct, plan, reviewed_name_map)
        validate_axial_dose(dose)
        # PyMedPhys supplies physical axes in mm and absorbed dose in Gy;
        # pydicom supplies the contour sequences. No private PyMedPhys API used.
        # Decode independently first: older PyMedPhys releases may adjust the
        # transfer-syntax metadata on their input dataset. Compare values so a
        # codec/endianness discrepancy cannot silently alter absorbed dose.
        source_grid = np.asarray(dose.pixel_array, dtype=float) * float(dose.DoseGridScaling)
        PhysicsValidationEngine.validate_dose_grid(source_grid, raise_on_fail=True)
        axes, grid = pymedphys.dicom.zyx_and_dose_from_dataset(dose)
        grid = np.asarray(grid, dtype=float)
        expected = (int(dose.NumberOfFrames), int(dose.Rows), int(dose.Columns))
        if grid.ndim != 3 or grid.shape != expected:
            raise DoseIntegrityError('Decoded dose grid shape does not match DICOM dimensions.')
        if grid.shape != source_grid.shape or not np.allclose(grid, source_grid, rtol=0, atol=1e-10):
            raise DoseIntegrityError('pydicom and PyMedPhys disagree on decoded dose values.')
        ipp = np.asarray(dose.ImagePositionPatient, dtype=float)
        expected_axes = (ipp[2] + np.asarray(dose.GridFrameOffsetVector, dtype=float),
                         ipp[1] + np.arange(expected[1])*float(dose.PixelSpacing[0]),
                         ipp[0] + np.arange(expected[2])*float(dose.PixelSpacing[1]))
        if len(axes) != 3 or any(np.asarray(axis).shape != wanted.shape or not np.allclose(axis, wanted, rtol=0, atol=1e-6) for axis, wanted in zip(axes, expected_axes)):
            raise DoseIntegrityError('PyMedPhys coordinates disagree with DICOM physical axes.')
        PhysicsValidationEngine.validate_dose_grid(grid, raise_on_fail=True)
        validate_tool_output({'_physics':{'dose_grid':grid,'expected_shape':expected,'axes_mm':axes}})
        labels = []
        for index, name in enumerate(rois):
            canonical = (name_map.get(name.casefold())
                         or check_structure_name(name)['canonical_name'])
            labels.append(canonical or f'RequestedROI{index+1}')
        if len(set(n.casefold() for n in labels)) != len(labels):
            raise ValueError('Requested ROI names resolve to duplicates.')
        result = analyze_dvh_datasets(struct, dose, labels, ds_plan=plan,
                                      require_plan_linkage=False, parsed_dose=grid)
    except PhysicsValidationError:
        raise
    except (ValueError, OSError, AttributeError, KeyError, TypeError) as exc:
        raise ValueError('DICOM input could not be read or validated; inspect locally without logging patient metadata.') from None
    if not result['course_linkage_verified']:
        result['limitations'].append('RTPLAN not supplied; dose/structure course linkage is unverified.')
    manager, session_id = current_session()
    result.update(session_id=session_id, artifacts=[], synthetic=synthetic, privacy={'profile':'minimal_in_memory_analysis_projection',
        'source_files_modified':False,'original_identifiers_exported':False})
    curves = [(name, values['dvh_curve']) for name, values in result['structures'].items() if values.get('found')]
    if curves:
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        figure = Figure(figsize=(8, 5)); FigureCanvasAgg(figure)
        ax = figure.subplots()
        for name, curve in curves:
            ax.plot(curve['dose_bins_Gy'], curve['volume_percent'], label=name)
        ax.set(xlabel='Dose (Gy)', ylabel='Volume (%)', title='Synthetic teaching DVH — research only' if synthetic else 'Cumulative DVH — research analysis', ylim=(0, 105))
        ax.legend(); ax.grid(alpha=.2)
        filename = 'dvh_' + uuid4().hex + '.png'
        output = Path(manager.get_artifacts_dir(session_id)) / filename
        figure.savefig(output, dpi=150, bbox_inches='tight')
        result['artifacts'] = [f'/artifacts/{session_id}/artifacts/{filename}']
    from src.reports import attach_report
    attach_report(result, 'dvh')
    result['_physics'] = {'dose_grid':grid,'expected_shape':expected,'axes_mm':axes}
    return result


@post_tool_call
def generate_topas_file(particle: str, energy_mev: float, histories: int, output_path: str) -> dict:
    """Write a validated water-phantom TOPAS template without overwriting files."""
    PhysicsValidationEngine.validate_beam_energy(energy_mev, particle, raise_on_fail=True)
    deck = generate_topas_deck(particle, energy_mev, number_of_histories=histories)
    from src.readonly import assert_output_path
    target = resolve_save_path(output_path)
    assert_output_path(target)
    if target.suffix.lower() != '.txt':
        raise ValueError('TOPAS output must use a .txt extension.')
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as stream:
        stream.write(deck)
    result = {'status':'generated','output_path':str(target),'particle':particle,
            'energy_mev':float(energy_mev),'histories':histories,'clinical_release':False,
            'limitations':['TOPAS execution and commissioned beam validation remain required.']}
    from src.reports import attach_report
    return attach_report(result, 'topas')


def evaluate_dvh_tool(dicom_rtdose_path, dicom_rtstruct_path, roi_names,
                      reviewed_name_map=None, dicom_rtplan_path=None):
    """Adapter for the agent's existing typed tool schema."""
    return parse_and_evaluate_dvh(dicom_rtdose_path, dicom_rtstruct_path, roi_names,
        reviewed_name_map=reviewed_name_map, rtplan_path=dicom_rtplan_path)
