import json
from pathlib import Path

import pytest

from cropquarantine.domain import observation_import, diagnose_import
from cropquarantine.treatment import treatment_import
from cropquarantine.spray import spray_import, certificate_import
from cropquarantine.report import report

F = Path(__file__).resolve().parents[1] / "fixtures"


def _load_base(db):
    observation_import(db, F / "observation-import_spray.json")
    treatment_import(db, F / "treatment_spray-base.json")
    treatment_import(db, F / "treatment_spray-overdose.json")
    spray_import(db, F / "spray_normal.json")


def _evaluation(data, plot_id):
    return next(e for e in data["spray_evaluation"] if e["plot_id"] == plot_id)


def _cert(data, cert_id):
    for e in data["spray_evaluation"]:
        for c in e["certificates"]:
            if c["id"] == cert_id:
                return c
    raise KeyError(cert_id)


def test_segment_overlap_accumulates_real_dose_and_blocks_any_overdose(tmp_path):
    db = tmp_path / "state.db"
    _load_base(db)
    data = report(db)
    p4 = _evaluation(data, "P4")
    # two passes share CAL2 [0.8,1.2]: overlap region accumulates the common
    # multiplier envelope, never a per-segment favourable pick
    region = p4["overdose_regions"][0]
    assert region["level"] == "definite"
    assert region["bounds"] == [44.0, 0.0, 46.0, 10.0]
    assert region["dose_bounds"]["TOM-SYN"] == (3.2, 4.8)
    point = p4["point_doses"][0]
    assert point["verdict"] == "failed"
    assert point["dose_bounds"]["TOM-SYN"] == (3.2, 4.8)
    # no outside-field area is counted: coverage fraction is plot-internal only
    assert p4["coverage_fraction"] == 1.0
    result = certificate_import(db, F / "certificate_normal.json")
    assert result == {"issued": 2, "review": 0, "refused": 3}
    assert _cert(report(db), "C4")["status"] == "refused"
    assert _cert(report(db), "C4")["reason"] == "overdose_limit_exceeded"


def test_segments_sharing_one_calibration_share_one_multiplier_interval(tmp_path):
    db = tmp_path / "state.db"
    _load_base(db)
    data = report(db)
    p1 = _evaluation(data, "P1")
    cal_ids = {c["id"] for c in p1["calibrations"]}
    assert cal_ids == {"CAL1"}
    # O1 sits in the S1+S2 overlap: 2.5 nominal across one CAL1 envelope
    o1 = next(p for p in p1["point_doses"] if p["observation_id"] == "O1")
    assert o1["verdict"] == "confirmed_covered"
    assert o1["dose_bounds"]["TOM-SYN"] == (2.25, 2.75)
    # every P1 segment carries the same calibration id, so no segment may pick
    # its own multiplier
    assert {s["calibration_id"] for s in p1["segments"]} == {"CAL1"}


def test_boundary_contact_is_not_coverage_and_error_disk_is_fully_checked(tmp_path):
    db = tmp_path / "state.db"
    _load_base(db)
    certificate_import(db, F / "certificate_normal.json")
    p5 = _evaluation(report(db), "P5")
    # O50 sits exactly on the S8 edge with a measurement radius: some possible
    # positions are inside (effective), some bare — therefore review, not pass
    o50 = next(p for p in p5["point_doses"] if p["observation_id"] == "O50")
    assert o50["verdict"] == "review"
    assert o50["boundary_contact"] == ["S8"]
    # O51 is reached by no segment at all
    o51 = next(p for p in p5["point_doses"] if p["observation_id"] == "O51")
    assert o51["verdict"] == "failed"
    assert o51["dose_bounds"] == {}
    # the application cannot be signed while any diseased point is uncertain
    assert _cert(report(db), "C5")["status"] == "refused"
    assert _cert(report(db), "C5")["reason"] == "point_not_covered"

    # zero-radius exact boundary point: boundary-only contact never counts
    obs = {"plots": [{"id": "Q1", "xmin": 0, "ymin": 0, "xmax": 10, "ymax": 10, "crop": "tomato"}],
           "observations": [{"id": "QO1", "plot": "Q1", "x": 5, "y": 5,
                             "at": "2026-07-01T09:00:00+08:00", "result": "positive"}]}
    (tmp_path / "obs.json").write_text(json.dumps(obs), encoding="utf8")
    observation_import(db, tmp_path / "obs.json")
    prod = {"products": [{"id": "TOM-SYN", "crop": "tomato", "min_dose": 1, "max_dose": 3}],
            "applications": [{"id": "QTA1", "plot": "Q1", "product": "TOM-SYN",
                              "at": "2026-07-01T10:00:00+08:00", "area_fraction": 0.5, "dose": 2}]}
    (tmp_path / "prod.json").write_text(json.dumps(prod), encoding="utf8")
    treatment_import(db, tmp_path / "prod.json")
    spray = {"calibrations": [{"id": "QCAL", "plot": "Q1", "factor_min": 1, "factor_max": 1,
                               "certified_at": "2026-06-30T18:00:00+08:00"}],
             "segments": [{"id": "QS1", "plot": "Q1", "application": "QTA1", "calibration": "QCAL",
                           "nozzle": "NZ-1", "at": "2026-07-01T10:00:00+08:00", "product": "TOM-SYN",
                           "xmin": 0, "ymin": 0, "xmax": 5, "ymax": 10, "nominal_dose": 2.0}]}
    (tmp_path / "spray.json").write_text(json.dumps(spray), encoding="utf8")
    spray_import(db, tmp_path / "spray.json")
    q1 = _evaluation(report(db), "Q1")
    qp = q1["point_doses"][0]
    assert qp["verdict"] == "failed" and qp["boundary_contact"] == ["QS1"]


def test_local_certificate_issued_but_whole_plot_refused_with_blank_area(tmp_path):
    db = tmp_path / "state.db"
    _load_base(db)
    certificate_import(db, F / "certificate_normal.json")
    data = report(db)
    p1 = _evaluation(data, "P1")
    # part of the plot is left unsprayed
    assert p1["uncovered_cells"]
    assert p1["coverage_fraction"] < 1.0
    local = _cert(data, "C1")
    whole = _cert(data, "C2")
    assert local["status"] == "issued"
    assert local["printed_scope"] == "local:P1:diseased_points_only"
    assert local["applicable_scope"]["scope"] == "local"
    assert set(local["applicable_scope"]["observations"]) == {"O1", "O2"}
    assert whole["status"] == "refused"
    assert whole["reason"] == "plot_not_fully_covered"
    assert whole["printed_scope"] == "whole_plot:P1"
    assert whole["applicable_scope"] is None
    # a local certificate must never be presented as whole-plot completion
    assert local["applicable_scope"]["scope"] != "whole_plot"


def test_late_confirmation_marks_issued_certificate_for_recheck_without_erasing_it(tmp_path):
    db = tmp_path / "state.db"
    _load_base(db)
    certificate_import(db, F / "certificate_normal.json")
    treatment_import(db, F / "treatment_spray-late.json")
    spray_import(db, F / "spray_late.json")
    data = report(db)
    c6 = _cert(data, "C6")
    # issued certificate keeps its original status and evidence...
    assert c6["status"] == "issued"
    # ...but the new overlap overdose is recorded as a non-destructive follow-up
    assert c6["followups"] == [{"kind": "recheck_required", "detail": "overdose_limit_exceeded"}]
    p6 = _evaluation(data, "P6")
    assert p6["overdose_regions"][0]["dose_bounds"]["TOM-SYN"] == (3.5, 3.5)
    # late confirmed positive outside the sprayed footprint triggers the same path
    late = {"plots": [], "observations": [{"id": "O3", "plot": "P1", "x": 9.5, "y": 9.5,
                                           "at": "2026-07-01T13:00:00+08:00", "result": "positive"}]}
    (tmp_path / "late.json").write_text(json.dumps(late), encoding="utf8")
    observation_import(db, tmp_path / "late.json")
    c1 = _cert(report(db), "C1")
    assert c1["status"] == "issued"
    assert c1["followups"] == [{"kind": "recheck_required", "detail": "point_not_covered"}]
    # rejecting that positive later does not silently wipe the recorded follow-up
    review = {"reviews": [{"id": "DX3", "observation": "O3", "verdict": "rejected",
                           "at": "2026-07-01T14:00:00+08:00", "reviewer": "plant-doctor",
                           "reason": "nutrient damage"}]}
    (tmp_path / "review.json").write_text(json.dumps(review), encoding="utf8")
    diagnose_import(db, tmp_path / "review.json")
    c1 = _cert(report(db), "C1")
    assert c1["status"] == "issued"
    assert c1["followups"] == [{"kind": "recheck_required", "detail": "point_not_covered"}]


def test_repeated_imports_are_idempotent_and_do_not_duplicate_followups(tmp_path):
    db = tmp_path / "state.db"
    _load_base(db)
    _load_base(db)  # re-importing identical spray evidence changes nothing
    certificate_import(db, F / "certificate_normal.json")
    certificate_import(db, F / "certificate_normal.json")
    treatment_import(db, F / "treatment_spray-late.json")
    spray_import(db, F / "spray_late.json")
    spray_import(db, F / "spray_late.json")
    data = report(db)
    assert len(data["spray_segment"]) == 10
    assert len(data["spray_calibration"]) == 4
    assert len(data["treatment_certificate"]) == 5
    followups = data["certificate_followup"]
    assert [f["detail"] for f in followups] == ["overdose_limit_exceeded"]


def test_plot_limits_and_calibration_conflicts_are_rejected(tmp_path):
    db = tmp_path / "state.db"
    _load_base(db)

    def expect(payload, match):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(payload), encoding="utf8")
        with pytest.raises(ValueError, match=match):
            spray_import(db, path)
        assert report(db)["source_failure"][-1]["error"] == match

    segment = {"id": "SX", "plot": "P1", "application": "TA1", "calibration": "CAL1",
               "nozzle": "NZ-9", "at": "2026-07-01T13:00:00+08:00", "product": "TOM-SYN",
               "xmin": 1, "ymin": 1, "xmax": 2, "ymax": 2, "nominal_dose": 1.0}
    # P1 already has five segments: a sixth is accepted, a seventh rejected
    sixth = dict(segment, id="SA")
    assert spray_import_payload(db, tmp_path, [sixth])["segments"] == 1
    seventh = dict(segment, id="SB")
    expect({"calibrations": [], "segments": [seventh]}, "plot_segment_limit")
    # segments wholly outside or merely touching the plot edge cannot dilute area
    outside = dict(segment, id="SO", plot="P6", application="TA5", calibration="CAL4",
                   xmin=90, ymin=0, xmax=95, ymax=10)
    expect({"calibrations": [], "segments": [outside]}, "segment_outside_plot")
    touching = dict(segment, id="ST", plot="P6", application="TA5", calibration="CAL4",
                    xmin=78, ymin=0, xmax=80, ymax=10)
    expect({"calibrations": [], "segments": [touching]}, "segment_outside_plot")
    expect({"calibrations": [{"id": "CALX", "plot": "P6", "factor_min": 1.2, "factor_max": 0.8,
                              "certified_at": "2026-07-01T08:00:00+08:00"}], "segments": []},
           "invalid_calibration_interval")
    expect({"calibrations": [{"id": "CAL1", "plot": "P1", "factor_min": 0.5, "factor_max": 1.5,
                              "certified_at": "2026-06-30T18:00:00+08:00"}], "segments": []},
           "calibration_identity_conflict")


def spray_import_payload(db, tmp_path, segments):
    path = tmp_path / "seg.json"
    path.write_text(json.dumps({"calibrations": [], "segments": segments}), encoding="utf8")
    return spray_import(db, path)


def test_eight_positive_point_limit_per_plot(tmp_path):
    db = tmp_path / "state.db"
    _load_base(db)
    # P6 already has one positive: eight more exceed the per-plot cap of eight
    payload = {"plots": [], "observations": [
        {"id": f"N{i}", "plot": "P6", "x": 81 + 0.1 * i, "y": 9,
         "at": "2026-07-02T09:00:00+08:00", "result": "positive"} for i in range(8)]}
    path = tmp_path / "nine.json"
    path.write_text(json.dumps(payload), encoding="utf8")
    with pytest.raises(ValueError, match="plot_positive_point_limit"):
        observation_import(db, path)
    # the whole import rolled back: no partial points persisted
    assert all(not o["id"].startswith("N") for o in report(db)["plant_observation"])
