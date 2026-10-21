"""Read-only DVH assessment using an explicitly supplied local DICOM dataset."""
import argparse
import json
from openrad.tools.dataset import discover_dataset
from src.tools import parse_and_evaluate_dvh
from src.storage import StorageManager, session_scope
from src.reports import markdown


def run_demo(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset_root')
    parser.add_argument('--pair',type=int,default=0)
    parser.add_argument('--roi',action='append',required=True)
    parser.add_argument('--roi-map',type=json.loads,default={})
    args=parser.parse_args(argv)
    scan=discover_dataset(args.dataset_root)
    if not 0<=args.pair<len(scan['dose_cases']):
        parser.error('Select an existing dose pair from dataset discovery.')
    pair=scan['dose_cases'][args.pair]
    if pair['blockers']:
        parser.error('Selected pair is blocked: '+'; '.join(pair['blockers']))
    with session_scope(StorageManager()):
        result=parse_and_evaluate_dvh(pair['dose_path'],pair['struct_path'],args.roi,
            rtplan_path=pair['plan_path'],reviewed_name_map=args.roi_map)
    print(markdown(result['human_report']))
    print('Session:',result['session_id'])
    return 0 if all(item.get('found') for item in result['structures'].values()) else 2


if __name__=='__main__':
    raise SystemExit(run_demo())
