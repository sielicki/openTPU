"""Bounded read-only exact original public-observation schema probe, no proof."""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import bounded_context,require
from sparkle_provenance import ARCHIVE,sha256
from qualify_sparkle_specialization_binding import read,normalized_hashes

OWNER=ROOT/'build/sparkle/vpu-original-control-inventory-seventh/summary.json'
PIN='1da5439d3020dda781bbb135be7526b5df5bc48cf82916194d9cf59afb4fea9f'
JOINT=ROOT/'build/sparkle/vpu-joint-control-initial-fifth/summary.json'
JOINT_PIN='3ac653cdf431115c3f6864d54772ad36b81cf9fa159ce8ab46d71eca9c3a5352'

def pinned(p,h):
    candidate=ARCHIVE/h
    if not candidate.is_file():candidate=p
    require(sha256(candidate)==h,'Pinned input changed '+str(p));return candidate

def main():
    bounded_context();r=read(pinned(OWNER,PIN));joint=read(pinned(JOINT,JOINT_PIN));hm=normalized_hashes(r['input_sha256'])
    require(r['inventory_complete']is True and joint['joint_1159_proven']is True,'Completed owners required')
    path=str(Path(r['owner_database']).resolve());require(path in hm,'No direct owner for SQLite')
    db=sqlite3.connect(pinned(Path(path),hm[path]).as_uri()+'?mode=ro&immutable=1',uri=True);db.execute('PRAGMA cache_size=-8192');db.execute('PRAGMA query_only=ON')
    try:
        result={'status':'observation_schema_probe_only','proof':False,'owner_database_sha256':hm[path],'outputs':joint['outputs'],'aliases':{},'geometry_aliases':[]}
        aliases={n.removeprefix('out_sequence_o_') for n in joint['outputs'] if n.startswith('out_sequence_o_')}|{'hc','hf','h_empty','can_begin','busy','rdy','cq_n','en','nfill'}
        for alias in sorted(aliases):
            row=db.execute('SELECT sha,payload FROM owners WHERE module="otpu_vpu" AND section="netnames" AND name=?',(alias,)).fetchone()
            if row is None:result['aliases'][alias]={'missing':True};continue
            require(hashlib.sha256(row[1].encode()).hexdigest()==row[0],'Owner checksum differs');value=json.loads(row[1]);bits=value['bits']
            drivers=[]
            for b in bits:
                if type(b)is int:
                    d=db.execute('SELECT owner,pin FROM drivers WHERE module="otpu_vpu" AND bit=?',(b,)).fetchone()
                    if d and list(d) not in drivers:drivers.append(list(d))
            result['aliases'][alias]={'owner':value,'drivers':drivers}
        for name,payload in db.execute('SELECT name,payload FROM owners WHERE module="otpu_vpu" AND section="netnames" AND (name LIKE "%nchunks%" OR name LIKE "%c16%" OR name LIKE "%begin_cmd%") ORDER BY name'):
            value=json.loads(payload);result['geometry_aliases'].append({'name':name,'owner':value})
        print(json.dumps(result,indent=2),flush=True)
    finally:db.close()

if __name__=='__main__':main()
