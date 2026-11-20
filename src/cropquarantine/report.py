import json
from .store import connect,TABLES

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
        data["lab_plate"]=[dict(row) for row in db.execute("""
            SELECT w.run_id,w.id AS well,w.position,w.role,w.raw,w.tip_action,
                   w.true_min,w.true_max,w.sample_id,w.observation_id,
                   s.verdict AS sample_verdict,
                   CASE WHEN w.sample_id IS NULL THEN 'not_applicable'
                        WHEN r.id IS NULL THEN 'not_cited'
                        WHEN r.verdict='confirmed' THEN 'cited_confirmed'
                        ELSE 'cited_rejected' END AS diagnosis_citation
            FROM lab_well w
            LEFT JOIN lab_sample s ON s.id=w.sample_id
            LEFT JOIN diagnosis_review r ON r.id=(
                SELECT b.review_id FROM lab_diagnosis_basis b
                JOIN diagnosis_review d ON d.id=b.review_id
                WHERE b.sample_id=w.sample_id ORDER BY d.reviewed_at DESC,d.id DESC LIMIT 1)
            ORDER BY w.run_id,w.position
        """)]
        return data
    finally:db.close()

def report_json(path):
    return json.dumps(report(path),ensure_ascii=False,indent=2,default=lambda x:x.hex() if isinstance(x,bytes) else str(x))
