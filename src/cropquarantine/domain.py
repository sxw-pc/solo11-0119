from datetime import datetime
from math import hypot
from .intake import ingest

def _time(value):
    dt=datetime.fromisoformat(value)
    if dt.tzinfo is None:raise ValueError("timezone_required")
    return dt

def observation_import(path,file):
    def handler(db,data,source):
        result={"plots":0,"observations":0,"held":0}
        for p in data["plots"]:
            if p["xmin"]>=p["xmax"] or p["ymin"]>=p["ymax"]:raise ValueError("invalid_plot_bounds")
            old=db.execute("SELECT * FROM field_plot WHERE id=?",(p["id"],)).fetchone()
            values=(p["xmin"],p["ymin"],p["xmax"],p["ymax"],p["crop"])
            if old and tuple(old[k] for k in ("xmin","ymin","xmax","ymax","crop"))!=values:raise ValueError("plot_identity_conflict")
            if not old:db.execute("INSERT INTO field_plot VALUES (?,?,?,?,?,?,?)",(p["id"],*values,source));result["plots"]+=1
        for o in data["observations"]:
            _time(o["at"])
            plot=db.execute("SELECT * FROM field_plot WHERE id=?",(o["plot"],)).fetchone()
            valid=bool(plot and plot["xmin"]<=o["x"]<=plot["xmax"] and plot["ymin"]<=o["y"]<=plot["ymax"] and o["result"] in {"positive","negative"})
            status="valid" if valid else "held"
            old=db.execute("SELECT * FROM plant_observation WHERE id=?",(o["id"],)).fetchone()
            values=(o["plot"],o["x"],o["y"],o["at"],o["result"],status)
            if old and tuple(old[k] for k in ("plot_id","x","y","observed_at","result","status"))!=values:raise ValueError("observation_identity_conflict")
            if not old:db.execute("INSERT INTO plant_observation VALUES (?,?,?,?,?,?,?,?)",(o["id"],*values,source));result["observations"]+=1
            result["held"]+=not valid
        return result
    return ingest(path,"observation",file,handler)

def _distance(x,y,plot):
    dx=max(plot["xmin"]-x,0,x-plot["xmax"])
    dy=max(plot["ymin"]-y,0,y-plot["ymax"])
    return hypot(dx,dy)

def _movement(db,lot,when):
    plot=db.execute("SELECT * FROM field_plot WHERE id=?",(lot["plot_id"],)).fetchone()
    zone=db.execute("SELECT * FROM quarantine_zone WHERE plot_id=? AND asof<=? ORDER BY version DESC LIMIT 1",
                    (plot["id"],when)).fetchone()
    if not zone:return "allowed","no_active_zone",None
    return ("held","quarantine_active",zone["version"]) if zone["status"]=="active" else ("allowed","released_after_reinspection",zone["version"])

def _recompute(db,source):
    for movement in db.execute("SELECT * FROM movement_decision").fetchall():
        lot=db.execute("SELECT * FROM plant_lot WHERE id=?",(movement["lot_id"],)).fetchone()
        status,reason,version=_movement(db,lot,movement["request_at"])
        dispatch=db.execute("SELECT * FROM movement_dispatch WHERE movement_id=?",(movement["id"],)).fetchone()
        if status=="held" and dispatch and dispatch["status"] in {"dispatched","recall_required"}:
            status,reason="recall_required","late_positive_recall"
            db.execute("UPDATE movement_dispatch SET status='recall_required' WHERE id=?",(dispatch["id"],))
        elif status=="allowed" and dispatch and dispatch["status"]=="recall_required":
            reason="recall_cancelled_by_new_evidence"
            db.execute("UPDATE movement_dispatch SET status='dispatched' WHERE id=?",(dispatch["id"],))
        elif dispatch and dispatch["status"]=="returned":
            status,reason="recalled_closed","physical_return_confirmed"
        if (movement["status"],movement["reason"],movement["zone_version"])!=(status,reason,version):
            db.execute("UPDATE movement_decision SET status=?,reason=?,zone_version=? WHERE id=?",
                       (status,reason,version,movement["id"]))
            db.execute("INSERT INTO movement_event(movement_id,status,reason,zone_version,source_id) VALUES (?,?,?,?,?)",
                       (movement["id"],status,reason,version,source))

def zone_plan(path,file):
    def handler(db,data,source):
        asof=_time(data["asof"]);radius=float(data["radius"])
        if radius<0:raise ValueError("invalid_radius")
        for r in data.get("reinspections",[]):
            _time(r["at"])
            if r["result"] not in {"positive","negative"}:raise ValueError("invalid_reinspection")
            old=db.execute("SELECT * FROM reinspection WHERE id=?",(r["id"],)).fetchone()
            if old and tuple(old[k] for k in ("plot_id","observed_at","result"))!=(r["plot"],r["at"],r["result"]):
                raise ValueError("reinspection_identity_conflict")
            db.execute("INSERT OR IGNORE INTO reinspection VALUES (?,?,?,?,?)",(r["id"],r["plot"],r["at"],r["result"],source))
        result={"active":0,"released":0,"clear":0}
        positives=[]
        for o in db.execute("SELECT * FROM plant_observation WHERE status='valid' AND result='positive'"):
            if _time(o["observed_at"])>asof:continue
            reviews=[r for r in db.execute("SELECT * FROM diagnosis_review WHERE observation_id=? ORDER BY reviewed_at,id",(o["id"],))
                     if _time(r["reviewed_at"])<=asof]
            if not reviews or reviews[-1]["verdict"]=="confirmed":positives.append(o)
        for plot in db.execute("SELECT * FROM field_plot ORDER BY id").fetchall():
            nearby=[o for o in positives if _distance(o["x"],o["y"],plot)<=radius]
            version=db.execute("SELECT COALESCE(MAX(version),0)+1 FROM quarantine_zone WHERE plot_id=?",(plot["id"],)).fetchone()[0]
            if not nearby:status,reason="clear","no_nearby_positive"
            else:
                latest=max(_time(o["observed_at"]) for o in nearby)
                checks=[r for r in db.execute("SELECT * FROM reinspection WHERE plot_id=?",(plot["id"],)) if latest<_time(r["observed_at"])<=asof]
                checks.sort(key=lambda r:r["observed_at"])
                released=len(checks)>=2 and all(r["result"]=="negative" for r in checks[-2:])
                status,reason=("released","two_negative_rechecks") if released else ("active","positive_within_radius")
            db.execute("INSERT INTO quarantine_zone(plot_id,version,asof,radius,status,reason,source_id) VALUES (?,?,?,?,?,?,?)",
                       (plot["id"],version,data["asof"],radius,status,reason,source))
            result[status]+=1
        _recompute(db,source)
        return result
    return ingest(path,"zone",file,handler)

def movement_import(path,file):
    def handler(db,data,source):
        result={"lots":0,"allowed":0,"held":0}
        for lot in data["lots"]:
            if lot["quantity"]<=0 or not db.execute("SELECT 1 FROM field_plot WHERE id=?",(lot["plot"],)).fetchone():
                raise ValueError("invalid_lot")
            old=db.execute("SELECT * FROM plant_lot WHERE id=?",(lot["id"],)).fetchone()
            if old and (old["plot_id"],old["quantity"])!=(lot["plot"],lot["quantity"]):raise ValueError("lot_identity_conflict")
            if not old:db.execute("INSERT INTO plant_lot VALUES (?,?,?,?)",(lot["id"],lot["plot"],lot["quantity"],source));result["lots"]+=1
        for req in data["requests"]:
            _time(req["at"])
            lot=db.execute("SELECT * FROM plant_lot WHERE id=?",(req["lot"],)).fetchone()
            if not lot:raise ValueError("unknown_lot")
            old=db.execute("SELECT * FROM movement_decision WHERE id=?",(req["id"],)).fetchone()
            if old and (old["lot_id"],old["request_at"])!=(req["lot"],req["at"]):raise ValueError("movement_identity_conflict")
            if not old:
                status,reason,version=_movement(db,lot,req["at"])
                db.execute("INSERT INTO movement_decision VALUES (?,?,?,?,?,?,?)",
                           (req["id"],req["lot"],req["at"],status,reason,version,source))
                db.execute("INSERT INTO movement_event(movement_id,status,reason,zone_version,source_id) VALUES (?,?,?,?,?)",
                           (req["id"],status,reason,version,source))
                result[status]+=1
        return result
    return ingest(path,"movement",file,handler)

def diagnose_import(path,file):
    """Independent field diagnosis can confirm or reject a recorded positive."""
    def handler(db,data,source):
        result={"confirmed":0,"rejected":0}
        for item in data["reviews"]:
            obs=db.execute("SELECT * FROM plant_observation WHERE id=?",(item["observation"],)).fetchone()
            if not obs or obs["status"]!="valid" or _time(item["at"])<_time(obs["observed_at"]):
                raise ValueError("invalid_diagnosis_basis")
            if item["verdict"] not in result or not item["reviewer"].strip() or not item["reason"].strip():
                raise ValueError("invalid_diagnosis_review")
            old=db.execute("SELECT * FROM diagnosis_review WHERE id=?",(item["id"],)).fetchone()
            values=(item["observation"],item["verdict"],item["at"],item["reviewer"],item["reason"])
            if old and tuple(old[k] for k in ("observation_id","verdict","reviewed_at","reviewer","reason"))!=values:
                raise ValueError("diagnosis_identity_conflict")
            if not old:
                db.execute("INSERT INTO diagnosis_review VALUES (?,?,?,?,?,?,?)",(item["id"],*values,source))
                if item.get("lab_sample"):
                    sample=db.execute("SELECT * FROM lab_sample WHERE id=?",(item["lab_sample"],)).fetchone()
                    if not sample or sample["observation_id"]!=item["observation"]:
                        raise ValueError("lab_diagnosis_basis_invalid")
                    if sample["verdict"]=="review":raise ValueError("lab_diagnosis_sample_held")
                    if sample["verdict"] not in {"positive","negative"}:
                        raise ValueError("lab_diagnosis_basis_invalid")
                    expected="confirmed" if sample["verdict"]=="positive" else "rejected"
                    if item["verdict"]!=expected:raise ValueError("lab_diagnosis_verdict_mismatch")
                    db.execute("INSERT INTO lab_diagnosis_basis VALUES (?,?)",(item["id"],item["lab_sample"]))
                result[item["verdict"]]+=1
        return result
    return ingest(path,"diagnosis",file,handler)

def dispatch_import(path,file):
    """A permitted decision is converted into accountable physical lot movement."""
    def handler(db,data,source):
        result={"dispatched":0}
        for item in data["dispatches"]:
            move=db.execute("SELECT * FROM movement_decision WHERE id=?",(item["movement"],)).fetchone()
            lot=db.execute("SELECT * FROM plant_lot WHERE id=?",(move["lot_id"],)).fetchone() if move else None
            old=db.execute("SELECT * FROM movement_dispatch WHERE id=?",(item["id"],)).fetchone()
            values=(item["movement"],item["quantity"],item["carrier"])
            if old:
                if tuple(old[k] for k in ("movement_id","quantity","carrier"))!=values:
                    raise ValueError("dispatch_identity_conflict")
                continue
            if not move or move["status"]!="allowed" or item["quantity"]<=0 or item["quantity"]>lot["quantity"] or not item["carrier"].strip():
                raise ValueError("movement_not_dispatchable")
            if db.execute("SELECT 1 FROM movement_dispatch WHERE movement_id=?",(item["movement"],)).fetchone():
                raise ValueError("movement_already_dispatched")
            db.execute("INSERT INTO movement_dispatch VALUES (?,?,?,?,?,?)",(item["id"],*values,"dispatched",source))
            result["dispatched"]+=1
        return result
    return ingest(path,"dispatch",file,handler)

def return_import(path,file):
    """A recall closes only when the full physical lot is returned under a seal."""
    def handler(db,data,source):
        result={"returned":0}
        for item in data["returns"]:
            _time(item["at"])
            dispatch=db.execute("SELECT * FROM movement_dispatch WHERE id=?",(item["dispatch"],)).fetchone()
            old=db.execute("SELECT * FROM dispatch_return WHERE id=?",(item["id"],)).fetchone()
            values=(item["dispatch"],item["quantity"],item["at"],item["seal"])
            if old:
                if tuple(old[k] for k in ("dispatch_id","quantity","returned_at","seal"))!=values:
                    raise ValueError("return_identity_conflict")
                continue
            if not dispatch or dispatch["status"]!="recall_required" or item["quantity"]!=dispatch["quantity"] or not item["seal"]:
                raise ValueError("recall_return_incomplete")
            db.execute("INSERT INTO dispatch_return VALUES (?,?,?,?,?,?)",(item["id"],*values,source))
            db.execute("UPDATE movement_dispatch SET status='returned' WHERE id=?",(item["dispatch"],))
            db.execute("UPDATE movement_decision SET status='recalled_closed',reason='physical_return_confirmed' WHERE id=?",
                       (dispatch["movement_id"],))
            db.execute("INSERT INTO movement_event(movement_id,status,reason,zone_version,source_id) "
                       "SELECT id,'recalled_closed','physical_return_confirmed',zone_version,? FROM movement_decision WHERE id=?",
                       (source,dispatch["movement_id"]))
            result["returned"]+=1
        return result
    return ingest(path,"return",file,handler)
