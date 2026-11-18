"""Synthetic staff check-ins around existing zone decisions."""
from .intake import ingest
from .domain import _time


def staff_import(path, file):
    def handler(db, data, source):
        result={"admitted":0,"held":0}
        for item in data["entries"]:
            start,end=_time(item["in_at"]),_time(item["out_at"])
            if start>=end or not item["person"] or item["purpose"] not in {"inspect","farm"}:
                raise ValueError("invalid_staff_entry")
            plot=db.execute("SELECT id FROM field_plot WHERE id=?",(item["plot"],)).fetchone()
            if not plot:raise ValueError("unknown_staff_plot")
            zone=db.execute("SELECT * FROM quarantine_zone WHERE plot_id=? AND asof<=? ORDER BY version DESC LIMIT 1",
                            (item["plot"],item["in_at"])).fetchone()
            blocked=bool(zone and zone["status"]=="active" and item["purpose"]!="inspect")
            status="held" if blocked else "admitted"
            values=(item["person"],item["plot"],item["in_at"],item["out_at"],item["purpose"],zone["version"] if zone else None,status)
            old=db.execute("SELECT * FROM staff_entry WHERE id=?",(item["id"],)).fetchone()
            if old:
                if tuple(old[k] for k in ("person","plot_id","in_at","out_at","purpose","zone_version","status"))!=values:
                    raise ValueError("staff_entry_identity_conflict")
                continue
            db.execute("INSERT INTO staff_entry VALUES (?,?,?,?,?,?,?,?,?)",(item["id"],*values,source))
            result[status]+=1
        return result
    return ingest(path,"staff",file,handler)
