"""Read-only bounded diagnostic; deliberately preserves parser failure.

No proof receipt or inventory completion is produced. Root owns execution.
"""
import argparse,json,re,sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import bounded_context
from original_ast import resolve_array_type,original_root_metadata

def main(log):
    bounded_context();original=resolve_array_type
    def diagnostic(text,aliases):
        try:return original(text,aliases)
        except BaseException:
            rows=[];seen=set();current=text
            while re.match(r'^\d+ ',current):
                address,qualified=current.split(' ',1)
                if address in seen:break
                seen.add(address);alias=aliases.get(address)
                base,separator,suffix=qualified.partition('$')
                rows.append({'requested_type':current,'requested_qualified_name':qualified,
                             'requested_base_qualified_name':base,'requested_unpacked_suffix':separator+suffix,
                             'actual_declaration':alias})
                if alias is None:break
                current=alias['target']
            print(json.dumps({'failing_type':text,'actual_alias_chain':rows},indent=2),flush=True)
            raise
    metadata=original_root_metadata(log,'otpu_vpu',resolver=diagnostic)
    print(json.dumps({'status':'local_typed_ast_parse_passed_inventory_unproved',
                     'parameters':metadata['parameters'],'port_count':len(metadata['ports']),
                     'direct_child_count':len(metadata['direct_children']),
                     'direct_children':{n:{'definition':c['body']['name'],'declared':{k:v['bits'] for k,v in c['declared_parameters'].items()},'export_count':len(c['final_parameter_exports'])} for n,c in metadata['direct_children'].items()},
                     'unresolved_port_types':{n:p['type'] for n,p in metadata['ports'].items() if 'width' not in p}},indent=2),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('log',type=Path);a=p.parse_args();main(a.log)
