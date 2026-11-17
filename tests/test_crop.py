from pathlib import Path
from cropquarantine.domain import observation_import,zone_plan,movement_import,diagnose_import,dispatch_import,return_import
from cropquarantine.report import report
from cropquarantine.__main__ import demo
F=Path(__file__).parents[1]/"fixtures"

def test_neighboring_plot_is_quarantined_and_far_plot_can_move(tmp_path):
    db=tmp_path/"db.sqlite"
    observation_import(db,F/"observation-import_normal.json")
    assert zone_plan(db,F/"zone-plan_normal.json")=={"active":2,"released":0,"clear":1}
    assert movement_import(db,F/"movement-import_normal.json")["held"]==1
    statuses={r["id"]:r["status"] for r in report(db)["movement_decision"]}
    assert statuses=={"M1":"held","M3":"allowed"}

def test_outside_observation_does_not_create_zone(tmp_path):
    db=tmp_path/"db.sqlite";observation_import(db,F/"observation-import_normal.json")
    assert observation_import(db,F/"observation-import_conflict.json")["held"]==1
    assert zone_plan(db,F/"zone-plan_normal.json")["active"]==2

def test_reinspection_releases_only_its_plot_and_new_request(tmp_path):
    db=tmp_path/"db.sqlite";observation_import(db,F/"observation-import_normal.json")
    zone_plan(db,F/"zone-plan_normal.json");movement_import(db,F/"movement-import_normal.json")
    assert zone_plan(db,F/"zone-plan_conflict.json")["released"]==1
    movement_import(db,F/"movement-import_conflict.json")
    decisions={r["id"]:r for r in report(db)["movement_decision"]}
    assert decisions["M1"]["status"]=="held"
    assert decisions["M2"]["status"]=="allowed"
    zones={r["plot_id"]:r["status"] for r in report(db)["quarantine_zone"] if r["version"]==2}
    assert zones["P1"]=="released" and zones["P2"]=="active"

def test_import_retry_is_idempotent(tmp_path):
    db=tmp_path/"db.sqlite"
    observation_import(db,F/"observation-import_normal.json")
    observation_import(db,F/"observation-import_normal.json")
    assert len(report(db)["plant_observation"])==1

def test_demo(tmp_path):
    assert demo(tmp_path)["results"]["movement-import"]["held"]==1

def test_late_positive_recalls_dispatched_lot_and_full_return_closes(tmp_path):
    db=tmp_path/"db.sqlite";observation_import(db,F/"observation-import_normal.json")
    zone_plan(db,F/"zone-plan_normal.json");movement_import(db,F/"movement-import_normal.json")
    assert dispatch_import(db,F/"dispatch-import_normal.json")["dispatched"]==1
    observation_import(db,F/"observation-import_late.json")
    zone_plan(db,F/"zone-plan_revision.json")
    data=report(db)
    assert next(m for m in data["movement_decision"] if m["id"]=="M3")["status"]=="recall_required"
    assert data["movement_dispatch"][0]["status"]=="recall_required"
    with __import__("pytest").raises(ValueError,match="recall_return_incomplete"):
        return_import(db,F/"return-import_conflict.json")
    assert report(db)["source_failure"][-1]["error"]=="recall_return_incomplete"
    assert return_import(db,F/"return-import_normal.json")["returned"]==1
    assert next(m for m in report(db)["movement_decision"] if m["id"]=="M3")["status"]=="recalled_closed"
    assert [e["status"] for e in report(db)["movement_event"] if e["movement_id"]=="M3"]==["allowed","recall_required","recalled_closed"]

def test_diagnosis_review_changes_late_observation_causal_result(tmp_path):
    db=tmp_path/"db.sqlite";observation_import(db,F/"observation-import_normal.json")
    zone_plan(db,F/"zone-plan_normal.json");movement_import(db,F/"movement-import_normal.json")
    dispatch_import(db,F/"dispatch-import_normal.json")
    observation_import(db,F/"observation-import_late.json")
    assert diagnose_import(db,F/"diagnose-import_reject.json")["rejected"]==1
    zone_plan(db,F/"zone-plan_revision.json")
    assert next(m for m in report(db)["movement_decision"] if m["id"]=="M3")["status"]=="allowed"
    diagnose_import(db,F/"diagnose-import_confirm.json")
    zone_plan(db,F/"zone-plan_revision3.json")
    assert next(m for m in report(db)["movement_decision"] if m["id"]=="M3")["status"]=="recall_required"

def test_dispatch_is_impossible_for_quarantined_lot(tmp_path):
    import json,pytest
    db=tmp_path/"db.sqlite";observation_import(db,F/"observation-import_normal.json")
    zone_plan(db,F/"zone-plan_normal.json");movement_import(db,F/"movement-import_normal.json")
    file=tmp_path/"bad-dispatch.json"
    file.write_text(json.dumps({"dispatches":[{"id":"D1","movement":"M1","quantity":10,"carrier":"farm-truck-1"}]}),encoding="utf-8")
    with pytest.raises(ValueError,match="movement_not_dispatchable"):
        dispatch_import(db,file)
    assert not report(db)["movement_dispatch"]

def test_positive_reinspection_reactivates_released_zone(tmp_path):
    db=tmp_path/"db.sqlite";observation_import(db,F/"observation-import_normal.json")
    zone_plan(db,F/"zone-plan_normal.json")
    zone_plan(db,F/"zone-plan_conflict.json")
    assert next(z for z in report(db)["quarantine_zone"] if z["plot_id"]=="P1" and z["version"]==2)["status"]=="released"
    zone_plan(db,F/"zone-plan_repositive.json")
    assert next(z for z in report(db)["quarantine_zone"] if z["plot_id"]=="P1" and z["version"]==3)["status"]=="active"

def test_observation_identity_conflict_retains_original_point(tmp_path):
    import json,pytest
    db=tmp_path/"db.sqlite";observation_import(db,F/"observation-import_normal.json")
    changed={"plots":[],"observations":[{"id":"O1","plot":"P1","x":5,"y":5,
        "at":"2026-06-01T09:00:00+08:00","result":"positive"}]}
    file=tmp_path/"changed.json";file.write_text(json.dumps(changed),encoding="utf-8")
    with pytest.raises(ValueError,match="observation_identity_conflict"):
        observation_import(db,file)
    assert report(db)["plant_observation"][0]["x"]==9
    assert report(db)["source_failure"][-1]["error"]=="observation_identity_conflict"
