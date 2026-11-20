import sqlite3
from pathlib import Path
SCHEMA="""
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS source_blob(id INTEGER PRIMARY KEY,kind TEXT,sha TEXT,raw BLOB,result TEXT,UNIQUE(kind,sha));
CREATE TABLE IF NOT EXISTS source_failure(id INTEGER PRIMARY KEY,kind TEXT,sha TEXT,raw BLOB,error TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS field_plot(id TEXT PRIMARY KEY,xmin REAL,ymin REAL,xmax REAL,ymax REAL,crop TEXT,source_id INTEGER REFERENCES source_blob(id));
CREATE TABLE IF NOT EXISTS plant_observation(id TEXT PRIMARY KEY,plot_id TEXT REFERENCES field_plot(id),x REAL,y REAL,observed_at TEXT,result TEXT,status TEXT,source_id INTEGER REFERENCES source_blob(id));
CREATE TABLE IF NOT EXISTS diagnosis_review(id TEXT PRIMARY KEY,observation_id TEXT REFERENCES plant_observation(id),verdict TEXT,reviewed_at TEXT,reviewer TEXT,reason TEXT,source_id INTEGER REFERENCES source_blob(id));
CREATE TABLE IF NOT EXISTS quarantine_zone(id INTEGER PRIMARY KEY,plot_id TEXT REFERENCES field_plot(id),version INTEGER,asof TEXT,radius REAL,status TEXT,reason TEXT,source_id INTEGER REFERENCES source_blob(id),UNIQUE(plot_id,version));
CREATE TABLE IF NOT EXISTS reinspection(id TEXT PRIMARY KEY,plot_id TEXT REFERENCES field_plot(id),observed_at TEXT,result TEXT,source_id INTEGER REFERENCES source_blob(id));
CREATE TABLE IF NOT EXISTS plant_lot(id TEXT PRIMARY KEY,plot_id TEXT REFERENCES field_plot(id),quantity INTEGER,source_id INTEGER REFERENCES source_blob(id));
CREATE TABLE IF NOT EXISTS movement_decision(id TEXT PRIMARY KEY,lot_id TEXT REFERENCES plant_lot(id),request_at TEXT,status TEXT,reason TEXT,zone_version INTEGER,source_id INTEGER REFERENCES source_blob(id));
CREATE TABLE IF NOT EXISTS movement_event(id INTEGER PRIMARY KEY,movement_id TEXT REFERENCES movement_decision(id),status TEXT,reason TEXT,zone_version INTEGER,source_id INTEGER REFERENCES source_blob(id));
CREATE TABLE IF NOT EXISTS movement_dispatch(id TEXT PRIMARY KEY,movement_id TEXT REFERENCES movement_decision(id),quantity INTEGER,carrier TEXT,status TEXT,source_id INTEGER REFERENCES source_blob(id));
CREATE TABLE IF NOT EXISTS dispatch_return(id TEXT PRIMARY KEY,dispatch_id TEXT REFERENCES movement_dispatch(id),quantity INTEGER,returned_at TEXT,seal TEXT,source_id INTEGER REFERENCES source_blob(id));
CREATE TABLE IF NOT EXISTS lab_run(id TEXT PRIMARY KEY,run_at TEXT,negative_control REAL,positive_control REAL,status TEXT,source_id INTEGER REFERENCES source_blob(id));
CREATE TABLE IF NOT EXISTS lab_sample(id TEXT PRIMARY KEY,run_id TEXT REFERENCES lab_run(id),observation_id TEXT REFERENCES plant_observation(id),signal REAL,verdict TEXT,source_id INTEGER REFERENCES source_blob(id));
CREATE TABLE IF NOT EXISTS lab_well(id TEXT PRIMARY KEY,run_id TEXT REFERENCES lab_run(id),position INTEGER,role TEXT,raw REAL,tip_action TEXT,sample_id TEXT,observation_id TEXT,true_min REAL,true_max REAL,source_id INTEGER REFERENCES source_blob(id),UNIQUE(run_id,position));
CREATE TABLE IF NOT EXISTS lab_run_coefficient(run_id TEXT PRIMARY KEY REFERENCES lab_run(id),issued_min REAL,issued_max REAL,feasible_spans TEXT,status TEXT,source_id INTEGER REFERENCES source_blob(id));
CREATE TABLE IF NOT EXISTS lab_diagnosis_basis(review_id TEXT PRIMARY KEY REFERENCES diagnosis_review(id),sample_id TEXT REFERENCES lab_sample(id));
CREATE TABLE IF NOT EXISTS treatment_product(id TEXT PRIMARY KEY,crop TEXT,min_dose REAL,max_dose REAL,source_id INTEGER REFERENCES source_blob(id));
CREATE TABLE IF NOT EXISTS treatment_application(id TEXT PRIMARY KEY,plot_id TEXT REFERENCES field_plot(id),product_id TEXT REFERENCES treatment_product(id),applied_at TEXT,area_fraction REAL,dose REAL,status TEXT,source_id INTEGER REFERENCES source_blob(id));
CREATE TABLE IF NOT EXISTS staff_entry(id TEXT PRIMARY KEY,person TEXT,plot_id TEXT REFERENCES field_plot(id),in_at TEXT,out_at TEXT,purpose TEXT,zone_version INTEGER,status TEXT,source_id INTEGER REFERENCES source_blob(id));
"""
TABLES=["source_blob","field_plot","plant_observation","diagnosis_review","quarantine_zone","reinspection","plant_lot","movement_decision","movement_event","movement_dispatch","dispatch_return"]
TABLES.insert(1,"source_failure")
TABLES.extend(["lab_run","lab_sample","lab_well","lab_run_coefficient","lab_diagnosis_basis","treatment_product","treatment_application","staff_entry"])
def connect(path):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(p);db.row_factory=sqlite3.Row;db.executescript(SCHEMA);return db
