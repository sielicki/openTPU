"""Bounded all679D boundary/closure diagnostic; no semantic or layout proof."""
import json
import sqlite3
import sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'build/sparkle/vpu_joint_observation_draft'),str(ROOT/'build/sparkle/vpu_control_partition_draft')]
from check_sparkle_fpga_top_complete import bounded_context,require
from sparkle_provenance import ARCHIVE,sha256
from qualify_sparkle_specialization_binding import normalized_hashes,read
from observation_coordinates import Original,Gold,actual
from joint_partition import storage
from physical_frontier import layouts,external_original,classes,closure

PINS={'original':('vpu-original-control-inventory-seventh','1da5439d3020dda781bbb135be7526b5df5bc48cf82916194d9cf59afb4fea9f'),
 'joint':('vpu-joint-control-initial-fifth','3ac653cdf431115c3f6864d54772ad36b81cf9fa159ce8ab46d71eca9c3a5352')}

def pinned(p,h):
    a=ARCHIVE/h
    if not a.is_file():a=p
    require(sha256(a)==h,'Pinned artifact differs '+str(p));return a

def main():
    bounded_context();records={};maps={}
    for k,(folder,h) in PINS.items():
        records[k]=read(pinned(ROOT/'build/sparkle'/folder/'summary.json',h));maps[k]=normalized_hashes(records[k]['input_sha256'])
    def artifact(key,p):
        p=str(Path(p).resolve());require(p in maps[key],'Exact direct artifact owner absent '+p);return pinned(Path(p),maps[key][p])
    original=records['original'];joint=records['joint']
    require(original['inventory_complete']is True and joint['joint_1159_proven']is True,'Completed evidence absent')
    rtl=ROOT/'rtl/vpu/otpu_vpu.sv';require(maps['original'].get(str(rtl))==maps['joint'].get(str(rtl)) and str(rtl) in maps['original'],'Full original source identity differs')
    types=layouts(artifact('original',rtl).read_text())
    inv=read(artifact('original',original['root_inventory']))
    expected={'LANES':format(8,'032b'),'CL':format(2,'032b'),'WBUF':'1','HAS_SE':'1','SID':format(0,'032b')}
    require(inv['otpu_vpu']['evaluated_parameter_values']==expected,'Actual source specialization differs');del inv
    db=sqlite3.connect(artifact('original',original['owner_database']).as_uri()+'?mode=ro&immutable=1',uri=True);db.execute('PRAGMA query_only=ON');db.execute('PRAGMA cache_size=-8192')
    try:
        selected,qs,memwords=storage(db,read(artifact('original',original['control_candidates'])));require(len(qs)==679 and memwords=={'cq':{0,1}},'Complete selected physical/memory inventory differs')
        o=Original(db);raw=read(artifact('joint',ROOT/'build/sparkle'/PINS['joint'][0]/'none/raw.json'));m=raw['modules']['gold'];del raw;g=Gold(m)
        qd={};gowners={}
        for name,c in m['cells'].items():
            if c['type']=='$dff':
                for q,d in zip(c['connections']['Q'],c['connections']['D']):require(q not in qd,'Duplicate gold Q');qd[q]=d;gowners[q]=name
        require(len(qd)==1159,'Exact gold full Q inventory differs')
        gfields=joint['cases']['none']['inventory']['inventory']['gold']['fields'];od={};gd={};ov={};gv={};vectors=[];source_bindings={}
        for field in selected:
            if field['classification']!='physical_DFF_Q':continue
            n=field['field'];ob=field['original_bits'];gb=g.alias(n)
            require(gb==gfields[n] and len(gb)==len(ob) and set(gb)<=qd.keys(),'Actual gold field mapping differs '+n)
            od[n]=[row['d'] for row in field['actual_qd']];gd[n]=[qd[b] for b in gb]
            label='state_'+n;ov[label]=ob;gv[label]=gb;vectors.append((label,ob,gb))
        require(sum(map(len,od.values()))==sum(map(len,gd.values()))==679,'Full actual physical D coverage differs')
        require({n:len(p['bits']) for n,p in m['ports'].items() if p['direction']=='input'}==joint['inputs'],'Complete joint external input inventory differs')
        for name,width in joint['inputs'].items():
            ob,binding=external_original(name,width,o,types);gb=m['ports'][name]['bits'];label='external_'+name
            ov[label]=ob;gv[label]=gb;vectors.append((label,ob,gb));source_bindings[name]=binding
        ob=o.alias('hc');gb=g.alias('hc');require(len(ob)==len(gb)==240,'Provisional complete head width differs')
        ov['provisional_hc']=ob;gv['provisional_hc']=gb;vectors.append(('provisional_hc',ob,gb))
        relation,ocuts,gcuts=classes(o,g,vectors)
        oq={q:name for q,name in db.execute('SELECT q,cell FROM qd WHERE module="otpu_vpu"')}
        result={'status':'all_679_D_actual_boundary_closure_diagnostic_only','proof':False,'source_layout_rules':types,'external_source_bindings':source_bindings,
            'boundary_relation':relation,'original':closure(o,od,ov,ocuts,oq,o.producer),
            'gold':closure(g,gd,gv,gcuts,gowners,lambda b:g.drivers.get(b)),
            'complete_actual_physical_D_bits':679,'cq_memory_D_bits_pending':480,
            'original_owner_database_sha256':maps['original'][str(Path(original['owner_database']).resolve())],
            'original_buffer_boundary_paths':sorted(o.used),'gold_buffer_boundary_paths':sorted(g.used),
            'packed_layout_proven':False,'provider_equality_proven':False,'initialized_trace_proven':False}
        print(json.dumps(result,indent=2),flush=True)
    finally:db.close()

if __name__=='__main__':main()
