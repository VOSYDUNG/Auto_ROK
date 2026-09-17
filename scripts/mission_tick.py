"""Run one deterministic mission occurrence tick; emits proposals but no input."""
from __future__ import annotations
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from harness.mission_ledger import LedgerError, atomic_write, parse_time, tick, validate_plan

def repo_file(value: str, label: str) -> Path:
    path=(ROOT/value).resolve()
    if Path(value).is_absolute() or not path.is_relative_to(ROOT) or not path.is_file(): raise LedgerError(f"{label} must be an existing repository-relative file")
    return path
def ledger_path(value: str) -> Path:
    path=(ROOT/value).resolve(); runs=(ROOT/"workspace/runs").resolve()
    if Path(value).is_absolute() or not path.is_relative_to(runs) or not path.name.endswith(".json"): raise LedgerError("ledger must be JSON under workspace/runs")
    return path
def run_scene(value: str) -> Path:
    path=repo_file(value,"receipt scene")
    if not path.is_relative_to((ROOT/"workspace/runs").resolve()): raise LedgerError("receipt scene must be under workspace/runs")
    return path
def read(path): return json.loads(path.read_text(encoding="utf-8"))
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--plan",required=True); p.add_argument("--scene"); p.add_argument("--ledger",required=True); p.add_argument("--receipt"); p.add_argument("--now"); p.add_argument("--cancel",action="store_true"); a=p.parse_args(argv)
    try:
        plan=validate_plan(read(repo_file(a.plan,"plan"))); path=ledger_path(a.ledger); existing=read(path) if path.is_file() else None
        scene_path=repo_file(a.scene,"scene") if a.scene else None; scene=read(scene_path) if scene_path else None; receipt=read(repo_file(a.receipt,"receipt")) if a.receipt else None
        receipt_evidence=None; evidence_receipt=receipt
        if existing and existing.get("status")=="VERIFIED": evidence_receipt=existing.get("outcome",{}).get("receipt")
        if evidence_receipt:
            receipt_evidence={}
            for ref in (evidence_receipt.get("before_frame"),evidence_receipt.get("after_frame")):
                if not isinstance(ref,dict) or not isinstance(ref.get("scene_path"),str): raise LedgerError("receipt frame reference is invalid")
                evidence_path=run_scene(ref["scene_path"]); receipt_evidence[ref["scene_path"]]=read(evidence_path)
        now=parse_time(a.now) if a.now else datetime.now(timezone.utc)
        result=tick(plan,scene,str(scene_path.relative_to(ROOT)).replace("\\","/") if scene_path else None,existing,now,cancel=a.cancel,receipt=receipt,receipt_evidence=receipt_evidence)
        atomic_write(path,result); print(json.dumps({"status":result["status"],"occurrence_id":result["occurrence_id"],"ledger":str(path),"issued":False})); return 0 if result["status"] in {"WAITING","PROPOSED","VERIFIED","CANCELLED"} else 3
    except (OSError,json.JSONDecodeError,LedgerError) as exc: print(f"mission-tick: error: {exc}",file=sys.stderr); return 2
if __name__=="__main__": raise SystemExit(main())
