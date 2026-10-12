"""Streaming complete-owner identity, lemma lift and whole-graph congruence."""
import copy
import hashlib
import json
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle/mxu_outer_mul_congruence_draft'),
             str(ROOT/'build/sparkle/mxu_outer_arithmetic_diagnostic_draft')]
from mul_congruence import digest
from operand_graph import PROBE
from check_partitioned_D import PairedIndex,write_partition
from control_extension import schema
from dot_initial_store import need


def owners(index,design='probe'):
    for kind,name,data in index.db.execute('SELECT kind,name,data FROM owner WHERE design=? AND module=? ORDER BY kind,name',(design,'paired')):
        yield kind,name,json.loads(data)


def full_audit(index):
    counts={}
    for kind,name,value in owners(index):
        if kind=='metadata':
            need(name in ('attributes','parameter_default_values'),'extra module metadata')
            need(not value if name=='parameter_default_values' else not any(k in value for k in ('init','blackbox','whitebox')),
                 'full graph constrained/parameterized module')
        elif kind=='cells':schema(value);counts[value['type']]=counts.get(value['type'],0)+1
        else:
            need(kind in ('ports','netnames') and 'init' not in value and 'init' not in value.get('attributes',{}),'unsupported full owner')
            for bit in value['bits']:
                need(type(bit)is int and bit>=0 or type(bit)is str and bit in ('0','1','x'),'invalid full alias bit')
                if kind=='ports' and value['direction']=='output':index.driver(bit)
    return {'cell_types':counts,'complete_driver_DAG':True,'all_owner_metadata_audited':True}


def original_identity(index,original_path):
    need(index.store.ingest(original_path,'original','paired')==['paired'],'extra original module')
    for a,b in [('original','probe'),('probe','original')]:
        extra=list(index.db.execute('SELECT kind,name FROM owner WHERE design=? EXCEPT SELECT kind,name FROM owner WHERE design=?',(a,b)))
        need(extra==([] if a=='original' else [('ports',PROBE)]),'indexed/original owner inventory differs')
    count=0;hasher=hashlib.sha256()
    for kind,name,value in owners(index,'original'):
        need(value==index.store.item('probe','paired',kind,name),'complete indexed/original owner differs')
        hasher.update(json.dumps([kind,name,value],sort_keys=True,separators=(',',':')).encode()+b'\n');count+=1
    eq=index.cell('retained_equality')['connections'];expected=[b for pair in zip(eq['A'],eq['B']) for b in pair]
    need(len(eq['A'])==len(eq['B'])==5928 and index.store.item('probe','paired','ports',PROBE)==
         {'direction':'output','bits':expected},'complete interleaved probe differs')
    return {'complete_owners':count,'canonical_owner_sha256':hasher.hexdigest(),'only_added_port':PROBE}


def lift(index,operand_manifest,source_cone):
    targets=operand_manifest['target_cells'];target_names={t['name'] for t in targets.values()}
    for target in targets.values():need(index.cell(target['name'])==target['body'],'FULL target body differs from actual operand lemma')
    inputs=[r['bit'] for r in operand_manifest['operand_coordinates']]
    need(len(inputs)==128,'full operand coordinate count differs')
    pending=list(inputs);seen=set();ancestry=set();roots=set()
    while pending:
        bit=pending.pop()
        if bit in seen:continue
        seen.add(bit);kind,name=index.driver(bit)
        if kind=='input':roots.add(bit)
        elif kind=='cell':
            need(name not in target_names,'full target output reaches operand ancestry')
            if name not in ancestry:ancestry.add(name);pending.extend(index.dependencies(name))
    # The first projection is replayed separately byte-for-byte by the caller.
    # Here root identities and actual complete target coordinates are explicit.
    projected=source_cone['ports']
    for root in operand_manifest['original_root_manifest']:
        row=index.db.execute("SELECT kind,name,idx FROM driver WHERE design='probe' AND bit=?",(root['bit'],)).fetchone()
        need(row==('input',root['original_port'],root['original_bit_index_lsb']),'lift original root semantic identity differs')
        need(projected['root_'+str(root['bit'])]=={'direction':'input','bits':[root['bit']]},'lift projected root differs')
    return {'full_target_cells':targets,'full_operand_coordinates':operand_manifest['operand_coordinates'],
        'conservative_full_cell_ancestry':sorted(ancestry),'full_ancestry_input_ids':sorted(roots),
        'target_output_ancestry_absent':True,'proof_direction':'every original full model restricts to replayed exact mux/whole-cell projection, then whole-cell operand projection',
        'totality_128_and_equality_64_lifted':True,'new_assumptions':[]}


def coordinate_map(index,targets):
    gold=targets['gold']['name'];gate=targets['gate']['name'];g=index.cell(gold);n=index.cell(gate)
    need(g==targets['gold']['body'] and n==targets['gate']['body'],'full multiply body differs')
    need(g['type']==n['type']=='$mul' and g['parameters']==n['parameters'],'full multiply shape differs')
    a=g['connections']['Y'];b=n['connections']['Y']
    need(len(a)==len(set(a))==len(b)==len(set(b))==32 and not set(a)&set(b),'full Y identity overlaps')
    return gold,gate,dict(zip(a,b))


def mapped_owner(kind,value,mapping):
    result=copy.deepcopy(value)
    def bits(values):return [mapping.get(b,b) if type(b)is int else b for b in values]
    if kind in ('ports','netnames'):result['bits']=bits(result['bits'])
    elif kind=='cells':result['connections']={p:bits(v) for p,v in result['connections'].items()}
    if kind=='ports' and value['direction']=='input':need(result==value,'full rewrite modifies original input root')
    return result


def write_full(index,path,targets):
    gold,gate,mapping=coordinate_map(index,targets);count=0;hasher=hashlib.sha256()
    with path.open('w') as out:
        out.write('{"modules":{"paired":{');first=True
        for kind,name,value in owners(index):
            if kind!='metadata':continue
            if not first:out.write(',')
            first=False;json.dump(name,out);out.write(':');json.dump(value,out)
        for kind in ('ports','netnames','cells'):
            if not first:out.write(',')
            first=False;json.dump(kind,out);out.write(':{');comma=False
            for name,data in index.db.execute('SELECT name,data FROM owner WHERE design=? AND module=? AND kind=? ORDER BY name',('probe','paired',kind)):
                if kind=='cells' and name==gold:continue
                value=mapped_owner(kind,json.loads(data),mapping)
                if comma:out.write(',')
                comma=True;json.dump(name,out);out.write(':');json.dump(value,out)
                hasher.update(json.dumps([kind,name,value],sort_keys=True,separators=(',',':')).encode()+b'\n');count+=1
            out.write('}')
        out.write('}}}')
    need(index.store.ingest(path,'transformed','paired')==['paired'],'extra transformed module')
    # Independent complete owner replay, including all metadata and aliases.
    for a,b in [('probe','transformed'),('transformed','probe')]:
        extra=list(index.db.execute('SELECT kind,name FROM owner WHERE design=? EXCEPT SELECT kind,name FROM owner WHERE design=?',(a,b)))
        need(extra==([('cells',gold)] if a=='probe' else []),'full rewrite owner inventory differs')
    for kind,name,value in owners(index):
        if kind=='cells' and name==gold:continue
        need(index.store.item('transformed','paired',kind,name)==mapped_owner(kind,value,mapping),'complete whole-graph substitution replay differs')
    return {'gold_cell':gold,'gate_cell':gate,'Y_coordinate_map':[[a,b] for a,b in mapping.items()],
        'complete_nonmetadata_owners':count,'canonical_owner_sha256':hasher.hexdigest(),
        'full_owner_replay':True,'model_direction':'original model implies transformed model with same observations; known equal multiply Y vectors substituted everywhere',
        'new_input_roots':False,'new_assumptions':[]}
