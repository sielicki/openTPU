"""Cheap read-only concrete schema probe; not a completed inventory receipt."""
import argparse,json,sqlite3,sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import bounded_context,require
from original_ast import original_root_metadata
from child_ast import bind_child_parameters,bind_child_ports,export_policy,loop_policy,serializer_policy

def main(work,log):
    bounded_context()
    source=ROOT/'build/sparkle/yosys_source_acquisition/attempt1/source/frontends/slang/lib'
    export_policy((source/'src/slang_frontend.cc').read_text(),(source/'third_party/slang/include/slang/ast/ASTVisitor.h').read_text())
    loop_policy((source/'third_party/slang/source/ast/symbols/BlockSymbols.cpp').read_text())
    serializer_policy((source/'third_party/slang/source/ast/ASTSerializer.cpp').read_text())
    metadata=original_root_metadata(log,'otpu_vpu');declared=json.loads((work/'source-inventory.json').read_text())['definitions'];rows={}
    db=sqlite3.connect((work/'owners.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    try:
        def value(module,section):
            row=db.execute('SELECT payload FROM owners WHERE module=? AND section=? AND name=?',(module,section,'')).fetchone()
            return json.loads(row[0]) if row else {}
        for name,payload in db.execute("SELECT name,payload FROM owners WHERE module='otpu_vpu' AND section='cells' ORDER BY rowid"):
            cell=json.loads(payload);kind=cell['type']
            if kind.startswith('$') and not kind.startswith('$paramod'):continue
            attrs=value(kind,'attributes');original=attrs.get('hdlname',kind)
            require(name in metadata['direct_children'],'Actual JSON child absent from AST')
            child={'cell':name,'parameters':cell['parameters'],'original_definition':original,'connections':cell['connections'],'port_directions':cell['port_directions']}
            declaration={n:{**json.loads(p),'width':len(json.loads(p)['bits'])} for n,p in db.execute("SELECT name,payload FROM owners WHERE module=? AND section='ports'",(kind,))}
            bind_child_ports(child,declaration,metadata['direct_children'][name])
            bind_child_parameters(child,{'parameter_default_values':value(kind,'parameter_default_values')},metadata['direct_children'][name],declared[original]['parameter_types'])
            rows[name]={'original_definition':original,'complete_effective_parameters':child['effective_parameters'],
                        'declared_parameter_values_verified':child['declared_parameter_values_verified'],
                        'complete_export_semantics_verified':child['complete_export_semantics_verified'],
                        'unresolved_non_declared_exports':child['unresolved_non_declared_exports'],
                        'complete_specialized_port_widths_verified':child['complete_specialized_port_widths_verified'],
                        'unresolved_specialized_port_layouts':child['unresolved_specialized_port_layouts'],
                        'generic_specialized_shape_differences':child['generic_specialized_shape_differences']}
        require(len(rows)==23 and set(rows)==set(metadata['direct_children']),'Complete 23-child AST/JSON inventory differs')
    finally:db.close()
    complete=all(c['complete_export_semantics_verified'] for c in rows.values())
    print(json.dumps({'status':'concrete_child_parameter_inventory_probe_completed','complete_export_semantics_verified':complete,
                      'inventory_proven':False,'children':rows,'child_count':len(rows)},indent=2),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--log',type=Path,required=True);a=p.parse_args();main(a.work,a.log)
