"""Read-only all-child ABI mismatch diagnostic over preserved SQLite and AST.

No metadata is repaired and no inventory/proof completion is published.
"""
import argparse,json,sqlite3,sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import bounded_context,require
from audit_sparkle_rtlil_roundtrip import Owners
from audit_sparkle_specialized_hierarchy import ast_integral_type
from original_ast import original_root_metadata

def ast_ports(log,wanted_paths):
    output={};count=0
    with log.open() as stream:
        while True:
            line=stream.readline();require(line!='','Missing AST dump')
            if line.strip()=='{':break
        parser=Owners(stream,limit=1024*1024);parser.buf='{\n'
        def visit(path,depth=0):
            nonlocal count
            count+=1;require(count<=10000000 and depth<128,'AST diagnostic bound exceeded')
            parser.whitespace();first=parser.buf[parser.pos]
            if first=='{':
                scalars={};seen=set()
                for key in parser.object():
                    require(key not in seen,'Duplicate AST field');seen.add(key)
                    v=visit(path+(key,),depth+1)
                    if v is not None:scalars[key]=v
                if scalars.get('kind')=='Port' and path[:-2] in wanted_paths:
                    row={'path':list(path),**scalars}
                    try:row['integral_geometry']=ast_integral_type(scalars['type'])
                    except RuntimeError:row['integral_geometry']=None
                    ports=output.setdefault(wanted_paths[path[:-2]],{})
                    require(scalars['name'] not in ports,'Duplicate actual child AST port');ports[scalars['name']]=row
                return None
            if first=='[':
                parser.char('[');index=0
                while True:
                    parser.whitespace()
                    if parser.buf[parser.pos]==']':parser.pos+=1;break
                    if index:parser.char(',')
                    visit(path+(index,),depth+1);index+=1
                return None
            return parser.value()
        visit(())
    return output

def main(work,log):
    bounded_context();metadata=original_root_metadata(log,'otpu_vpu')['direct_children']
    ports=ast_ports(log,{tuple(m['body_path']):n for n,m in metadata.items()})
    db=sqlite3.connect((work/'owners.sqlite').resolve().as_uri()+'?mode=ro',uri=True);rows=[];count=0
    try:
        for name,payload in db.execute("SELECT name,payload FROM owners WHERE module='otpu_vpu' AND section='cells' ORDER BY rowid"):
            cell=json.loads(payload);kind=cell['type']
            if kind.startswith('$') and not kind.startswith('$paramod'):continue
            count+=1;require(name in metadata and name in ports,'Missing exact child AST occurrence')
            declaration={n:json.loads(p) for n,p in db.execute("SELECT name,payload FROM owners WHERE module=? AND section='ports'",(kind,))}
            mismatches={}
            for pin in sorted(set(cell['connections'])|set(declaration)|set(ports[name])):
                actual=cell['connections'].get(pin);decl=declaration.get(pin);ast=ports[name].get(pin)
                direction=cell['port_directions'].get(pin)
                if actual is not None and decl is not None and ast is not None and direction==decl['direction'] and len(actual)==len(decl['bits']):continue
                mismatches[pin]={'actual_cell_direction':direction,'actual_cell_width':len(actual) if actual is not None else None,
                                 'declaration_direction':decl.get('direction') if decl else None,'declaration_width':len(decl['bits']) if decl else None,
                                 'declaration_geometry':{k:v for k,v in (decl or {}).items() if k not in ('bits',)},'typed_actual_ast_port':ast}
            if mismatches:rows.append({'child':name,'cell_type':kind,'ast_body':metadata[name]['body'],'actual_cell_parameters':cell['parameters'],
                                      'typed_declared_parameters':metadata[name]['declared_parameters'],'mismatched_pins':mismatches})
    finally:db.close()
    print(json.dumps({'status':'diagnostic_only_abi_unproved','child_count':count,'children_with_mismatches':rows},indent=2),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--log',type=Path,required=True);a=p.parse_args();main(a.work,a.log)
