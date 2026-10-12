"""Read-only authenticated dot/epilogue valid-state schema, no composition claim."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'build/sparkle/mxu_outer_observations_draft'),
             str(ROOT/'build/sparkle/mxu_dot_composition_draft')]
from check_observation_inventory import Evidence,normalized_hashes,bounded_context,require
from audit_sparkle_rtlil_roundtrip import Owners
from check_dot_definedness import LOCAL,LOCAL_SHA

EP=ROOT/'build/sparkle/mxu_epilogue_product/attempt1/summary.json'
EP_SHA='6d3cc7e333d7ddf9a186140c78a1604f2c31ffd409f879937a1705f397fefc18'
DOT=ROOT/'build/sparkle/mxu-dot-initialized-composition-first/summary.json'
DOT_SHA='fb82976be4f1a441fde64a70ab8e826400bd03ab8754de33b0afd9013ab6c0fe'


def schema(path):
    result={}
    with path.open() as stream:
        reader=Owners(stream)
        for top in reader.object():
            if top!='modules':reader.value();continue
            for module in reader.object():
                require(module not in result,'duplicate module');ports={};aliases={};types=Counter();init_aliases=0
                for kind in reader.object():
                    if kind not in ('ports','netnames','cells'):reader.value();continue
                    seen=set()
                    for name in reader.object():
                        require(name not in seen,'duplicate owner');seen.add(name);value=reader.value()
                        if kind=='ports':ports[name]=value
                        elif kind=='cells':types[value['type']]+=1
                        else:
                            init_aliases+=int('init' in value.get('attributes',{}))
                            if re.search(r'(^|[.])(?:meta[0-9_]*|u_m4(?:[.]|$)|m[0456]|m[atqx]|launch|lv2|lv_[0-9]+|u_lv(?:[.]|$)|mtp[0-9]*|mqp[0-9]*)',name):
                                aliases[name]=value
                state={n:p for n,p in ports.items() if n.startswith(('state_','next_'))}
                wanted={b for v in aliases.values() for b in v['bits'] if type(b)is int}
                related={n:{'direction':p['direction'],'width':len(p['bits']),
                    'related_coordinates':[{'index_lsb':i,'bit':b} for i,b in enumerate(p['bits']) if b in wanted]}
                    for n,p in state.items() if any(b in wanted for b in p['bits'])}
                result[module]={'public_ports':{n:{'direction':p['direction'],'width':len(p['bits']),
                    **({'bits':p['bits']} if n in ('clk','rst','en_c','m0','m4','pr0','lv2') else {})}
                    for n,p in ports.items() if n not in state},
                    'state_port_count':len(state),'state_input_bits':sum(len(p['bits']) for p in state.values() if p['direction']=='input'),
                    'metadata_aliases':aliases,'related_state_ports':related,'cell_types':dict(types),'init_alias_count':init_aliases}
        reader.whitespace();require(reader.eof and reader.pos==len(reader.buf),'trailing JSON content')
    return result


def main():
    bounded_context();ev=Evidence();dot,_=ev.record(DOT,DOT_SHA);ep,_=ev.record(EP,EP_SHA)
    require(dot['initialized_dot_proven'] is True and dot['status']=='initialized_physical_dot_trace_refinement_certified','dot incomplete')
    require(ep['status']=='passed' and ep['state_bits_per_design']==8197,'epilogue incomplete')
    dh=normalized_hashes(dot['input_sha256']);eh=normalized_hashes(ep['input_sha256'])
    require(dh[str(LOCAL)]==LOCAL_SHA,'local dot owner differs');local,_=ev.record(LOCAL,LOCAL_SHA)
    ref=local['parent_transition_receipt'];pp=Path(ref['summary']).resolve()
    require(dh[str(pp)]==ref['sha256'],'dot parent owner differs');parent,_=ev.record(pp,ref['sha256']);ph=normalized_hashes(parent['input_sha256'])
    records=[]
    for kind,paths,hashes in [('epilogue',[EP.parent/'none/raw.json',EP.parent/'none/steps.json'],eh),
                              ('dot',[pp.parent/'steps.json',pp.parent/'gold.json',pp.parent/'gate.json'],ph)]:
        for path in paths:
            require(path.is_absolute(),'artifact path not absolute');digest=hashes[str(path)]
            if kind=='dot':require(dh[str(path)]==digest,'dot composition graph owner differs')
            ev.direct(path,digest);records.append({'kind':kind,'path':str(path),'sha256':digest,'schema':schema(path)})
    ev.finish()
    print(json.dumps({'status':'complete_read_only_child_valid_schema','records':records,
        'epilogue_receipt_sha256':EP_SHA,'dot_receipt_sha256':DOT_SHA,'feedback_composition_proven':False},sort_keys=True))

if __name__=='__main__':
    argparse.ArgumentParser().parse_args();main()
