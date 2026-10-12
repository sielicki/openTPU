"""Read-only bounded native manifest comparison; does not qualify a theorem."""
import json
from pathlib import Path
import sys
from memory_relation import ROOT
from check_memory_expansion import PROOF,read_bounded,cut_rams,cut_fp,native_steps,bounded_context


def main():
    bounded_context()
    flat=read_bounded(PROOF.parent/'flat.json')
    cut,ram=cut_rams(flat,read_bounded(PROOF.parent/'ram_induction.json'))
    del flat,cut
    mapped=read_bounded(PROOF.parent/'mapped.json');cut_fp(mapped,ram['RMW_declaration_contracts'])
    graph,fresh=native_steps(mapped['modules']['gate']);del graph,mapped,ram
    path=ROOT/'build/sparkle/mxu-outer-memory-expansion-first/native-full-state.json'
    old=read_bounded(path)
    differences=[]
    def compare(a,b,path):
        if len(differences)>=20:return
        if type(a)is not type(b):
            differences.append({'path':path,'fresh_type':type(a).__name__,'old_type':type(b).__name__});return
        if isinstance(a,dict):
            if a.keys()!=b.keys():
                differences.append({'path':path,'fresh_only_keys':[repr(x) for x in a.keys()-b.keys()][:5],
                    'old_only_keys':[repr(x) for x in b.keys()-a.keys()][:5],
                    'fresh_key_types':sorted({type(x).__name__ for x in a}),
                    'old_key_types':sorted({type(x).__name__ for x in b})})
            for key in a.keys()&b.keys():compare(a[key],b[key],path+'/'+str(key))
        elif isinstance(a,list):
            if len(a)!=len(b):differences.append({'path':path,'fresh_len':len(a),'old_len':len(b)})
            for i,(x,y) in enumerate(zip(a,b)):compare(x,y,path+'/'+str(i))
        elif a!=b:differences.append({'path':path,'fresh':a,'old':b})
    compare(fresh,old,'')
    print(json.dumps({'status':'read_only_manifest_diagnostic','old_path':str(path),
        'differences':differences,'report_limit':20,
        'complete_JSON_roundtrip_equal':json.loads(json.dumps(fresh))==old,
        'new_theorem_proven':False},sort_keys=True))


if __name__=='__main__':main()
