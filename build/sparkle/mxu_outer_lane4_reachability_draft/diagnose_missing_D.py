"""Read-only exact missing-D owner report from preserved incomplete inventory."""
import argparse
import json
from pathlib import Path
from sequential_inventory import ROOT,mapped_cells
from observation_queries import read
from check_observation_inventory import Evidence,normalized_hashes,bounded_context,require


def main(attempt_path,attempt_sha):
    bounded_context();ev=Evidence();attempt,_=ev.record(attempt_path,attempt_sha)
    require(attempt['certificate_kind']=='archived_lane4_sequential_dependency_inventory' and
        attempt['status']=='incomplete' and attempt['complete_dependency_inventory'] is False,'exact incomplete inventory required')
    ah=normalized_hashes(attempt['input_sha256']);ref=attempt['hazard_premise'];hp=Path(ref['path']).resolve()
    require(ah[str(hp)]==ref['sha256'],'hazard owner differs');hazard,_=ev.record(hp,ref['sha256'])
    hh=normalized_hashes(hazard['input_sha256']);ref=hazard['inventory_premise'];ip=Path(ref['path']).resolve()
    require(hh[str(ip)]==ref['sha256'],'inventory owner differs');inv,_=ev.record(ip,ref['sha256'])
    ih=normalized_hashes(inv['input_sha256'])
    def owned(path):
        path=Path(path).resolve();require(ah[str(path)]==ih[str(path)],'attempt/input graph identity differs')
        ev.direct(path,ih[str(path)]);return read(path)
    pair=owned(inv['observation_graph']['path'])['modules']['paired'];records=[]
    for side in ('gold','gate'):
        original=owned(inv['active_artifacts'][side+'-steps'])['modules'][side]
        manifest=owned(inv['active_artifacts'][side+'-full-manifest'])
        mapping=mapped_cells(original,pair,side)
        qset={r['q'] for r in manifest['full_state_coordinates']}
        require(len(qset)==len(manifest['full_state_coordinates'])==7436,'full physical state scope differs')
        for row in manifest['full_state_coordinates']:
            bit=row['d']
            if type(bit)is str or bit in mapping:continue
            aliases=[{'name':n,'bit_indices_lsb':[i for i,b in enumerate(a['bits']) if b==bit],
                'attributes':a.get('attributes',{})} for n,a in original['netnames'].items() if bit in a['bits']]
            ports=[{'name':n,'direction':p['direction'],'bit_indices_lsb':[i for i,b in enumerate(p['bits']) if b==bit]}
                for n,p in original['ports'].items() if bit in p['bits']]
            records.append({'side':side,'physical_coordinate':row,'D_is_physical_Q':bit in qset,
                'actual_source_ports':ports,'actual_source_aliases':aliases})
    ev.finish()
    print(json.dumps({'status':'complete_read_only_missing_D_inventory','count':len(records),'coordinates':records,
        'physical_scope_per_side':7436,'no_state_dropped':True,'mapping_repair_proven':False},sort_keys=True))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--attempt',type=Path,required=True);p.add_argument('--attempt-sha',required=True)
    a=p.parse_args();main(a.attempt.resolve(),a.attempt_sha)
