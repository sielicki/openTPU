"""Resume production RAM inventory from an authenticated immutable extraction."""
import argparse
import json
from pathlib import Path
import re
from audit_sparkle_rtlil_roundtrip import Owners
from collect_sparkle_native_dram_production import require, save, snapshot, verify, inventory
from check_sparkle_fpga_top_complete import bounded_context
from sparkle_provenance import verify as resolve_archived


def read_inventory(path):
    result={'modules':{}}
    counts={}
    with path.open() as source:
        parser=Owners(source,limit=4*1024*1024)
        top=set()
        for field in parser.object():
            require(field not in top,'Duplicate top field');top.add(field)
            if field != 'modules': parser.value(); continue
            for name in parser.object():
                require(name not in result['modules'],'Duplicate module')
                module={'cells':{},'netnames':{},'ports':{}}
                result['modules'][name]=module; counts[name]=0
                sections=set()
                for section in parser.object():
                    require(section not in sections,'Duplicate module section'); sections.add(section)
                    if section not in ('cells','netnames','ports'):
                        parser.value(); continue
                    seen=set()
                    for owner in parser.object():
                        require(owner not in seen,'Duplicate owner'); seen.add(owner)
                        value=parser.value()
                        if section=='cells':
                            counts[name]+=1
                            if value['type'].startswith('$mem'): module['cells'][owner]=value
                        elif section=='ports': module['ports'][owner]=value
                        elif re.fullmatch(r'wh_[fn](?:[01]|\[[01]\])?',owner):
                            module['netnames'][owner]=value
        parser.whitespace()
        require(parser.eof and parser.pos==len(parser.buf),'Trailing JSON content')
    # Slang packs ascending unpacked [2] arrays with element zero high.
    gold=result['modules']['gold']['netnames']
    for base in ('wh_f','wh_n'):
        if base in gold:
            bits=gold[base]['bits']
            require(len(bits)==12,'Unexpected packed hazard read aliases')
            for channel in range(2):
                alias=f'{base}[{channel}]'
                require(alias not in gold,'Ambiguous packed/unpacked read alias')
                gold[alias]={'bits':bits[(1-channel)*6:(2-channel)*6]}
    details=inventory(result)
    details['cell_counts']=counts
    details['transport']='Bounded 4 MiB owner parser; full original artifact retained, not transformed'
    return details


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('extraction',type=Path);p.add_argument('work',type=Path)
    a=p.parse_args(); bounded_context()
    require(not a.work.exists(),'Fresh inventory directory required');a.work.mkdir(parents=True)
    summary={'status':'incomplete','phase':'inventory','scope':'No equivalence proof claimed'}
    save(a.work/'summary.json',summary)
    try:
        record=json.loads((a.extraction/'summary.json').read_text())
        # All original source, executable, generated source and extraction inputs
        # must still match their archived hashes before this continuation.
        summary['historical_inputs']=resolve_archived(record['input_sha256'])
        for key in ['frontend_plugins','generation_sha256','extraction_input_sha256','collected_sha256']:
            verify(record[key])
        runner=json.loads((a.extraction/'Emit.runner.json').read_text())
        verify(runner['source_sha256']);verify(runner['linked_sha256'])
        paths=[a.extraction/'summary.json',a.extraction/'collected.json',
               Path(__file__).resolve(),Path(__file__).with_name('audit_sparkle_rtlil_roundtrip.py')]
        summary['inputs']=snapshot(paths);save(a.work/'summary.json',summary)
        details=read_inventory(a.extraction/'collected.json')
        save(a.work/'inventory.json',details)
        verify(summary['inputs'])
        summary['inventory_sha256']=snapshot([a.work/'inventory.json'])
        summary['phase']='inventory_complete'
        summary['memory_state_bits']=details['ram_state_bits']
        summary['residual_memories']={k:list(v) for k,v in details['residual_memories_to_map'].items()}
    except BaseException as error:
        summary['error']=type(error).__name__+': '+str(error);raise
    finally:save(a.work/'summary.json',summary)
    print(json.dumps(summary),flush=True)

if __name__=='__main__':main()
