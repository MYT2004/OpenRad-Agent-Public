"""Local-only integration audit; no uploads and no automatic source repairs.

Run as: python -m scripts.verify_local_datasets folder1 folder2 --reference
Reports go to ignored data/processed by default.
"""
import argparse
import hashlib
import json
from pathlib import Path
import pydicom
from openrad.tools.dataset import discover_dataset
from openrad.tools.dicom_tool import analyze_dvh
from openrad.validation.physics_rules import PhysicsValidationEngine


def verify(roots, reference=False):
    reports=[]
    for root in roots:
        scan=discover_dataset(root)
        report={'dataset':Path(root).name,'counts':scan['modality_counts'],'scan_errors':scan['scan_errors'],'dose_pairs':[]}
        for pair in scan['dose_cases']:
            dose=pydicom.dcmread(pair['dose_path'])
            values=dose.pixel_array.astype(float)*float(dose.DoseGridScaling)
            integrity=PhysicsValidationEngine.validate_dose_grid(values,raise_on_fail=True)
            item={'blockers':pair['blockers'],'dose_integrity':integrity.to_dict(),
                  'source_sha256':{key:hashlib.sha256(Path(pair[key]).read_bytes()).hexdigest() for key in ('dose_path','plan_path','struct_path') if pair[key]}}
            if not pair['blockers']:
                names=[r['name'] for r in pair['rois'] if r['nomenclature']['canonical_name']]
                result=analyze_dvh(pair['struct_path'],pair['dose_path'],names,dicom_rtplan_path=pair['plan_path'])
                item['structures']=result['structures']
                if reference:
                    from dicompylercore import dvhcalc
                    for name,r in result['structures'].items():
                        if not r.get('found'):continue
                        ref=dvhcalc.get_dvh(pair['struct_path'],pair['dose_path'],r['roi_number'])
                        r['independent_reference']={'package':'dicompyler-core 0.5.6','volume_cc':float(ref.volume),'mean_Gy':float(ref.mean),'D95_Gy':float(ref.D95.value)}
                        r['reference_discrepancy']={'volume_cc':r['volume_cc']-float(ref.volume),'mean_Gy':r['mean_dose_Gy']-float(ref.mean),'D95_Gy':r['D95_Gy']-float(ref.D95.value)}
            report['dose_pairs'].append(item)
        reports.append(report)
    return reports


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('roots',nargs='+')
    parser.add_argument('--reference',action='store_true')
    parser.add_argument('--output',default='data/processed/dataset-verification.json')
    args=parser.parse_args()
    report=verify(args.roots,args.reference)
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2))
    for case in report:
        print(case['dataset'],case['counts'],'pairs:',len(case['dose_pairs']))
        for pair in case['dose_pairs']:
            print('  blocked:',bool(pair['blockers']),'computed ROIs:',sum(r.get('found',False) for r in pair.get('structures',{}).values()))
    print('Local report:',out.resolve())
