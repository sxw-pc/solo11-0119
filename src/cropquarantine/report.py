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
        return data
    finally:db.close()

def report_json(path):
    return json.dumps(report(path),ensure_ascii=False,indent=2,default=lambda x:x.hex() if isinstance(x,bytes) else str(x))
