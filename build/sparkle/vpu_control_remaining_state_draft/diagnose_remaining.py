"""Bounded complete remaining3072 coordinate/access diagnostic; no proof promotion."""
import json
import sqlite3
import sys
from pathlib import Path
ROOT = next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0] = [str(ROOT/'tools')] + [str(ROOT/'build/sparkle'/d) for d in
    ('vpu_control_partition_draft','vpu_joint_physical_proof_draft')]
from check_sparkle_fpga_top_complete import bounded_context
from sparkle_provenance import ARCHIVE, sha256
from qualify_sparkle_specialization_binding import normalized_hashes, read
from joint_partition import owner, storage
from remaining_state import unit_inventory, require

PINS = {
 'issue':('vpu-issue-bridge-second','c40c214b3e6f724c858c2365464c809ea8dd2a7bde46d7946ce35b2779b5dac7'),
 'original':('vpu-original-control-inventory-seventh','1da5439d3020dda781bbb135be7526b5df5bc48cf82916194d9cf59afb4fea9f'),
 'binding':('vpu-control-initial-binding-second','704555cc3e0c7c5c526ef1f7de7f3fc52b025d9e48396c9f7e85b215e48cb1c8'),
 'stream':('vpu-stream-initial-third','0c70d73921cff4d2d6064d7244b3f3181dd43c671601e09f42f51a3fbdb23cea'),
 'write_buffer':('vpu-write-buffer-initial-first','596c10b7e574167bf708e8dc6a30f2992e1ef8724d695794c056892f85016f07')}


def pinned(path, digest):
    candidate = ARCHIVE/digest
    if not candidate.is_file(): candidate = Path(path)
    require(sha256(candidate) == digest, 'Authenticated artifact differs '+str(path))
    return candidate


def join(maps, parent, child):
    folder,digest = PINS[child]
    require(maps[parent].get(str(ROOT/'build/sparkle'/folder/'summary.json')) == digest,
            'Exact receipt owner join differs '+parent+' -> '+child)


def complete_union(units, qs, memwords, db):
    coordinates = {('Q',q) for q in qs}
    for memory,words in memwords.items():
        width = owner(db,'memories',memory)['width']
        coordinates.update(('memory',memory,w,i) for w in words for i in range(width))
    require(len(coordinates) == 1159, 'Prior complete1159 coordinates differ')
    for result in units.values():
        for field in result['fields'].values():
            added = ({('Q',q) for q in field['original_bits']} if field['classification']=='physical_DFF_Q'
                     else {('memory',field['memory'],field['word'],i) for i in range(field['logical_width'])})
            require(not coordinates & added, 'Cross-unit state owner overlap')
            coordinates.update(added)
    require(len(coordinates) == 4231, 'Complete4231 coordinate union differs')
    return {'logical_bits':len(coordinates), 'physical_Q_bits':sum(c[0]=='Q' for c in coordinates),
            'memory_bits':sum(c[0]=='memory' for c in coordinates), 'state_semantic_relation_proven':False}


def main():
    bounded_context(); records = {}; maps = {}
    for key,(folder,digest) in PINS.items():
        records[key] = read(pinned(ROOT/'build/sparkle'/folder/'summary.json',digest))
        maps[key] = normalized_hashes(records[key]['input_sha256'])
    for parent,child in (('issue','original'),('issue','binding'),('binding','stream'),('binding','write_buffer')):
        join(maps,parent,child)
    require(records['issue']['status']=='actual_root_native_issue555_and27_internal_premises_proven' and
            records['binding']['local_contracts_bound'] is True and records['original']['inventory_complete'] is True,
            'Completed owner evidence absent')
    def artifact(key,path):
        path = str(Path(path).resolve()); require(path in maps[key], 'Exact direct artifact absent '+path)
        return pinned(path,maps[key][path])
    rtl = str(ROOT/'rtl/vpu/otpu_vpu.sv')
    require(rtl in maps['original'] and all(maps[k].get(rtl)==maps['original'][rtl] for k in ('stream','write_buffer')),
            'Original source definitions disagree')
    candidates = read(artifact('original',records['original']['control_candidates']))
    db = sqlite3.connect(artifact('original',records['original']['owner_database']).as_uri()+'?mode=ro&immutable=1',uri=True)
    db.execute('PRAGMA query_only=ON'); db.execute('PRAGMA cache_size=-8192')
    try:
        _,qs,memwords = storage(db,candidates); units = {}
        for unit in ('stream','write_buffer'):
            raw = read(artifact(unit,ROOT/'build/sparkle'/PINS[unit][0]/'none/raw.json'))
            units[unit] = unit_inventory(db,candidates,unit,raw,records[unit]); del raw
        union = complete_union(units,qs,memwords,db)
        providers = {}
        for signal,unit,field in (('en','write_buffer','en_r'),('ss_rq','stream','ss_rq')):
            row = units[unit]['fields'][field]
            providers[signal] = {'actual_state_field':row,'actual_signal_alias':owner(db,'netnames',signal),
                                 'raw_alias_linkage_proven':False,'original_native_provider_equality_proven':False}
        child = owner(db,'cells','g_comp.u_comp')
        require(child['type']=='otpu_se_comp' and child['port_directions']['hold']=='output' and len(child['connections']['hold'])==1,
                'Actual composite hold edge differs')
        print(json.dumps({'status':'complete_remaining3072_coordinate_access_diagnostic_only','proof':False,
            'receipt_pins':PINS,'units':units,'complete_original_union':union,'remaining_internal_providers':providers,
            'c_hold':{'actual_child':child,'actual_alias':owner(db,'netnames','c_hold'),'producer_equality_proven':False},
            'full_control_transition_proven':False,'layout_proven':False,'initial_witness_proven':False},indent=2),flush=True)
    finally: db.close()


if __name__=='__main__': main()
