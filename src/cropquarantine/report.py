import json
from .store import connect,TABLES
from .spray import evaluate_plot

def report(path):
    db=connect(path)
    try:
        data={name:[dict(row) for row in db.execute("SELECT * FROM "+name)] for name in TABLES}
        data["movement_chains"]=[dict(row) for row in db.execute("""
            SELECT m.id AS movement,m.request_at,m.status AS movement_status,m.reason,
                   l.id AS lot,l.quantity,p.id AS plot,p.crop,z.version AS zone_version,z.status AS zone_status,
                   d.id AS dispatch,d.status AS dispatch_status,s.sha AS lot_source_sha
            FROM movement_decision m JOIN plant_lot l ON l.id=m.lot_id JOIN field_plot p ON p.id=l.plot_id
            JOIN source_blob s ON s.id=l.source_id
            LEFT JOIN quarantine_zone z ON z.plot_id=p.id AND z.version=m.zone_version
            LEFT JOIN movement_dispatch d ON d.movement_id=m.id ORDER BY m.id
        """)]
        evaluations=[]
        for plot in db.execute("SELECT * FROM field_plot ORDER BY id"):
            if not db.execute("SELECT 1 FROM spray_segment WHERE plot_id=?",(plot["id"],)).fetchone():
                continue
            evaluation=evaluate_plot(db,plot)
            certs=db.execute("SELECT * FROM treatment_certificate WHERE plot_id=? ORDER BY id",(plot["id"],)).fetchall()
            evaluation["certificates"]=[]
            for cert in certs:
                followups=db.execute("SELECT kind,detail FROM certificate_followup WHERE certificate_id=? ORDER BY id",
                                     (cert["id"],)).fetchall()
                if cert["scope"]=="whole_plot":
                    printed=f"whole_plot:{plot['id']}"
                    applicable=None if cert["status"]!="issued" else {"plot_id":plot["id"],"scope":"whole_plot"}
                else:
                    covered=[p for p in evaluation["point_doses"] if p["verdict"]=="confirmed_covered"]
                    printed=f"local:{plot['id']}:diseased_points_only"
                    applicable=None if cert["status"]!="issued" else {
                        "plot_id":plot["id"],"scope":"local",
                        "observations":[p["observation_id"] for p in covered],
                        "rectangles":evaluation["scope_rectangles"]}
                evaluation["certificates"].append({
                    "id":cert["id"],"requested_at":cert["requested_at"],
                    "scope":cert["scope"],"status":cert["status"],"reason":cert["reason"],
                    "printed_scope":printed,"applicable_scope":applicable,
                    "followups":[{"kind":f["kind"],"detail":f["detail"]} for f in followups]})
            evaluations.append(evaluation)
        data["spray_evaluation"]=evaluations
        return data
    finally:db.close()

def report_json(path):
    return json.dumps(report(path),ensure_ascii=False,indent=2,default=lambda x:x.hex() if isinstance(x,bytes) else str(x))
