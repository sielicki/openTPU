"""Read-only diagnostic of preserved JSON owners and typed AST child symbols.

This reports evidence; it does not repair metadata or publish an inventory.
Root owns bounded execution. No extraction is performed.
"""
import argparse,json,sqlite3,sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import bounded_context,require
from audit_sparkle_rtlil_roundtrip import Owners
from audit_sparkle_specialized_hierarchy import ast_parameter_bits

def ast_children(log,wanted):
    scopes={};params={};count=0
    with log.open() as stream:
        while True:
            line=stream.readline();require(line!='','Missing AST dump')
            if line.strip()=='{':break
        parser=Owners(stream,limit=1024*1024);parser.buf='{\n'
        def visit(path,depth=0):
            nonlocal count
            count+=1;require(depth<128 and count<=10000000,'AST diagnostic bound exceeded')
            parser.whitespace();first=parser.buf[parser.pos]
            if first=='{':
                scalars={};seen=set()
                for key in parser.object():
                    require(key not in seen,'Duplicate AST field');seen.add(key)
                    value=visit(path+(key,),depth+1)
                    if value is not None:scalars[key]=value
                if scalars.get('kind') in ('Root','Instance','InstanceBody','GenerateBlock','GenerateBlockArray','InstanceArray'):scopes[path]=scalars
                if scalars.get('kind')=='Parameter':
                    params.setdefault(path[:-2],[]).append({'path':list(path),**scalars})
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
    rows=[]
    for path,body in scopes.items():
        if body.get('kind')!='InstanceBody' or body.get('name') not in wanted:continue
        ancestors=[p for p,v in scopes.items() if len(p)<len(path) and path[:len(p)]==p and v.get('kind')=='InstanceBody']
        if len(ancestors)!=1 or scopes[ancestors[0]].get('name')!='otpu_vpu':continue
        values=[]
        for param in params.get(path,[]):
            row=dict(param)
            try:
                bits,shape=ast_parameter_bits(param);row.update(evaluated_bits=bits,evaluated_shape=shape)
            except (RuntimeError,KeyError) as error:row['typed_conversion_error']=str(error)
            values.append(row)
        ancestry=[{'path':list(path[:i]),**scopes[path[:i]],'local_parameters':params.get(path[:i],[])} for i in range(len(path)) if path[:i] in scopes]
        rows.append({'body_path':list(path),'body':body,'ancestry':ancestry,'nonlocal_parameters':[v for v in values if not v.get('isLocal')],'local_parameters':[v for v in values if v.get('isLocal')]})
    return rows

def main(work,log):
    bounded_context();database=(work/'owners.sqlite').resolve()
    sources=json.loads((work/'source-inventory.json').read_text());declared=sources['definitions']
    db=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True);bad=[];wanted=set();count=0
    def metadata(module,section):
        row=db.execute('SELECT payload FROM owners WHERE module=? AND section=? AND name=?',(module,section,'')).fetchone()
        return json.loads(row[0]) if row else None
    try:
        for name,payload in db.execute("SELECT name,payload FROM owners WHERE module='otpu_vpu' AND section='cells' ORDER BY rowid"):
            cell=json.loads(payload);kind=cell['type']
            if kind.startswith('$') and not kind.startswith('$paramod'):continue
            count+=1;attrs=metadata(kind,'attributes');defaults=metadata(kind,'parameter_default_values')
            original=(attrs or {}).get('hdlname',kind);expected=declared.get(original,{}).get('parameter_types');effective={**(defaults or {}),**cell['parameters']}
            wanted.add(original)
            if expected is not None and set(effective)==set(expected):continue
            bad.append({'cell':name,'specialized_type':kind,'original_definition':original,
                        'definition_attributes':attrs,'json_parameter_defaults':defaults,
                        'actual_cell_parameters':cell['parameters'],'effective_json_parameters':effective,
                        'source_declared_parameter_types':expected,
                        'missing_parameters':sorted(set(expected or {})-set(effective)),
                        'extra_parameters':sorted(set(effective)-set(expected or {})),
                        'port_widths':{p:len(bits) for p,bits in cell['connections'].items()},
                        'port_directions':cell['port_directions']})
    finally:db.close()
    print(json.dumps({'status':'diagnostic_only_no_inventory_claim','database':str(database),'ast_log':str(log),
                      'root_child_count':count,'parameter_mismatches':bad,
                      'matching_ast_bodies':ast_children(log,wanted)},indent=2),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--log',type=Path,required=True);a=p.parse_args();main(a.work,a.log)
