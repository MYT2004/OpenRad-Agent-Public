"""Read-only dose comparison runner: supplied NPY arrays, explicit aligned grids.

No model deserialization, inference, registration, DICOM mutation or silent repair.
"""
import hashlib
import io
import json
import uuid
from pathlib import Path
from importlib.metadata import version, PackageNotFoundError
from scipy.ndimage import distance_transform_edt
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from src.decision import EvaluationRequest, ModelEvaluationResult, Rule, decide, threshold_rule
from src.governance import canonical, digest, append_record
from src.storage import current_session
from openrad.tools.gamma_tool import evaluate_gamma_index


def file_hash(path):
    hasher = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def software_provenance():
    versions = {}
    for name in ('openrad', 'numpy', 'scipy', 'pydantic'):
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = 'source-tree'
    versions['engine_source_sha256'] = digest({name: file_hash(Path(__file__).parent / name)
        for name in ('evaluation.py', 'decision.py', 'governance.py')})
    return versions


def evaluate_model(request: EvaluationRequest):
    rules, metrics, hashes, arrays, violations, source_paths = [], {}, {}, {}, [], {}
    input_context = {'role': 'provenance'}
    def rule(name, passed, observed, criterion, hard=False, fail='REVIEW'):
        rules.append(Rule(name=name, outcome='PASS' if passed else fail,
                          observed=observed, criterion=criterion, hard=hard))
    def load(role, path, shape=None, mask=False):
        # Array bytes and hash come from the very same read (prevents hash/load races).
        input_context['role'] = role
        if Path(path).stat().st_size > request.policy.max_voxels * 8 + 65536:
            raise ValueError('Array exceeds the configured input budget')
        source_paths[role] = path
        raw = Path(path).read_bytes()
        hashes[role] = hashlib.sha256(raw).hexdigest()
        value = np.load(io.BytesIO(raw), allow_pickle=False)
        if not isinstance(value, np.ndarray) or value.dtype.kind not in 'bufi':
            raise ValueError('Requires a numeric NPY array, no pickled objects or archives')
        if not np.isfinite(value).all():
            rule(f'{role}_finite', False, {'nonfinite_count': int((~np.isfinite(value)).sum())}, 'All array values must be finite', True, 'REJECT')
            raise ValueError('Non-finite array')
        if shape is not None and value.shape != shape:
            rule(f'{role}_shape', False, {'actual': list(value.shape), 'expected': list(shape)}, 'Array shape must equal declared registered image grid', True, 'REJECT')
            raise ValueError('Shape mismatch')
        if mask and (not np.isin(value, [0, 1]).all() or not value.any()):
            raise ValueError('Masks must be binary and nonempty')
        arrays[role] = value.astype(bool if mask else float)
        return arrays[role]
    def evidence(role, path):
        if path:
            hashes[role] = file_hash(path)
            source_paths[role] = path
        rule(role, bool(path), bool(path), 'A hashed, externally reviewed calibration/qualification record is required')
    # Do not echo paths or file metadata into logs/errors.
    try:
        hashes['model_weights'] = file_hash(request.model_weights_path)
        for index, path in enumerate(request.input_paths):
            hashes[f'input_{index}'] = file_hash(path)
        rule('source_provenance', True, len(request.input_paths), 'SHA-256 of model weights and all supplied source files')
        if request.energy_mev is not None:
            rule('beam_energy', .01 <= request.energy_mev <= 250, request.energy_mev, '0.01 <= E <= 250 MeV (application range)', True, 'REJECT')
        elif request.model_kind == 'monte_carlo':
            rule('beam_energy', False, None, 'Monte Carlo evaluation requires beam energy')
        if request.fluence_per_mm2 is not None:
            rule('fluence_nonnegative', request.fluence_per_mm2 >= 0, request.fluence_per_mm2, 'Fluence >=0 particles/mm2', True, 'REJECT')
            limit = request.policy.max_fluence_per_mm2
            rule('fluence_limit', limit is not None and request.fluence_per_mm2 <= limit, request.fluence_per_mm2,
                 f'Operator must configure fluence limit: {limit}', limit is not None, 'REJECT' if limit is not None else 'REVIEW')
        for index, probability in enumerate(request.probabilities.values()):
            rule(f'radiobiology_probability_{index}', 0 <= probability <= 1, probability, '0 <= TCP/NTCP <=1', True, 'REJECT')
        if request.model_kind == 'monte_carlo':
            rule('monte_carlo_density', request.mass_density_path is not None, request.mass_density_path is not None, 'Explicit mass density assignments required for Monte Carlo evaluation')
        if request.depth_dose_path:
            profile = load('depth_dose', request.depth_dose_path)
            if profile.ndim != 2 or profile.shape[1] != 2 or len(profile) < 2 or not (np.diff(profile[:, 0]) > 0).all() or (profile[:, 1] < 0).any():
                raise ValueError('Invalid depth-dose array')
            applicable = request.homogeneous_photon_depth_dose and request.buildup_end_mm is not None
            rule('depth_dose_applicability', applicable, applicable, 'Monotonicity only applies to an explicitly selected homogeneous photon depth-dose test')
            if applicable:
                distal = profile[profile[:, 0] >= request.buildup_end_mm, 1]
                rule('depth_dose_monotonic', len(distal) >= 2 and bool((np.diff(distal) <= request.depth_dose_tolerance_gy).all()),
                     {'samples': len(distal), 'tolerance_gy': request.depth_dose_tolerance_gy}, 'No post-buildup increase above configured measurement/numerical tolerance', True, 'REJECT')
        grids = [request.image_grid, request.reference_grid, request.prediction_grid]
        valid_grids = True
        for grid in grids:
            direction = np.array(grid.direction)
            valid_grids &= (len(direction) == 9 and all(v > 0 for v in grid.shape) and all(v > 0 for v in grid.spacing_mm))
            if len(direction) == 9:
                valid_grids &= np.allclose(direction.reshape(3, 3).T @ direction.reshape(3, 3), np.eye(3), atol=1e-6, rtol=0)
        aligned = all(grid == grids[0] for grid in grids)
        rule('registered_grid_integrity', bool(valid_grids and aligned), {'valid': bool(valid_grids), 'aligned': aligned},
             'Identical declared shape, origin, positive spacing, orthonormal direction and frame; no implicit resampling', True, 'REJECT')
        rule('resource_limit', np.prod(request.image_grid.shape, dtype=object) <= request.policy.max_voxels,
             list(request.image_grid.shape), f'At most {request.policy.max_voxels} voxels for this discrete gamma implementation')
        if valid_grids and aligned and rules[-1].outcome == 'PASS':
            shape = request.image_grid.shape
            reference = load('reference', request.reference_path, shape)
            prediction = load('prediction', request.prediction_path, shape)
            rule('nonnegative_dose', bool((reference >= 0).all() and (prediction >= 0).all()),
                 {'reference_min_gy': float(reference.min()), 'prediction_min_gy': float(prediction.min())}, 'Every dose value >= 0 Gy', True, 'REJECT')
            rule('reference_normalization', bool(reference.max() > 0), float(reference.max()), 'Reference maximum > 0 Gy', True, 'REJECT')
            target = load('target_mask', request.target_mask_path, shape, True)
            if set(request.oar_mask_paths) != set(request.oar_limits_gy) or not all(
                    np.isfinite(v) and v > 0 for v in request.oar_limits_gy.values()):
                raise ValueError('Every OAR needs exactly one positive finite tolerance')
            oars = {}
            for index, name in enumerate(sorted(request.oar_mask_paths)):
                # Supplied ROI names are checked against TG-263 before entering reports.
                from openrad.validation.nomenclature import check_structure_name
                nomenclature = check_structure_name(name)
                if nomenclature.get('canonical_name') != name:
                    raise ValueError('OAR name requires a canonical TG-263 label')
                oars[name] = load(f'oar_mask_{index}', request.oar_mask_paths[name], shape, True)
            if request.mass_density_path:
                density = load('mass_density', request.mass_density_path, shape)
                rule('mass_density', bool((density > 0).all() and (density <= request.policy.mass_density_limit_g_cm3).all()),
                     [float(density.min()), float(density.max())], f'Mass density >0 and <= {request.policy.mass_density_limit_g_cm3} g/cm3; application bound, not electron density', True, 'REJECT')
            if all(r.outcome != 'REJECT' for r in rules):
                for label, percent, distance, pass_at, fail_at in (
                    ('custom_gamma_3pct_3mm', 3, 3, 95, 90),
                    ('strict_gamma_2pct_2mm', 2, 2, 90, 85),
                    ('tg218_reference_gamma_3pct_2mm', 3, 2, 95, 90)):
                    gamma = evaluate_gamma_index(reference, prediction, percent, distance, 10,
                                                 list(request.image_grid.spacing_mm), list(request.image_grid.spacing_mm))
                    metrics[label] = gamma
                    rules.append(threshold_rule(label, gamma['passing_rate'], pass_at, fail_at))
                metrics['prescription_gy'] = request.prescription_gy
                metrics['mae_gy'] = float(np.mean(np.abs(prediction - reference)))
                metrics['ptv_d95_gy'] = float(np.percentile(prediction[target], 5))
                metrics['mae_percent_rx'] = metrics['mae_gy'] / request.prescription_gy * 100
                metrics['ptv_d95_percent_rx'] = metrics['ptv_d95_gy'] / request.prescription_gy * 100
                rules.extend([threshold_rule('mae_percent_rx', metrics['mae_percent_rx'], 1.5, 3, False),
                              threshold_rule('ptv_d95_percent_rx', metrics['ptv_d95_percent_rx'], 95, 93)])
                metrics['oar_dmax_gy'] = {}
                for name, mask in oars.items():
                    dmax, limit = float(prediction[mask].max()), request.oar_limits_gy[name]
                    metrics['oar_dmax_gy'][name] = dmax
                    outcome = 'REJECT' if dmax > limit else 'REVIEW' if dmax >= .98 * limit else 'PASS'
                    if outcome == 'REJECT':
                        violations.append(name)
                    rules.append(Rule(name=f'oar_{name}', outcome=outcome, observed={'dmax_gy': dmax, 'limit_gy': limit},
                                      criterion='reject >100% limit; review 98–100% inclusive; pass <98%'))
                if request.uncertainty_std_path:
                    uncertainty = load('uncertainty_std', request.uncertainty_std_path, shape)
                    rule('uncertainty_nonnegative', bool((uncertainty >= 0).all()), float(uncertainty.min()), 'Standard deviation >=0 Gy', True, 'REJECT')
                    metrics['max_uncertainty_gy'] = float(uncertainty.max())
                    # Singleton axes have zero finite difference; no fabricated spacing.
                    gradient_sq = np.zeros(shape)
                    for axis, step in enumerate(request.image_grid.spacing_mm):
                        if shape[axis] > 1:
                            gradient_sq += np.gradient(prediction, step, axis=axis) ** 2
                    critical = np.logical_or.reduce(list(oars.values()))
                    if request.policy.critical_margin_mm > 0:
                        critical = distance_transform_edt(~critical, sampling=request.image_grid.spacing_mm) <= request.policy.critical_margin_mm
                    overlap = critical & (np.sqrt(gradient_sq) >= request.policy.gradient_gy_per_mm) & (uncertainty >= request.policy.max_uncertainty_gy)
                    rule('critical_uncertainty_overlap', not overlap.any(), int(overlap.sum()),
                         f'No voxel within {request.policy.critical_margin_mm} mm of OAR with gradient >= {request.policy.gradient_gy_per_mm} Gy/mm and SD >= {request.policy.max_uncertainty_gy} Gy')
                    rule('global_uncertainty', uncertainty.max() < request.policy.max_uncertainty_gy,
                         float(uncertainty.max()), f'Maximum SD < {request.policy.max_uncertainty_gy} Gy')
                else:
                    rule('uncertainty_map', False, None, 'Voxel-wise SD map in Gy required')
        rule('confidence', request.confidence is not None and request.confidence >= request.policy.min_confidence,
             request.confidence, f'Calibrated confidence >= {request.policy.min_confidence}', fail='REJECT' if request.confidence is not None else 'REVIEW')
        rule('ood', request.ood_score is not None and request.ood_score <= request.policy.max_ood_score and not request.ood_flags,
             {'score': request.ood_score, 'flags': request.ood_flags}, f'OOD score <= {request.policy.max_ood_score} and no anatomy/artifact flags')
        evidence('qualification', request.qualification_evidence_path)
        evidence('uncertainty_calibration', request.uncertainty_calibration_path)
        evidence('ood_calibration', request.ood_calibration_path)
        rule('inference_seed', request.inference_seed == request.policy.seed, request.inference_seed,
             f'Supplied inference provenance must declare seed {request.policy.seed}; runner performs no stochastic inference')
        rule('model_scope', request.model_kind != 'auto_segmentation', request.model_kind,
             'Dose comparison supports dose predictors and Monte Carlo outputs; segmentation needs independently validated Dice/surface-distance policy')
    except (ValueError, OSError, TypeError, EOFError) as exc:
        # File paths/external exception text are deliberately not included.
        rule('input_integrity', False, {'role': input_context['role'], 'error_type': type(exc).__name__}, 'All input files readable, finite numeric NPY arrays with explicit shapes and masks', True, 'REJECT')
    result = ModelEvaluationResult(model_name=request.model_name, dataset_id=request.dataset_id, status=decide(rules),
        hard_checks_passed=not any(r.hard and r.outcome == 'REJECT' for r in rules), rules=rules, metrics=metrics,
        policy=request.policy, provenance={'sha256': hashes, 'request_sha256': digest(request.model_dump(mode='json')),
        'gamma_method': 'discrete_global_gamma; 10% reference max cutoff; no interpolation',
        'evidence_trust': 'Caller-supplied evidence is hashed, not independently certified.',
        'software': software_provenance(),
        'grid': request.image_grid.model_dump(mode='json', exclude={'frame_id'}),
        'frame_sha256': digest(request.image_grid.frame_id),
        'oar_mask_roles': {f'oar_mask_{i}': name for i, name in enumerate(sorted(request.oar_mask_paths))}},
        gamma_pass_rate_3mm3pct=metrics.get('custom_gamma_3pct_3mm', {}).get('passing_rate'),
        max_uncertainty_gy=metrics.get('max_uncertainty_gy'), oar_tolerance_violations=violations,
        rejection_reasons=[r.name for r in rules if r.outcome == 'REJECT'])
    result.decision_hash = digest(result.model_dump(mode='json', exclude={'decision_hash', 'artifacts', 'session_id'}))
    manager, session_id = current_session()
    result.session_id = session_id
    artifact_dir = Path(manager.get_artifacts_dir(session_id))
    if result.hard_checks_passed and 'mae_percent_rx' in metrics:
        filename = f'decision_{uuid.uuid4().hex}.png'
        _plot_comparison(arrays, artifact_dir / filename, result.provenance['oar_mask_roles'], request.image_grid.spacing_mm)
        result.artifacts.append(f'/artifacts/{session_id}/artifacts/{filename}')
    # Recheck source content after computation, without modifying any source file.
    # Array hashes bind the actual bytes read; full inputs/weights are checked again.
    sources = [('model_weights', request.model_weights_path)] + [(f'input_{i}', p) for i, p in enumerate(request.input_paths)]
    for role, path in sources + list(source_paths.items()):
        if role in hashes and file_hash(path) != hashes[role]:
            raise ValueError('Source changed during evaluation; no decision committed')
    record = result.model_dump(mode='json')
    from src.reports import attach_report
    attach_report(record, 'evaluation')
    append_record(Path(manager.get_session_dir(session_id)) / 'decisions.jsonl', {'type': 'evaluation', **record})
    return record


def _plot_comparison(arrays, output, roi_labels, spacing_mm):
    reference, prediction = arrays['reference'], arrays['prediction']
    z = int(np.argmax(np.max(np.abs(prediction - reference), axis=(1, 2))))
    figure = Figure(figsize=(12, 4)); FigureCanvasAgg(figure)
    ax = figure.add_subplot(131)
    delta = prediction[z] - reference[z]
    limit = max(float(np.abs(delta).max()), .001)
    extent = (0, reference.shape[2]*spacing_mm[2], reference.shape[1]*spacing_mm[1], 0)
    im = ax.imshow(delta, cmap='RdBu_r', vmin=-limit, vmax=limit, extent=extent)
    ax.set(xlabel='Grid x (mm)', ylabel='Grid y (mm)', title=f'Model − reference (Gy), slice {z}'); figure.colorbar(im, ax=ax)
    for role in roi_labels:
        plane=arrays[role][z]
        if plane.any() and not plane.all():
            ax.contour((np.arange(plane.shape[1])+.5)*spacing_mm[2], (np.arange(plane.shape[0])+.5)*spacing_mm[1], plane, levels=[.5], linewidths=.8, colors='black')
    ax = figure.add_subplot(132)
    if 'uncertainty_std' in arrays:
        im = ax.imshow(arrays['uncertainty_std'][z], cmap='magma', vmin=0, vmax=max(float(arrays['uncertainty_std'].max()), .001), extent=extent)
        figure.colorbar(im, ax=ax); ax.set(xlabel='Grid x (mm)', ylabel='Grid y (mm)', title='Uncertainty SD (Gy)')
    else:
        ax.text(.1, .5, 'Uncertainty unavailable'); ax.axis('off')
    ax = figure.add_subplot(133)
    for name, mask in arrays.items():
        if name == 'target_mask' or name.startswith('oar_mask_'):
            for dose, style in ((reference, '-'), (prediction, '--')):
                values, counts = np.unique(dose[mask], return_counts=True)
                volume = (counts.sum() - np.r_[0, np.cumsum(counts)[:-1]]) / counts.sum() * 100
                x = np.r_[0., values, values[-1] + max(.001, values[-1] * 1e-6)]
                y = np.r_[100., volume, 0.]
                label = roi_labels.get(name, 'PTV')
                ax.step(x, y, style, where='pre', label=f'{label} {"ref" if style == "-" else "model"}')
    ax.set(xlabel='Dose (Gy)', ylabel='Volume (%)', title='DVH comparison'); ax.legend(fontsize=6)
    figure.tight_layout(); figure.savefig(output, dpi=120)
