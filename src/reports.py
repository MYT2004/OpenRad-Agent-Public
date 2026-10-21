"""Physicist-facing summaries alongside unchanged machine-readable measurements."""
import csv
import io
from pathlib import Path
from uuid import uuid4


RESEARCH_SCOPE = 'Research assessment only. This output does not authorize treatment or establish clinical commissioning.'


def number(value, unit='', digits=3):
    if value is None:
        return 'Not evaluated'
    return f'{value:.{digits}f}{(" " + unit) if unit else ""}'


def build_report(result, kind):
    rows, actions, limitations = [], [], list(result.get('limitations', []))
    def row(measure, value, interpretation=''):
        rows.append({'Measure': measure, 'Result': str(value), 'Interpretation': interpretation})
    if kind == 'dvh':
        title = 'Dose-volume assessment'
        found = sum(bool(v.get('found')) for v in result['structures'].values())
        total = len(result['structures'])
        summary = f'{found} of {total} requested structures evaluated. ' + ('All requested curves are available.' if found == total else 'Assessment is incomplete; review blocked structures before interpreting the plan.')
        row('Dose–plan–structure linkage', 'Verified' if result.get('course_linkage_verified') else 'Unverified', 'UID association is not independent anatomical verification.')
        row('Maximum grid dose', number(result.get('max_dose_Gy'), 'Gy'), 'Maximum sampled grid value; no prescription or OAR limit inferred.')
        for name, item in result['structures'].items():
            if not item.get('found'):
                row(name, 'Not evaluated', item.get('error', 'Review ROI mapping and contours.'))
                continue
            for key, label, unit in [('volume_cc','Volume','cc'), ('mean_dose_Gy','Mean dose','Gy'),
                                    ('max_dose_Gy','Voxel Dmax','Gy'), ('D95_Gy','D95%','Gy'),
                                    ('D50_Gy','D50%','Gy'), ('D2_Gy','D2%','Gy'), ('V50_percent','V50Gy','%'), ('V50_cc','V50Gy','cc')]:
                row(f'{name}: {label}', number(item.get(key), unit), 'Descriptive sampled metric; compare with the approved protocol.')
        actions = ['Confirm structure anatomy, laterality and any manually reviewed aliases.',
                   'Compare target coverage and OAR metrics with the actual prescription, fractionation and approved endpoint-specific constraints.',
                   'Review dose coverage, contour topology, resolution and comparison with an independently validated TPS DVH.']
        limitations.append('No treatment-plan acceptability verdict is inferred without prescription and protocol-specific constraints.')
    elif kind == 'gamma':
        title = 'Independent dose comparison'
        criteria = result['criteria']; rate = result['passing_rate']
        policy = (criteria['dose_percent'], criteria['distance_mm'], criteria['cutoff_percent'])
        thresholds = {(3,2,10):(95,90,'TG-218 reference limits'), (3,3,10):(95,90,'Custom 3%/3 mm policy'), (2,2,10):(90,85,'Custom 2%/2 mm policy')}
        if policy in thresholds:
            passed, failed, label = thresholds[policy]
            verdict = 'Candidate threshold met' if rate >= passed else 'Review band' if rate >= failed else 'Below action threshold'
            summary = f'{verdict}: {number(rate, "%", 2)} passing under {label}. This is a numerical comparison, not a treatment release.'
            row('Policy thresholds', f'Candidate ≥{passed}%; review ≥{failed}% and <{passed}%; below {failed}% fails')
        else:
            summary = 'Custom gamma comparison completed. No acceptance policy is assigned to this combination of criteria.'
        row('Dose difference / distance', f'{criteria["dose_percent"]}% / {criteria["distance_mm"]} mm', 'Global reference-maximum dose normalization.')
        row('Low-dose cutoff', number(criteria['cutoff_percent'], '%'), 'Relative to reference maximum.')
        row('Passing rate', number(rate, '%', 2), 'Gamma ≤1 on eligible reference voxels.')
        row('Eligible / total reference voxels', f'{result["evaluated_voxels"]} / {result["total_voxels"]}')
        row('Mean / maximum gamma', f'{number(result["average_gamma"])} / {number(result["max_gamma"])}', 'Dimensionless; discrete search without interpolation.')
        actions = ['Verify independent reference provenance, absolute-dose calibration, units, registration and grid coverage.',
                   'Inspect spatial discrepancies and target/OAR DVHs; an aggregate gamma rate cannot localize a clinically relevant error.']
    elif kind == 'radiobiology':
        title = 'Radiobiological model assessment'
        endpoint = 'NTCP' if 'NTCP' in result else 'TCP'
        summary = f'{endpoint} model estimate: {number(result[endpoint] * 100, "%", 2)}. This is conditional on the supplied DVH and model parameters; it is not an individually validated outcome prediction.'
        row('Model', result['model'])
        row(endpoint, number(result[endpoint] * 100, '%', 2), 'Model estimate; no confidence interval computed.')
        row('Equivalent uniform dose', number(result.get('EUD_Gy'), 'Gy'))
        row('DVH representation', result.get('dvh_type', 'Unspecified'))
        for key, value in result.get('parameters_used', {}).items():
            row(f'Model parameter: {key}', value, 'Confirm endpoint, units, fractionation and published calibration cohort.')
        actions = ['Confirm endpoint-specific parameters and the applicable treatment/fractionation regime.',
                   'Review DVH discretization, parameter uncertainty and external calibration before using this estimate in plan assessment.']
    elif kind == 'topas':
        title = 'Monte Carlo parameter-deck handoff'
        summary = 'TOPAS input template generated. No transport simulation, dose distribution or beam commissioning was performed.'
        row('Particle', result.get('particle', 'See deck'))
        row('Kinetic energy', number(result.get('energy_mev'), 'MeV'), 'Supported application range: 0.01–250 MeV.')
        row('Primary histories', result.get('histories', 'See deck'))
        row('Random seed / threads', '42 / 1', 'Fixed template values; retain TOPAS/Geant4 and physics-data versions.')
        row('Scoring quantity', 'DoseToMedium', 'Do not assume equivalence to dose-to-water or a commissioned patient calculation.')
        actions = ['Review geometry, source spectrum, materials, scoring mesh and physics modules in the actual parameter file.',
                   'Run in a validated TOPAS installation; inspect statistical uncertainty and compare with independent measurements.']
    elif kind == 'evaluation':
        title = 'Computational dose-model assessment'
        status = result['status']
        summary = {'APPROVED':'All configured per-case research gates passed. This case is a research candidate; population-wide model validity and clinical release are unestablished.',
                   'REJECTED':'This case failed one or more evaluation gates. Investigate the listed failures and re-evaluate corrected derived outputs.',
                   'FLAGGED_FOR_REVIEW':'Evidence is incomplete, unsupported or within a review band. A qualified reviewer must resolve the listed issues.'}[status]
        row('Model / dataset pseudonym', f'{result["model_name"]} / {result["dataset_id"]}')
        row('Triage state', status)
        row('Hard checks', 'Passed' if result['hard_checks_passed'] else 'Failed')
        metrics=result.get('metrics', {})
        for key,label in [('prescription_gy','Prescription'),('mae_gy','Mean absolute dose error'),('ptv_d95_gy','PTV D95%')]:
            row(label, number(metrics.get(key),'Gy'))
        for entry in result['rules']:
            import json
            observed = json.dumps(entry['observed'], ensure_ascii=False, allow_nan=False)
            labels={'custom_gamma_3pct_3mm':'Gamma passing rate: 3%/3 mm (custom)',
                    'strict_gamma_2pct_2mm':'Gamma passing rate: 2%/2 mm (custom)',
                    'tg218_reference_gamma_3pct_2mm':'Gamma passing rate: 3%/2 mm (TG-218 reference)',
                    'ptv_d95_percent_rx':'PTV D95% / prescription (%)', 'mae_percent_rx':'MAE / prescription (%)'}
            if isinstance(entry['observed'],dict) and 'dmax_gy' in entry['observed']:
                observed=f'Dmax {number(entry["observed"]["dmax_gy"],"Gy")}; limit {number(entry["observed"]["limit_gy"],"Gy")}'
            row(labels.get(entry['name'],entry['name'].replace('_', ' ')), observed, f'{entry["outcome"]}: {entry["criterion"]}')
        actions = ['Resolve every REJECT or REVIEW row against its recorded criterion; do not change raw inputs to obtain a pass.',
                   'Inspect difference maps, uncertainty maps and overlaid DVHs, including critical organs and target cold spots.',
                   'Check qualification, OOD and uncertainty calibration records independently; file hashes establish content identity, not scientific validity.']
        limitations.extend(['Dose/reference geometry is caller-declared; no registration is performed.',
                            'Auto-segmentation is unsupported by the dose policy and requires separate anatomical/surface-distance validation.',
                            'Caller-supplied evidence files are hashed, not scientifically certified.'])
    else:
        raise ValueError('Unknown report type')
    return dict(title=title, summary=summary, metrics=rows, follow_up_actions=actions,
                limitations=list(dict.fromkeys([RESEARCH_SCOPE] + limitations)))


def markdown(report):
    def cell(value):
        return str(value).replace('|', r'\|').replace('\n', ' ')
    lines = [f'# OpenRad — {report["title"]}', '', report['summary'], '',
             '| Measure | Result | Interpretation |', '|---|---|---|']
    lines.extend('| ' + ' | '.join(cell(row[key]) for key in ('Measure','Result','Interpretation')) + ' |' for row in report['metrics'])
    lines.extend(['', '## Follow-up actions', ''] + [f'{i}. {item}' for i,item in enumerate(report['follow_up_actions'],1)])
    lines.extend(['', '## Scope and limitations', ''] + [f'- {item}' for item in report['limitations']])
    return '\n'.join(lines) + '\n'


def attach_report(result, kind):
    from src.storage import current_session
    manager, session_id = current_session()
    report = build_report(result, kind)
    filename = f'report_{uuid4().hex}.md'
    destination = Path(manager.get_artifacts_dir(session_id)) / filename
    with destination.open('x', encoding='utf-8') as handle:
        handle.write(markdown(report))
    result.update(human_report=report, session_id=session_id)
    result.setdefault('artifacts', []).append(f'/artifacts/{session_id}/artifacts/{filename}')
    return result


def metrics_csv(report):
    stream = io.StringIO(); writer = csv.DictWriter(stream, fieldnames=['Measure','Result','Interpretation'])
    writer.writeheader(); writer.writerows(report['metrics'])
    return stream.getvalue()
