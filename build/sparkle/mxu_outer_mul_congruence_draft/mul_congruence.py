"""Exact whole-Y congruence rewrite, conditional on authenticated operand lemmas."""
import copy
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle/mxu_outer_operand_lemma_draft')]
from operand_graph import audit,construct,digest
from dot_initial_store import need


def rewrite(source,gold_name,gate_name):
    # This validates shape and absence of either multiply in operand ancestry.
    _,operand_manifest=construct(source,gold_name,gate_name)
    gold=source['cells'][gold_name];gate=source['cells'][gate_name]
    need(gold['parameters']==gate['parameters'] and gold['port_directions']==gate['port_directions'],
         'multiply parameter serialization/directions differ')
    old=gold['connections']['Y'];new=gate['connections']['Y']
    need(len(old)==len(new)==32 and len(set(old))==len(set(new))==32 and not set(old)&set(new),
         'whole multiply outputs overlap or duplicate')
    mapping=dict(zip(old,new));target=copy.deepcopy(source);del target['cells'][gold_name]
    counts={'ports':0,'netnames':0,'cell_pins':0}
    def mapped(bits,kind):
        counts[kind]+=sum(type(b)is int and b in mapping for b in bits)
        return [mapping.get(b,b) if type(b)is int else b for b in bits]
    for kind in ('ports','netnames'):
        for owner in target[kind].values():owner['bits']=mapped(owner['bits'],kind)
    for cell in target['cells'].values():
        for pin,bits in cell['connections'].items():cell['connections'][pin]=mapped(bits,'cell_pins')
    audit(target)
    need({n:p for n,p in source['ports'].items() if p['direction']=='input'}==
         {n:p for n,p in target['ports'].items() if p['direction']=='input'},'rewrite changed original roots')
    certificate={'schema_version':1,'source_module_sha256':digest(source),'target_module_sha256':digest(target),
        'gold_cell':gold_name,'gate_cell':gate_name,'operand_target_cells':operand_manifest['target_cells'],
        'Y_coordinate_map':[{'index_lsb':i,'gold':a,'gate':b} for i,(a,b) in enumerate(zip(old,new))],
        'replaced_uses':counts,'only_removed_cell':gold_name,
        'proof_rule':'equal defined ordered operands under original roots imply equal defined deterministic multiply Y; rename every Y use simultaneously',
        'model_direction':'every original satisfying value/undef assignment induces a transformed assignment with identical observations under the recorded coordinate map',
        'operand_totality_and_equality_certificate_required':True,'no_new_roots_or_assumptions':True}
    return target,certificate


def verify(source,target,certificate,gold_name,gate_name):
    expected,record=rewrite(source,gold_name,gate_name)
    need(target==expected and certificate==record,'whole graph/coordinate certificate replay differs')
    return record
