from pathlib import Path
from cropquarantine.domain import observation_import, zone_plan, diagnose_import
from cropquarantine.lab import lab_import
from cropquarantine.treatment import treatment_import
from cropquarantine.staff import staff_import
from cropquarantine.report import report

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def test_lab_control_and_diagnosis_basis(tmp_path):
    db = tmp_path / "state.db"
    observation_import(db, FIX / "observation-import_normal.json")
    assert lab_import(db, FIX / "lab_normal.json")["trusted_samples"] == 1
    assert lab_import(db, FIX / "lab_conflict.json")["untrusted_samples"] == 1
    review = tmp_path / "review.json"
    review.write_text('{"reviews":[{"id":"DX-LAB","observation":"O1","verdict":"confirmed","at":"2026-06-01T11:00:00+08:00","reviewer":"lab-reviewer","reason":"trusted run","lab_sample":"S1"}]}', encoding="utf8")
    assert diagnose_import(db, review)["confirmed"] == 1
    rows = report(db)
    assert rows["lab_diagnosis_basis"][0]["sample_id"] == "S1"
    assert len(rows["lab_sample"]) == 2


def test_treatment_has_own_plot_crop_and_dose_decision(tmp_path):
    db = tmp_path / "state.db"
    observation_import(db, FIX / "observation-import_normal.json")
    assert treatment_import(db, FIX / "treatment_normal.json")["applied"] == 1
    assert treatment_import(db, FIX / "treatment_conflict.json")["held"] == 1
    assert {row["id"]: row["status"] for row in report(db)["treatment_application"]} == {"TA1": "applied", "TA2": "held"}


def test_staff_entry_uses_zone_state_without_changing_it(tmp_path):
    db = tmp_path / "state.db"
    observation_import(db, FIX / "observation-import_normal.json")
    zone_plan(db, FIX / "zone-plan_normal.json")
    assert staff_import(db, FIX / "staff_normal.json")["admitted"] == 1
    assert staff_import(db, FIX / "staff_conflict.json")["held"] == 1
    rows = report(db)
    assert {row["id"]: row["status"] for row in rows["staff_entry"]} == {"E1": "admitted", "E2": "held"}
    assert next(row for row in rows["quarantine_zone"] if row["plot_id"] == "P1")["status"] == "active"
