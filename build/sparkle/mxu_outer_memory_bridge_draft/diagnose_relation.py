"""Read-only complete retained relation serialization diagnostic."""
import json
from pathlib import Path
from memory_relation import ROOT
from check_memory_expansion import (PROOF,OWNERSHIP,read_bounded,cut_rams,cut_fp,
    native_steps,expand,coordinates,bounded_context)


def main():
    bounded_context()
    flat=read_bounded(PROOF.parent/'flat.json')
    cut,ram=cut_rams(flat,read_bounded(PROOF.parent/'ram_induction.json'));del flat
    cut_fp(cut,ram['RMW_declaration_contracts'])
    gold,gm,bootstrap,bm=expand(cut['modules']['gold']);del gold,bootstrap,bm
    mapped=read_bounded(PROOF.parent/'mapped.json');cut_fp(mapped,ram['RMW_declaration_contracts'])
    gate,nm=native_steps(mapped['modules']['gate']);del gate,ram
    own=read_bounded(OWNERSHIP)
    lowered=read_bounded(Path(own['original_to_mapped_initial_ownership']['path']))
    retained=read_bounded(Path(own['retained_initialization']['path']))
    fresh=coordinates(cut['modules']['gold'],mapped['modules']['gold'],gm,nm,lowered['gold'],retained)
    path=ROOT/'build/sparkle/mxu-outer-memory-expansion-first/retained-relation.json';old=read_bounded(path)
    differences=[]
    for key in fresh.keys()|old.keys():
        if key not in fresh or key not in old:differences.append({'field':key,'missing':True});continue
        if fresh[key]==old[key]:continue
        row={'field':key,'fresh_type':type(fresh[key]).__name__,'old_type':type(old[key]).__name__}
        if isinstance(fresh[key],dict) and isinstance(old[key],dict):
            row.update(fresh_key_types=sorted({type(k).__name__ for k in fresh[key]}),
                old_key_types=sorted({type(k).__name__ for k in old[key]}),fresh_count=len(fresh[key]),old_count=len(old[key]))
        row['complete_JSON_roundtrip_equal']=json.loads(json.dumps(fresh[key]))==old[key]
        differences.append(row)
    print(json.dumps({'status':'read_only_relation_diagnostic','old_path':str(path),
        'differences':differences,'complete_JSON_roundtrip_equal':json.loads(json.dumps(fresh))==old,
        'new_theorem_proven':False},sort_keys=True))


if __name__=='__main__':main()
