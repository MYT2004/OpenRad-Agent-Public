"""OSI CLI: explicit, deterministic tools with session artifacts and guardrails."""
import argparse
import json
import os
from pathlib import Path
from src.tools import parse_and_evaluate_dvh, generate_topas_file
from src.storage import StorageManager, session_scope
from src.config import skills_paths


def main(argv=None):
    parser = argparse.ArgumentParser(description='OpenRad research analysis CLI')
    parser.add_argument('--storage-dir', default=os.getenv('STORAGE_DIR','./storage/sessions'))
    parser.add_argument('--session-id')
    sub = parser.add_subparsers(dest='command', required=True)
    dvh = sub.add_parser('dvh')
    dvh.add_argument('--rtdose',required=True); dvh.add_argument('--rtstruct',required=True)
    dvh.add_argument('--rtplan'); dvh.add_argument('--roi',action='append',required=True)
    dvh.add_argument('--roi-map',type=json.loads,default={})
    topas = sub.add_parser('topas')
    topas.add_argument('--particle',required=True); topas.add_argument('--energy-mev',type=float,required=True)
    topas.add_argument('--histories',type=int,required=True); topas.add_argument('--output')
    evaluate = sub.add_parser('evaluate')
    evaluate.add_argument('--manifest', required=True, help='JSON EvaluationRequest with read-only NPY paths')
    args = parser.parse_args(argv)
    try:
        manager = StorageManager(args.storage_dir)
        with session_scope(manager,args.session_id) as session_id:
            if args.command == 'evaluate':
                from src.decision import EvaluationRequest
                from src.evaluation import evaluate_model
                request = EvaluationRequest.model_validate_json(Path(args.manifest).read_text())
                result = evaluate_model(request)
            elif args.command == 'dvh':
                result = parse_and_evaluate_dvh(args.rtdose,args.rtstruct,args.roi,
                    rtplan_path=args.rtplan,reviewed_name_map=args.roi_map)
            else:
                output = args.output or str(Path(manager.get_artifacts_dir(session_id))/'topas.txt')
                result = generate_topas_file(args.particle,args.energy_mev,args.histories,output)
                result['session_id'] = session_id
            print(json.dumps(result, allow_nan=False))
            if args.command == 'evaluate':
                return {'APPROVED': 0, 'FLAGGED_FOR_REVIEW': 3, 'REJECTED': 2}[result['status']]
            return 0 if args.command != 'dvh' or all(r.get('found') for r in result['structures'].values()) else 2
    except (ValueError,OSError) as exc:
        print(json.dumps({'status':'failed','error':str(exc)}))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
