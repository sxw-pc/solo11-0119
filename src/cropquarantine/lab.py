"""Offline sample runs with explicit controls and observation identity."""
from .intake import ingest
from .domain import _time


def lab_import(path, file):
    def handler(db, data, source):
        counts={"runs":0,"trusted_samples":0,"untrusted_samples":0}
        for run in data["runs"]:
            _time(run["at"])
            negative,positive=float(run["negative_control"]),float(run["positive_control"])
            if not 0<=negative<=1 or not 0<=positive<=1:raise ValueError("invalid_lab_control")
            status="trusted" if negative<0.2 and positive>=0.8 else "untrusted"
            values=(run["at"],negative,positive,status)
            old=db.execute("SELECT * FROM lab_run WHERE id=?",(run["id"],)).fetchone()
            if old:
                if tuple(old[k] for k in ("run_at","negative_control","positive_control","status"))!=values:
                    raise ValueError("lab_run_identity_conflict")
            else:
                db.execute("INSERT INTO lab_run VALUES (?,?,?,?,?,?)",(run["id"],*values,source))
                counts["runs"]+=1
        for sample in data["samples"]:
            signal=float(sample["signal"])
            if not 0<=signal<=1:raise ValueError("invalid_lab_signal")
            run=db.execute("SELECT * FROM lab_run WHERE id=?",(sample["run"],)).fetchone()
            obs=db.execute("SELECT * FROM plant_observation WHERE id=?",(sample["observation"],)).fetchone()
            if not run or not obs or obs["status"]!="valid" or _time(run["run_at"])<_time(obs["observed_at"]):
                raise ValueError("invalid_lab_sample_basis")
            verdict=("untrusted" if run["status"]!="trusted" else "positive" if signal>=0.5 else "negative")
            values=(sample["run"],sample["observation"],signal,verdict)
            old=db.execute("SELECT * FROM lab_sample WHERE id=?",(sample["id"],)).fetchone()
            if old:
                if tuple(old[k] for k in ("run_id","observation_id","signal","verdict"))!=values:
                    raise ValueError("lab_sample_identity_conflict")
                continue
            db.execute("INSERT INTO lab_sample VALUES (?,?,?,?,?,?)",(sample["id"],*values,source))
            counts["trusted_samples" if verdict!="untrusted" else "untrusted_samples"]+=1
        return counts
    return ingest(path,"lab",file,handler)
