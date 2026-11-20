"""Offline sample runs with explicit controls, plate order and observation identity.

A plate is read in order.  When a tip is reused the observed reading is the
well's own true signal plus one common coefficient times the previous well's
true signal.  A fresh tip (or a flush) clears that carry-over.  One coefficient
range is issued for the whole run and must, together with both control ranges,
explain every well; no well gets its own coefficient.

Because the previous well's true signal is itself part of the explanation, a
well's true signal is a polynomial in the shared coefficient.  We therefore
compute the exact (up to numeric root isolation) set of compatible coefficients
before deciding any sample.  A sample is positive only when every compatible
explanation reaches the positive threshold, negative only when every one stays
below it, and otherwise held for review.
"""
import json
from .intake import ingest
from .domain import _time

EPS = 1e-9
THRESHOLD = 0.5
NEGATIVE_CONTROL_RANGE = (0.0, 0.2)
POSITIVE_CONTROL_RANGE = (0.8, 1.0)
ROLE_RANGES = {"negative_control": NEGATIVE_CONTROL_RANGE,
               "positive_control": POSITIVE_CONTROL_RANGE,
               "sample": (0.0, 1.0)}
FRESH_TIP = {"fresh", "flush"}
REUSE_TIP = {"reuse"}
MAX_WELLS = 6


# --- polynomials in the shared residue coefficient -------------------------

def _poly(coefficient):
    return [float(coefficient)]


def _const(value):
    return [float(value)]


def _shift(poly):
    return [0.0] + list(poly)


def _sub(first, second):
    size = max(len(first), len(second))
    out = [0.0] * size
    for i in range(size):
        out[i] = (first[i] if i < len(first) else 0.0) - (second[i] if i < len(second) else 0.0)
    return out


def _eval(poly, value):
    result = 0.0
    for coefficient in reversed(poly):
        result = result * value + coefficient
    return result


def _derivative(poly):
    return [poly[i] * i for i in range(1, len(poly))] or [0.0]


def _trim(poly):
    while len(poly) > 1 and abs(poly[-1]) < EPS:
        poly = poly[:-1]
    return poly


def _roots(poly, low, high):
    """All real roots of ``poly`` in [low, high] via recursive critical points."""
    poly = _trim(poly)
    degree = len(poly) - 1
    if degree <= 0:
        return []
    if degree == 1:
        root = -poly[0] / poly[1]
        return [root] if low - EPS <= root <= high + EPS else []
    critical = sorted({round(r, 10) for r in _roots(_derivative(poly), low, high)
                       if low - EPS <= r <= high + EPS})
    points = [low] + [r for r in critical if low < r < high] + [high]
    found = []
    for r in critical:
        if abs(_eval(poly, r)) <= 1e-7:
            found.append(r)
    for left, right in zip(points, points[1:]):
        f_left, f_right = _eval(poly, left), _eval(poly, right)
        if abs(f_left) <= EPS:
            found.append(left)
        if f_left * f_right < 0:
            start, stop = left, right
            for _ in range(100):
                middle = (start + stop) / 2
                if _eval(poly, start) * _eval(poly, middle) <= 0:
                    stop = middle
                else:
                    start = middle
            found.append((start + stop) / 2)
    if abs(_eval(poly, high)) <= EPS:
        found.append(high)
    return sorted({round(r, 10) for r in found})


def _merge(intervals):
    merged = []
    for low, high in sorted(intervals):
        if merged and low <= merged[-1][1] + 1e-7:
            merged[-1] = (merged[-1][0], max(merged[-1][1], high))
        else:
            merged.append((low, high))
    return merged


def _feasible(rows, issued):
    """Rows are (polynomial, low, high); return compatible coefficient intervals."""
    low, high = issued
    if low > high + EPS:
        return []
    cuts = {low, high}
    for poly, floor, ceiling in rows:
        cuts.update(r for r in _roots(_sub(poly, _const(floor)), low, high))
        cuts.update(r for r in _roots(_sub(poly, _const(ceiling)), low, high))
    points = sorted(c for c in cuts if low - EPS <= c <= high + EPS)
    compatible = lambda c: all(floor - EPS <= _eval(poly, c) <= ceiling + EPS
                               for poly, floor, ceiling in rows)
    intervals = []
    for point in points:
        if compatible(point):
            intervals.append((point, point))
    for left, right in zip(points, points[1:]):
        if right - left <= EPS:
            continue
        if compatible((left + right) / 2):
            intervals.append((left, right))
    return _merge(intervals)


def _range_over(poly, intervals):
    values = []
    for left, right in intervals:
        points = [left, right] + [r for r in _roots(_derivative(poly), left, right)
                                  if left < r < right]
        values.extend(_eval(poly, point) for point in points)
    return min(values), max(values)


def _verdict(bounds):
    low, high = bounds
    if low >= THRESHOLD - EPS:
        return "positive"
    if high <= THRESHOLD + EPS:
        return "negative"
    return "review"


# --- run, well and sample evidence ----------------------------------------

def _coefficient_range(run):
    raw = run.get("residual_coefficient")
    if raw is None:
        return None
    if isinstance(raw, dict):
        low, high = float(raw["min"]), float(raw["max"])
    else:
        low, high = float(raw[0]), float(raw[1])
    if not 0 <= low <= high <= 1:
        raise ValueError("invalid_lab_residual_range")
    return (low, high)


def _true_signal_polynomial(well, previous):
    """Reading = own signal + coefficient * previous signal on a reused tip."""
    if well["position"] == 1 or well["tip_action"] in FRESH_TIP:
        return _const(well["raw"])
    return _sub(_const(well["raw"]), _shift(previous))


def _prepare_well(item):
    position, action, role = int(item["position"]), item["tip_action"], item["role"]
    raw = float(item["raw"])
    if action not in FRESH_TIP | REUSE_TIP or role not in ROLE_RANGES:
        raise ValueError("invalid_lab_well")
    if not 0 <= raw <= 1 or not 1 <= position <= MAX_WELLS:
        raise ValueError("invalid_lab_well")
    return {"id": item["id"], "position": position, "role": role, "raw": raw,
            "tip_action": action, "sample_id": item.get("sample"),
            "observation_id": item.get("observation")}


def _wells_from_db(db, run_id):
    rows = [dict(row) for row in db.execute(
        "SELECT * FROM lab_well WHERE run_id=? ORDER BY position", (run_id,))]
    return [{"id": row["id"], "position": row["position"], "role": row["role"],
             "raw": row["raw"], "tip_action": row["tip_action"],
             "sample_id": row["sample_id"], "observation_id": row["observation_id"]}
            for row in rows]


def _evaluate(db, run_id, issued):
    """Return (compatible coefficient intervals, per-well bounds, sample verdicts)."""
    wells = _wells_from_db(db, run_id)
    if not wells:
        return [], {}, {}
    if (len(wells) > MAX_WELLS
            or [well["position"] for well in wells] != list(range(1, len(wells) + 1))):
        raise ValueError("invalid_lab_well_position")
    rows, polynomials = [], {}
    previous = _const(0.0)
    for well in wells:
        signal = _true_signal_polynomial(well, previous)
        polynomials[well["position"]] = signal
        floor, ceiling = ROLE_RANGES[well["role"]]
        rows.append((signal, floor, ceiling))
        previous = signal
    compatible = _feasible(rows, issued)
    if not compatible:
        return [], {}, {}
    bounds = {position: _range_over(poly, compatible)
              for position, poly in polynomials.items()}
    verdicts = {well["position"]: _verdict(bounds[well["position"]])
                for well in wells if well["role"] == "sample"}
    return compatible, bounds, verdicts


def _signoff(run):
    negative, positive = float(run["negative_control"]), float(run["positive_control"])
    if not 0 <= negative <= 1 or not 0 <= positive <= 1:
        raise ValueError("invalid_lab_control")
    return "trusted" if negative < 0.2 and positive >= 0.8 else "untrusted"


def _store_run(db, run, source, counts):
    _time(run["at"])
    status = _signoff(run)
    values = (run["at"], float(run["negative_control"]), float(run["positive_control"]), status)
    old = db.execute("SELECT * FROM lab_run WHERE id=?", (run["id"],)).fetchone()
    if old:
        if tuple(old[k] for k in ("run_at", "negative_control", "positive_control", "status")) != values:
            raise ValueError("lab_run_identity_conflict")
    else:
        db.execute("INSERT INTO lab_run VALUES (?,?,?,?,?,?)", (run["id"], *values, source))
        counts["runs"] += 1


def _store_well(db, run_id, well, source):
    if well["role"] == "sample" and (not well["sample_id"] or not well["observation_id"]):
        raise ValueError("invalid_lab_well_sample")
    values = (run_id, well["position"], well["role"], well["raw"], well["tip_action"],
              well["sample_id"], well["observation_id"])
    old = db.execute("SELECT * FROM lab_well WHERE id=?", (well["id"],)).fetchone()
    if old:
        if tuple(old[k] for k in ("run_id", "position", "role", "raw", "tip_action",
                                  "sample_id", "observation_id")) != values:
            raise ValueError("lab_well_identity_conflict")
        return
    if db.execute("SELECT 1 FROM lab_well WHERE run_id=? AND position=?",
                  (run_id, well["position"])).fetchone():
        raise ValueError("lab_well_position_conflict")
    db.execute("INSERT INTO lab_well VALUES (?,?,?,?,?,?,?,?,?,?,?)",
               (well["id"], *values, None, None, source))


def _store_coefficient(db, run_id, issued, compatible, status, source):
    old = db.execute("SELECT * FROM lab_run_coefficient WHERE run_id=?", (run_id,)).fetchone()
    spans = json.dumps([[low, high] for low, high in compatible])
    if old:
        if (old["issued_min"], old["issued_max"]) != issued:
            raise ValueError("lab_run_coefficient_conflict")
        db.execute("UPDATE lab_run_coefficient SET feasible_spans=?,status=? WHERE run_id=?",
                   (spans, status, run_id))
    else:
        db.execute("INSERT INTO lab_run_coefficient VALUES (?,?,?,?,?,?)",
                   (run_id, issued[0], issued[1], spans, status, source))


def _store_sample(db, sample_id, run_id, observation_id, signal, verdict, source, counts, derived=False):
    values = (run_id, observation_id, signal, verdict)
    old = db.execute("SELECT * FROM lab_sample WHERE id=?", (sample_id,)).fetchone()
    if old:
        if tuple(old[k] for k in ("run_id", "observation_id", "signal")) != values[:3]:
            raise ValueError("lab_sample_identity_conflict")
        if old["verdict"] != verdict:
            # A plate verdict is derived from the whole run; new wells may change it.
            if not derived or verdict not in {"positive", "negative", "review", "untrusted"}:
                raise ValueError("lab_sample_identity_conflict")
            if db.execute("SELECT 1 FROM lab_diagnosis_basis WHERE sample_id=?", (sample_id,)).fetchone():
                raise ValueError("lab_sample_identity_conflict")
            db.execute("UPDATE lab_sample SET verdict=? WHERE id=?", (verdict, sample_id))
        return
    db.execute("INSERT INTO lab_sample VALUES (?,?,?,?,?,?)", (sample_id, *values, source))
    counts["trusted_samples" if verdict in {"positive", "negative"} else
           "review_samples" if verdict == "review" else "untrusted_samples"] += 1


def _check_basis(db, run, observation_id):
    obs = db.execute("SELECT * FROM plant_observation WHERE id=?", (observation_id,)).fetchone()
    if not obs or obs["status"] != "valid" or _time(run["run_at"]) < _time(obs["observed_at"]):
        raise ValueError("invalid_lab_sample_basis")


def lab_import(path, file):
    def handler(db, data, source):
        counts = {"runs": 0, "trusted_samples": 0, "untrusted_samples": 0, "review_samples": 0}
        for run in data.get("runs", []):
            _store_run(db, run, source, counts)
        issued_by_run = {}
        for item in data.get("wells", []):
            run = db.execute("SELECT * FROM lab_run WHERE id=?", (item["run"],)).fetchone()
            if not run:
                raise ValueError("invalid_lab_sample_basis")
            raw_run = next((r for r in data.get("runs", []) if r["id"] == item["run"]), None)
            coefficient = _coefficient_range(raw_run) if raw_run else None
            if coefficient is None:
                stored = db.execute("SELECT * FROM lab_run_coefficient WHERE run_id=?",
                                    (item["run"],)).fetchone()
                if stored:
                    coefficient = (stored["issued_min"], stored["issued_max"])
            if coefficient is None:
                raise ValueError("missing_lab_residual_range")
            if issued_by_run.setdefault(item["run"], coefficient) != coefficient:
                raise ValueError("invalid_lab_residual_range")
            _store_well(db, item["run"], _prepare_well(item), source)
        for run_id, issued in issued_by_run.items():
            run = db.execute("SELECT * FROM lab_run WHERE id=?", (run_id,)).fetchone()
            compatible, bounds, verdicts = _evaluate(db, run_id, issued)
            status = "conflict" if not compatible else run["status"]
            _store_coefficient(db, run_id, issued, compatible, status, source)
            for position, (low, high) in bounds.items():
                db.execute("UPDATE lab_well SET true_min=?,true_max=? WHERE run_id=? AND position=?",
                           (low, high, run_id, position))
            for well in _wells_from_db(db, run_id):
                if well["role"] != "sample":
                    continue
                _check_basis(db, run, well["observation_id"])
                verdict = "untrusted" if status != "trusted" else verdicts[well["position"]]
                _store_sample(db, well["sample_id"], run_id, well["observation_id"],
                              well["raw"], verdict, source, counts, derived=True)
        for sample in data.get("samples", []):
            signal = float(sample["signal"])
            if not 0 <= signal <= 1:
                raise ValueError("invalid_lab_signal")
            run = db.execute("SELECT * FROM lab_run WHERE id=?", (sample["run"],)).fetchone()
            if not run:
                raise ValueError("invalid_lab_sample_basis")
            if db.execute("SELECT 1 FROM lab_well WHERE run_id=?", (sample["run"],)).fetchone():
                if not sample.get("well"):
                    raise ValueError("lab_sample_well_required")
            if sample.get("well"):
                well = db.execute("SELECT * FROM lab_well WHERE id=? AND run_id=?",
                                  (sample["well"], sample["run"])).fetchone()
                if (not well or well["role"] != "sample"
                        or well["sample_id"] != sample["id"]
                        or well["observation_id"] != sample["observation"]):
                    raise ValueError("lab_sample_well_conflict")
                continue  # already stored together with its plate evidence
            _check_basis(db, run, sample["observation"])
            verdict = ("untrusted" if run["status"] != "trusted" else
                       "positive" if signal >= THRESHOLD else "negative")
            _store_sample(db, sample["id"], sample["run"], sample["observation"],
                          signal, verdict, source, counts)
        return counts
    return ingest(path, "lab", file, handler)
