"""Bounded actual write-select coordinates/frontier; no equivalence claim."""
import json,sqlite3,sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle'/d) for d in ('vpu_control_closure_draft','vpu_joint_cq_memory_draft','vpu_control_comb_draft','vpu_joint_initialized_composition_draft')]
import check_issue_bridge
from check_sparkle_fpga_top_complete import bounded_context
from qualify_sparkle_specialization_binding import read,normalized_hashes
from sparkle_provenance import ARCHIVE,sha256
from physical_slices import require
from write_select_boundary import boundary,closure

PINS={
 'providers':('vpu-control-provider-closure-second','b61359382979c221be0ef0cd959ffeb3dd5ddf1bdfbeb389038584e94953a7f8'),
 'startup':('vpu-full-initial-product-second','3c14f3877198ab025d26968440753e9b0cff4f28aadfb699556e7a49c09c6d75'),
 'original':('vpu-original-control-inventory-seventh','1da5439d3020dda781bbb135be7526b5df5bc48cf82916194d9cf59afb4fea9f'),
 'joint':('vpu-joint-control-initial-fifth','3ac653cdf431115c3f6864d54772ad36b81cf9fa159ce8ab46d71eca9c3a5352'),
 'writer':('vpu-write-root-bridge-first','9e0e69f6801292a4ada5d24d127d4b74c8bdbe7af613491d2b24b4d6c33d650b'),
 'comb':('vpu-control-comb-third','7271adaaafc7d1b53c1a4c1aa969a046d8efe1f369a465f5994805b8a76e1203')}


def main():
    bounded_context();records={};maps={};consumed={}
    def pin(p,h):
        p=Path(p).resolve();a=ARCHIVE/h
        if not a.is_file():a=p
        require(sha256(a)==h,'Immutable artifact differs '+str(p));consumed[str(p)]=h;return a
    for key,(folder,h) in PINS.items():
        records[key]=read(pin(ROOT/'build/sparkle'/folder/'summary.json',h));maps[key]=normalized_hashes(records[key]['input_sha256'])
    for key in PINS:
        if key!='providers':
            folder,h=PINS[key];require(maps['providers'].get(str(ROOT/'build/sparkle'/folder/'summary.json'))==h,'Explicit inventory receipt join differs')
    require(records['providers']['inventory_complete'] and records['startup']['full_4231_initial_predicate_compatibility_proven'] and records['writer']['actual_write_1722_D_outputs_proven'] and records['comb']['local_combinational_proven'],'Completed prerequisites missing')
    def artifact(key,p):
        p=str(Path(p).resolve());require(p in maps[key],'Exact direct artifact owner missing');return pin(p,maps[key][p])
    def obj(key,name):return read(artifact(key,ROOT/'build/sparkle'/PINS[key][0]/name))
    rtl=ROOT/'rtl/vpu/otpu_vpu.sv';require(maps['original'].get(str(rtl)) is not None and maps['original'][str(rtl)]==maps['comb'].get(str(rtl)),'Original source reconstruction identity differs')
    raw=obj('comb','write_select/none/raw.json');require(set(raw['modules'])=={'gold','gate'},'Complete raw module inventory differs');native=raw['modules']['gate'];del raw
    db=sqlite3.connect(artifact('original',records['original']['owner_database']).as_uri()+'?mode=ro&immutable=1',uri=True)
    db.execute('PRAGMA query_only=ON');db.execute('PRAGMA cache_size=-8192')
    try:
        b=boundary(db,native,artifact('original',rtl).read_text(),obj('providers','provider-consumer-coordinates.json'),obj('startup','initial-predicate-certificate.json'),records['joint'],obj('writer','complete-logical-obligations.json'))
        report={k:b[k] for k in ('relation','manifest','input_audit','output_audit','internal91','writer424','packed_source_rules')}
        report.update(status='actual_write_select_mapping_frontier_diagnostic_only',proof=False,layout_proven=False,production_applicability_proven=False,
            providers_discharged=False,closure=closure(b),receipt_pins=PINS,input_sha256=consumed)
        print(json.dumps(report,indent=2),flush=True)
    finally:db.close()

if __name__=='__main__':main()
