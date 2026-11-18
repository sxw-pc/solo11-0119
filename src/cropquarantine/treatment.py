"""Synthetic field treatment evidence, independent of zone or movement status."""
from .intake import ingest
from .domain import _time


def treatment_import(path, file):
    def handler(db, data, source):
        result={"applied":0,"held":0}
        for product in data["products"]:
            low,high=float(product["min_dose"]),float(product["max_dose"])
            if low<=0 or high<low or not product["crop"]:raise ValueError("invalid_treatment_product")
            old=db.execute("SELECT * FROM treatment_product WHERE id=?",(product["id"],)).fetchone()
            values=(product["crop"],low,high)
            if old:
                if tuple(old[k] for k in ("crop","min_dose","max_dose"))!=values:
                    raise ValueError("treatment_product_conflict")
            else:db.execute("INSERT INTO treatment_product VALUES (?,?,?,?,?)",(product["id"],*values,source))
        for item in data["applications"]:
            at=_time(item["at"])
            fraction,dose=float(item["area_fraction"]),float(item["dose"])
            if not 0<fraction<=1 or dose<=0:raise ValueError("invalid_treatment_amount")
            plot=db.execute("SELECT * FROM field_plot WHERE id=?",(item["plot"],)).fetchone()
            product=db.execute("SELECT * FROM treatment_product WHERE id=?",(item["product"],)).fetchone()
            if not plot or not product:raise ValueError("unknown_treatment_basis")
            affected=db.execute("SELECT observed_at FROM plant_observation WHERE plot_id=? AND status='valid' AND result='positive'",(item["plot"],)).fetchall()
            has_positive=any(_time(x["observed_at"])<=at for x in affected)
            status="applied" if product["crop"]==plot["crop"] and product["min_dose"]<=dose<=product["max_dose"] and has_positive else "held"
            values=(item["plot"],item["product"],item["at"],fraction,dose,status)
            old=db.execute("SELECT * FROM treatment_application WHERE id=?",(item["id"],)).fetchone()
            if old:
                if tuple(old[k] for k in ("plot_id","product_id","applied_at","area_fraction","dose","status"))!=values:
                    raise ValueError("treatment_application_conflict")
                continue
            db.execute("INSERT INTO treatment_application VALUES (?,?,?,?,?,?,?,?)",(item["id"],*values,source))
            result[status]+=1
        return result
    return ingest(path,"treatment",file,handler)
