import argparse
import json
import tempfile
from pathlib import Path
from .domain import observation_import,zone_plan,movement_import,diagnose_import,dispatch_import,return_import
from .report import report,report_json

COMMANDS={"observation-import":observation_import,"zone-plan":zone_plan,"movement-import":movement_import,
          "diagnose-import":diagnose_import,"dispatch-import":dispatch_import,"return-import":return_import}

def demo(workdir=None):
    root=Path(workdir or tempfile.mkdtemp(prefix="cropquarantine-"))
    root.mkdir(parents=True,exist_ok=True)
    db=root/"data.db"
    fixtures=Path.cwd()/"fixtures"
    results={}
    for name in ("observation-import","zone-plan","movement-import"):
        func=COMMANDS[name]
        results[name]=func(db,fixtures/(name+"_normal.json"))
    return {"db":str(db),"results":results}

def decision_demo(workdir=None):
    root=Path(workdir or tempfile.mkdtemp(prefix="cropquarantine-decisions-"));root.mkdir(parents=True,exist_ok=True)
    db=root/"data.db";fixtures=Path.cwd()/"fixtures"
    observation_import(db,fixtures/"observation-import_normal.json")
    zone_plan(db,fixtures/"zone-plan_normal.json")
    movement_import(db,fixtures/"movement-import_normal.json")
    dispatch_import(db,fixtures/"dispatch-import_normal.json")
    observation_import(db,fixtures/"observation-import_late.json")
    zone_plan(db,fixtures/"zone-plan_revision.json")
    recalled={x["id"]:x["status"] for x in report(db)["movement_decision"]}
    return_import(db,fixtures/"return-import_normal.json")
    closed={x["id"]:x["status"] for x in report(db)["movement_decision"]}
    return {"db":str(db),"after_late_observation":recalled,"after_return":closed}

def main():
    parser=argparse.ArgumentParser()
    subs=parser.add_subparsers(dest="command",required=True)
    for name in COMMANDS:
        sub=subs.add_parser(name);sub.add_argument("--db",required=True);sub.add_argument("--file",required=True)
    d=subs.add_parser("demo");d.add_argument("--workdir")
    dd=subs.add_parser("demo-decisions");dd.add_argument("--workdir")
    r=subs.add_parser("report");r.add_argument("--db",required=True)
    args=parser.parse_args()
    if args.command=="demo":print(json.dumps(demo(args.workdir),ensure_ascii=False))
    elif args.command=="demo-decisions":print(json.dumps(decision_demo(args.workdir),ensure_ascii=False))
    elif args.command=="report":print(report_json(args.db))
    else:print(json.dumps(COMMANDS[args.command](args.db,args.file),ensure_ascii=False))
if __name__=="__main__":main()
