"""Rectangular spray passes, shared nozzle calibration and treatment certificates.

Dose accounting never treats boundary contact as area coverage and never uses
area outside the field plot to dilute an overdose. Segments sharing one
calibration certificate share one real multiplier interval: the interval, not
a per-segment favourable pick, is what every dose bound is derived from.
"""
from .intake import ingest
from .domain import _time

EPS=1e-9
MAX_SEGMENTS_PER_PLOT=6


# ---------------------------------------------------------------- geometry

def _clip(rect,plot):
    return (max(rect[0],plot["xmin"]),max(rect[1],plot["ymin"]),
            min(rect[2],plot["xmax"]),min(rect[3],plot["ymax"]))

def _has_interior(rect,plot):
    return (min(rect[2],plot["xmax"])>max(rect[0],plot["xmin"])+EPS
            and min(rect[3],plot["ymax"])>max(rect[1],plot["ymin"])+EPS)

def _dist_to_rect_border(px,py,rect):
    xmin,ymin,xmax,ymax=rect
    dx=max(xmin-px,0,px-xmax);dy=max(ymin-py,0,py-ymax)
    # outside: corner/edge distance; inside: distance to nearest border line
    if dx>EPS or dy>EPS:return (dx*dx+dy*dy)**0.5
    return min(abs(px-xmin),abs(px-xmax),abs(py-ymin),abs(py-ymax))

def _cell_dose(seg_ids,segments,calibrations):
    """Per-product attainable dose interval for one covered set of segments."""
    sums={}
    for sid in seg_ids:
        seg=segments[sid]
        cal=calibrations[seg["calibration_id"]]
        key=(seg["product_id"],cal["id"])
        sums.setdefault(key,0.0)
        sums[key]+=float(seg["nominal_dose"])
    out={}
    for (product,cal_id),nominal in sums.items():
        cal=calibrations[cal_id]
        lo,hi=out.get(product,(0.0,0.0))
        out[product]=(lo+nominal*cal["factor_min"],hi+nominal*cal["factor_max"])
    return out

def _build_grid(plot,segments):
    xs={plot["xmin"],plot["xmax"]};ys={plot["ymin"],plot["ymax"]}
    clipped={}
    for sid,seg in segments.items():
        rect=_clip((seg["xmin"],seg["ymin"],seg["xmax"],seg["ymax"]),plot)
        clipped[sid]=rect
        xs.update(rect[0:4:2]);ys.update(rect[1:4:2])
    xs=sorted(xs);ys=sorted(ys)
    cells=[]
    for i in range(len(xs)-1):
        for j in range(len(ys)-1):
            if xs[i+1]-xs[i]<=EPS or ys[j+1]-ys[j]<=EPS:continue
            covering=tuple(sid for sid,rect in clipped.items()
                           if rect[0]<=xs[i]+EPS and rect[2]>=xs[i+1]-EPS
                           and rect[1]<=ys[j]+EPS and rect[3]>=ys[j+1]-EPS)
            cells.append({"bounds":[xs[i],ys[j],xs[i+1],ys[j+1]],"segments":covering})
    return xs,ys,clipped,cells

def _set_on_cell(cell_bounds,clipped):
    xmin,ymin,xmax,ymax=cell_bounds
    return tuple(sid for sid,(a,b,c,d) in clipped.items()
                 if a<=xmin+EPS and c>=xmax-EPS and b<=ymin+EPS and d>=ymax-EPS)

def _set_on_vline(x,ymin,ymax,clipped):
    return tuple(sid for sid,(a,b,c,d) in clipped.items()
                 if a<x-EPS and c>x+EPS and b<=ymin+EPS and d>=ymax-EPS)

def _set_on_hline(y,xmin,xmax,clipped):
    return tuple(sid for sid,(a,b,c,d) in clipped.items()
                 if b<y-EPS and d>y+EPS and a<=xmin+EPS and c>=xmax-EPS)

def _set_on_vertex(x,y,clipped):
    return tuple(sid for sid,(a,b,c,d) in clipped.items()
                 if a<x-EPS and c>x+EPS and b<y-EPS and d>y+EPS)

def _attainable_sets(px,py,r,xs,ys,clipped):
    """All coverage sets reachable by some position inside the error disk."""
    sets=set()
    r2=r*r
    # open cells — a zero-radius point lies on no open cell
    if r>EPS:
        for i in range(len(xs)-1):
            for j in range(len(ys)-1):
                a,b,c,d=xs[i],ys[j],xs[i+1],ys[j+1]
                if c-a<=EPS or d-b<=EPS:continue
                dx=a-px if px<a else (px-c if px>c else 0.0)
                dy=b-py if py<b else (py-d if py>d else 0.0)
                if dx*dx+dy*dy<=r2+EPS:sets.add(_set_on_cell((a,b,c,d),clipped))
    # vertical grid lines (open y intervals)
    for i,x in enumerate(xs):
        if abs(x-px)>r+EPS:continue
        dx=x-px
        for j in range(len(ys)-1):
            b,d=ys[j],ys[j+1]
            if d-b<=EPS:continue
            dy=b-py if py<b else (py-d if py>d else 0.0)
            if dx*dx+dy*dy<=r2+EPS and (r>EPS or (b<py-EPS and py<d-EPS)):
                sets.add(_set_on_vline(x,b,d,clipped))
    # horizontal grid lines (open x intervals)
    for j,y in enumerate(ys):
        if abs(y-py)>r+EPS:continue
        dy=y-py
        for i in range(len(xs)-1):
            a,c=xs[i],xs[i+1]
            if c-a<=EPS:continue
            dx=a-px if px<a else (px-c if px>c else 0.0)
            if dx*dx+dy*dy<=r2+EPS and (r>EPS or (a<px-EPS and px<c-EPS)):
                sets.add(_set_on_hline(y,a,c,clipped))
    # vertices
    if r<=EPS:
        ix=[i for i,x in enumerate(xs) if abs(x-px)<=EPS]
        jy=[j for j,y in enumerate(ys) if abs(y-py)<=EPS]
        if ix and jy:
            for i in ix:
                for j in jy:sets.add(_set_on_vertex(xs[i],ys[j],clipped))
        else:
            # exact point strictly inside one open cell
            for i in range(len(xs)-1):
                for j in range(len(ys)-1):
                    if xs[i]<px-EPS and px<xs[i+1]-EPS and ys[j]<py-EPS and py<ys[j+1]-EPS:
                        sets.add(_set_on_cell((xs[i],ys[j],xs[i+1],ys[j+1]),clipped))
    else:
        for x in xs:
            for y in ys:
                if (x-px)**2+(y-py)**2<=r2+EPS:sets.add(_set_on_vertex(x,y,clipped))
    return sets

def _set_verdict(dose_bounds,products):
    if not dose_bounds:return "bad"  # bare ground: no spray reached the point
    for product,(lo,hi) in dose_bounds.items():
        window=products[product]
        if hi<window["min_dose"]-EPS or lo>window["max_dose"]+EPS:return "bad"
        if lo<window["min_dose"]-EPS or hi>window["max_dose"]+EPS:return "mixed"
    return "good"


# ---------------------------------------------------------------- evaluation

def _confirmed_positives(db,plot_id):
    points=[]
    for obs in db.execute("SELECT * FROM plant_observation WHERE plot_id=? AND status='valid' AND result='positive' ORDER BY id",
                          (plot_id,)):
        reviews=db.execute("SELECT verdict FROM diagnosis_review WHERE observation_id=? ORDER BY reviewed_at,id",
                           (obs["id"],)).fetchall()
        if reviews and reviews[-1]["verdict"]=="rejected":continue
        points.append(dict(obs))
    return points

def evaluate_plot(db,plot):
    seg_rows=db.execute("SELECT * FROM spray_segment WHERE plot_id=? ORDER BY id",(plot["id"],)).fetchall()
    segments={row["id"]:dict(row) for row in seg_rows}
    calibrations={row["id"]:dict(row) for row in
                  db.execute("SELECT * FROM spray_calibration WHERE plot_id=? ORDER BY id",(plot["id"],))}
    products={row["id"]:dict(row) for row in db.execute("SELECT * FROM treatment_product").fetchall()}
    xs,ys,clipped,cells=_build_grid(plot,segments)

    regions=[];uncovered=[]
    for cell in cells:
        bounds=cell["segments"]
        dose=_cell_dose(bounds,segments,calibrations) if bounds else {}
        level=None
        for product,(lo,hi) in dose.items():
            window=products[product]
            if lo>window["max_dose"]+EPS:level="definite";break
            if hi>window["max_dose"]+EPS:level="risk"
        entry={"bounds":cell["bounds"],"segments":list(bounds),"dose_bounds":dose,
               "area":(cell["bounds"][2]-cell["bounds"][0])*(cell["bounds"][3]-cell["bounds"][1])}
        if level:
            entry["level"]=level;regions.append(entry)
        elif not bounds:
            uncovered.append(cell["bounds"])

    point_doses=[]
    for point in _confirmed_positives(db,plot["id"]):
        px,py,r=point["x"],point["y"],point["error_radius"] or 0.0
        sets=_attainable_sets(px,py,r,xs,ys,clipped)
        verdicts=[];bounds_acc={};contacts=[]
        for seg_ids in sets:
            dose=_cell_dose(seg_ids,segments,calibrations)
            verdicts.append(_set_verdict(dose,products))
            for product,(lo,hi) in dose.items():
                if product not in bounds_acc:bounds_acc[product]=[lo,hi]
                else:bounds_acc[product]=[min(bounds_acc[product][0],lo),max(bounds_acc[product][1],hi)]
        for sid,rect in clipped.items():
            inside=rect[0]<px-EPS and px<rect[2]-EPS and rect[1]<py-EPS and py<rect[3]-EPS
            if not inside and _dist_to_rect_border(px,py,rect)<=r+EPS:contacts.append(sid)
        if verdicts and all(v=="good" for v in verdicts):verdict="confirmed_covered"
        elif verdicts and all(v=="bad" for v in verdicts):verdict="failed"
        else:verdict="review"
        point_doses.append({"observation_id":point["id"],"x":px,"y":py,"error_radius":r,
                            "verdict":verdict,
                            "dose_bounds":{k:tuple(v) for k,v in bounds_acc.items()},
                            "boundary_contact":sorted(contacts)})

    definite=[r for r in regions if r["level"]=="definite"]
    risk=[r for r in regions if r["level"]=="risk"]
    failed=[p for p in point_doses if p["verdict"]=="failed"]
    uncertain=[p for p in point_doses if p["verdict"]=="review"]

    decision=("issued",None)
    if definite:decision=("refused","overdose_limit_exceeded")
    elif risk:decision=("review","overdose_calibration_uncertain")
    elif failed:decision=("refused","point_not_covered")
    elif uncertain:decision=("review","point_coverage_uncertain")
    elif not point_doses:decision=("refused","no_confirmed_diseased_point")

    footprint=[{"segment":sid,"bounds":list(rect)} for sid,rect in sorted(clipped.items())]
    plot_area=(plot["xmax"]-plot["xmin"])*(plot["ymax"]-plot["ymin"])
    covered_area=sum((c["bounds"][2]-c["bounds"][0])*(c["bounds"][3]-c["bounds"][1]) for c in cells if c["segments"])
    return {"plot_id":plot["id"],"segments":list(segments.values()),
            "calibrations":list(calibrations.values()),
            "point_doses":point_doses,
            "overdose_regions":regions,"uncovered_cells":uncovered,
            "coverage_fraction":covered_area/plot_area if plot_area else 0.0,
            "scope_rectangles":footprint,"decision":decision}

# ---------------------------------------------------------------- imports

def spray_import(path,file):
    def handler(db,data,source):
        result={"calibrations":0,"segments":0}
        for cal in data.get("calibrations",[]):
            low,high=float(cal["factor_min"]),float(cal["factor_max"])
            _time(cal["certified_at"])
            if not 0<low<=high:raise ValueError("invalid_calibration_interval")
            plot=db.execute("SELECT * FROM field_plot WHERE id=?",(cal["plot"],)).fetchone()
            if not plot:raise ValueError("unknown_calibration_plot")
            old=db.execute("SELECT * FROM spray_calibration WHERE id=?",(cal["id"],)).fetchone()
            values=(cal["plot"],low,high,cal["certified_at"])
            if old:
                if tuple(old[k] for k in ("plot_id","factor_min","factor_max","certified_at"))!=values:
                    raise ValueError("calibration_identity_conflict")
            else:
                db.execute("INSERT INTO spray_calibration VALUES (?,?,?,?,?,?)",(cal["id"],*values,source))
                result["calibrations"]+=1
        for item in data.get("segments",[]):
            at=_time(item["at"]);dose=float(item["nominal_dose"])
            xmin,ymin,xmax,ymax=(float(item[k]) for k in ("xmin","ymin","xmax","ymax"))
            if dose<=0 or xmax<=xmin or ymax<=ymin or not str(item.get("nozzle","")).strip():
                raise ValueError("invalid_spray_segment")
            plot=db.execute("SELECT * FROM field_plot WHERE id=?",(item["plot"],)).fetchone()
            product=db.execute("SELECT * FROM treatment_product WHERE id=?",(item["product"],)).fetchone()
            cal=db.execute("SELECT * FROM spray_calibration WHERE id=?",(item["calibration"],)).fetchone()
            app=db.execute("SELECT * FROM treatment_application WHERE id=?",(item["application"],)).fetchone()
            if not plot or not product or not cal:raise ValueError("unknown_spray_basis")
            if cal["plot_id"]!=plot["id"]:raise ValueError("calibration_plot_mismatch")
            if product["crop"]!=plot["crop"]:raise ValueError("segment_product_crop_mismatch")
            if not app or app["plot_id"]!=plot["id"] or app["product_id"]!=product["id"]:
                raise ValueError("segment_application_mismatch")
            if not _has_interior((xmin,ymin,xmax,ymax),plot):raise ValueError("segment_outside_plot")
            old=db.execute("SELECT * FROM spray_segment WHERE id=?",(item["id"],)).fetchone()
            values=(item["plot"],item["application"],item["calibration"],str(item["nozzle"]),
                    item["at"],item["product"],xmin,ymin,xmax,ymax,dose)
            if old:
                if tuple(old[k] for k in ("plot_id","application_id","calibration_id","spray_nozzle",
                                           "applied_at","product_id","xmin","ymin","xmax","ymax","nominal_dose"))!=values:
                    raise ValueError("spray_segment_identity_conflict")
                continue
            count=db.execute("SELECT COUNT(*) FROM spray_segment WHERE plot_id=?",(plot["id"],)).fetchone()[0]
            if count>=MAX_SEGMENTS_PER_PLOT:raise ValueError("plot_segment_limit")
            db.execute("INSERT INTO spray_segment VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",(item["id"],*values,source))
            result["segments"]+=1
        recompute_certificates(db,source)
        return result
    return ingest(path,"spray",file,handler)


def certificate_import(path,file):
    def handler(db,data,source):
        result={"issued":0,"review":0,"refused":0}
        for item in data.get("certificates",[]):
            if item["scope"] not in {"local","whole_plot"}:raise ValueError("invalid_certificate_scope")
            _time(item["requested_at"])
            plot=db.execute("SELECT * FROM field_plot WHERE id=?",(item["plot"],)).fetchone()
            if not plot:raise ValueError("unknown_certificate_plot")
            old=db.execute("SELECT * FROM treatment_certificate WHERE id=?",(item["id"],)).fetchone()
            if old:
                if (old["plot_id"],old["scope"],old["requested_at"])!=(item["plot"],item["scope"],item["requested_at"]):
                    raise ValueError("certificate_identity_conflict")
                result[old["status"]]+=1
                continue
            evaluation=evaluate_plot(db,plot)
            base_status,base_reason=evaluation["decision"]
            if base_status!="issued":
                status,reason=base_status,base_reason
            else:
                if item["scope"]=="whole_plot" and evaluation["uncovered_cells"]:
                    status,reason="refused","plot_not_fully_covered"
                else:
                    status,reason="issued",None
            db.execute("INSERT INTO treatment_certificate VALUES (?,?,?,?,?,?,?)",
                       (item["id"],item["plot"],item["scope"],item["requested_at"],status,reason,source))
            result[status]+=1
        return result
    return ingest(path,"certificate",file,handler)


def recompute_certificates(db,source):
    """Late evidence only reopens unsigned certificates; issued ones keep their
    original evidence and, if now insufficient, gain a non-destructive follow-up."""
    certs=db.execute("SELECT * FROM treatment_certificate ORDER BY id").fetchall()
    cache={}
    for cert in certs:
        plot=db.execute("SELECT * FROM field_plot WHERE id=?",(cert["plot_id"],)).fetchone()
        if cert["plot_id"] not in cache:cache[cert["plot_id"]]=evaluate_plot(db,plot)
        evaluation=cache[cert["plot_id"]]
        base_status,base_reason=evaluation["decision"]
        status,reason=base_status,base_reason
        if base_status=="issued" and cert["scope"]=="whole_plot" and evaluation["uncovered_cells"]:
            status,reason="refused","plot_not_fully_covered"
        if cert["status"]=="issued":
            if status!="issued":
                exists=db.execute("SELECT 1 FROM certificate_followup WHERE certificate_id=? AND kind='recheck_required' AND detail=?",
                                  (cert["id"],reason)).fetchone()
                if not exists:
                    db.execute("INSERT INTO certificate_followup(certificate_id,plot_id,kind,detail,created_source) VALUES (?,?,?,?,?)",
                               (cert["id"],cert["plot_id"],"recheck_required",reason,source))
            continue
        if (cert["status"],cert["reason"])!=(status,reason):
            db.execute("UPDATE treatment_certificate SET status=?,reason=? WHERE id=?",(status,reason,cert["id"]))
