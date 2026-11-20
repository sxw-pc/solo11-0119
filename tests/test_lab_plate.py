import json
from pathlib import Path
import pytest
from cropquarantine.domain import observation_import, diagnose_import
from cropquarantine.lab import lab_import
from cropquarantine.report import report

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def _plate(db):
    return {row["position"]: row for row in report(db)["lab_plate"]}


def _verdicts(db):
    return {row["sample_id"]: row["sample_verdict"] for row in report(db)["lab_plate"]
            if row["sample_id"]}


def _run(db):
    return report(db)["lab_run_coefficient"][0]


def test_reused_tip_residue_separates_second_and_third_well(tmp_path):
    db = tmp_path / "state.db"
    observation_import(db, FIX / "observation-import_normal.json")
    assert lab_import(db, FIX / "lab_wells_reuse.json") == {
        "runs": 1, "trusted_samples": 2, "untrusted_samples": 0, "review_samples": 0}
    wells = _plate(db)
    assert wells[2]["true_min"] == pytest.approx(0.45)
    assert wells[3]["true_min"] == pytest.approx(0.505)
    assert _verdicts(db) == {"SP2": "negative", "SP3": "positive"}
    assert _run(db)["status"] == "trusted"
    assert json.loads(_run(db)["feasible_spans"]) == [[0.1, 0.1]]


def test_fresh_tip_zeroes_previous_carry_over(tmp_path):
    db = tmp_path / "state.db"
    observation_import(db, FIX / "observation-import_normal.json")
    lab_import(db, FIX / "lab_wells_fresh_tip.json")
    wells = _plate(db)
    assert wells[2]["true_min"] == pytest.approx(0.55)
    assert wells[3]["true_min"] == pytest.approx(0.55)
    assert _verdicts(db) == {"SS2": "positive", "SS3": "positive"}
    # Identical raw readings, but the signed tip action changes the sample verdict.
    assert _verdicts(db) != {"SS2": "negative", "SS3": "positive"}


def test_interval_coefficient_holds_sample_for_review(tmp_path):
    db = tmp_path / "state.db"
    observation_import(db, FIX / "observation-import_normal.json")
    assert lab_import(db, FIX / "lab_wells_interval.json")["review_samples"] == 1
    well = _plate(db)[2]
    assert (well["true_min"], well["true_max"]) == pytest.approx((0.35, 0.55))
    assert well["sample_verdict"] == "review"
    assert _run(db)["status"] == "trusted"
    assert json.loads(_run(db)["feasible_spans"]) == [[0.0, 0.2]]


def test_control_contradiction_holds_whole_run_without_overwriting(tmp_path):
    db = tmp_path / "state.db"
    observation_import(db, FIX / "observation-import_normal.json")
    assert lab_import(db, FIX / "lab_wells_control_conflict.json")["trusted_samples"] == 0
    assert _run(db)["status"] == "conflict"
    assert json.loads(_run(db)["feasible_spans"]) == []
    assert all(row["true_min"] is None for row in _plate(db).values())
    # A later plate cannot replace the unresolved one without contradicting its evidence.
    changed = json.loads((FIX / "lab_wells_control_conflict.json").read_text(encoding="utf8"))
    changed["wells"][1]["raw"] = 0.7
    file = tmp_path / "changed.json"
    file.write_text(json.dumps(changed), encoding="utf8")
    with pytest.raises(ValueError, match="lab_well_identity_conflict"):
        lab_import(db, file)
    assert _plate(db)[2]["raw"] == 0.8


def test_later_wells_recompute_earlier_plate_verdict(tmp_path):
    db = tmp_path / "state.db"
    observation_import(db, FIX / "observation-import_normal.json")
    first = json.loads((FIX / "lab_wells_reuse.json").read_text(encoding="utf8"))
    del first["wells"][2]
    del first["samples"][1]
    file = tmp_path / "one-well.json"
    file.write_text(json.dumps(first), encoding="utf8")
    lab_import(db, file)
    assert _verdicts(db) == {"SP2": "negative"}
    lab_import(db, FIX / "lab_wells_reuse.json")
    assert _verdicts(db) == {"SP2": "negative", "SP3": "positive"}


def test_review_sample_cannot_back_a_confirmed_diagnosis(tmp_path):
    db = tmp_path / "state.db"
    observation_import(db, FIX / "observation-import_normal.json")
    lab_import(db, FIX / "lab_wells_interval.json")
    review = tmp_path / "review.json"
    review.write_text(json.dumps({"reviews": [{
        "id": "DX-REVIEW", "observation": "O1", "verdict": "confirmed",
        "at": "2026-06-01T11:00:00+08:00", "reviewer": "lab-reviewer",
        "reason": "plate", "lab_sample": "SR2"}]}), encoding="utf8")
    with pytest.raises(ValueError, match="lab_diagnosis_sample_held"):
        diagnose_import(db, review)
    assert not report(db)["lab_diagnosis_basis"]


def test_trusted_positive_well_still_backs_diagnosis(tmp_path):
    db = tmp_path / "state.db"
    observation_import(db, FIX / "observation-import_normal.json")
    lab_import(db, FIX / "lab_wells_reuse.json")
    review = tmp_path / "review.json"
    review.write_text(json.dumps({"reviews": [{
        "id": "DX-PLATE", "observation": "O1", "verdict": "confirmed",
        "at": "2026-06-01T11:00:00+08:00", "reviewer": "lab-reviewer",
        "reason": "residue-corrected third well", "lab_sample": "SP3"}]}), encoding="utf8")
    assert diagnose_import(db, review)["confirmed"] == 1
    assert report(db)["lab_diagnosis_basis"][0]["sample_id"] == "SP3"
    assert _plate(db)[3]["diagnosis_citation"] == "cited_confirmed"
    assert _plate(db)[2]["diagnosis_citation"] == "not_cited"


def test_duplicate_plate_file_is_idempotent_and_conflicting_values_keep_original(tmp_path):
    db = tmp_path / "state.db"
    observation_import(db, FIX / "observation-import_normal.json")
    first = lab_import(db, FIX / "lab_wells_reuse.json")
    assert lab_import(db, FIX / "lab_wells_reuse.json") == first
    assert len(report(db)["lab_plate"]) == 3
    changed = json.loads((FIX / "lab_wells_reuse.json").read_text(encoding="utf8"))
    changed["wells"][2]["raw"] = 0.6
    file = tmp_path / "changed.json"
    file.write_text(json.dumps(changed), encoding="utf8")
    with pytest.raises(ValueError, match="lab_well_identity_conflict"):
        lab_import(db, file)
    assert _plate(db)[3]["raw"] == 0.55
    assert len(report(db)["lab_sample"]) == 2


def test_plate_is_limited_to_six_wells(tmp_path):
    db = tmp_path / "state.db"
    observation_import(db, FIX / "observation-import_normal.json")
    wells = [{"id": f"L{i}", "run": "RUN-LONG", "position": i, "role": "sample",
              "raw": 0.4, "tip_action": "fresh", "sample": f"SL{i}", "observation": "O1"}
             for i in range(1, 8)]
    file = tmp_path / "long.json"
    file.write_text(json.dumps({"runs": [{"id": "RUN-LONG", "at": "2026-06-01T10:00:00+08:00",
        "negative_control": 0.1, "positive_control": 0.9, "residual_coefficient": [0.1, 0.1]}],
        "wells": wells}), encoding="utf8")
    with pytest.raises(ValueError, match="invalid_lab_well"):
        lab_import(db, file)
    assert not report(db)["lab_well"]


def test_plate_sample_requires_both_well_and_original_observation(tmp_path):
    db = tmp_path / "state.db"
    observation_import(db, FIX / "observation-import_normal.json")
    payload = json.loads((FIX / "lab_wells_reuse.json").read_text(encoding="utf8"))
    payload["samples"][0].pop("well")
    file = tmp_path / "missing-well.json"
    file.write_text(json.dumps(payload), encoding="utf8")
    with pytest.raises(ValueError, match="lab_sample_well_required"):
        lab_import(db, file)
    payload = json.loads((FIX / "lab_wells_reuse.json").read_text(encoding="utf8"))
    payload["wells"][1]["observation"] = "O-MISSING"
    payload["samples"][0]["observation"] = "O-MISSING"
    file = tmp_path / "missing-observation.json"
    file.write_text(json.dumps(payload), encoding="utf8")
    with pytest.raises(ValueError, match="invalid_lab_sample_basis"):
        lab_import(db, file)


def test_legacy_fixture_still_judges_independent_samples(tmp_path):
    db = tmp_path / "state.db"
    observation_import(db, FIX / "observation-import_normal.json")
    assert lab_import(db, FIX / "lab_normal.json")["trusted_samples"] == 1
    assert lab_import(db, FIX / "lab_conflict.json")["untrusted_samples"] == 1
    rows = {row["id"]: row for row in report(db)["lab_sample"]}
    assert rows["S1"]["verdict"] == "positive"
    assert rows["S2"]["verdict"] == "untrusted"
    assert not report(db)["lab_well"]
