"""Replay concrete batch operands and independent actual-SatGen compare rule."""
from pathlib import Path
import sys
from predicate_full_graph import ROOT
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_outer_predicate_rule_draft'))
from predicate_rule import graph as rule_graph
from batch_operands import construct,equality,mutate,equality_script,PROBE
from check_partitioned_D import read,require,query_script,classify,result


def qualify_queries(record,hashes,expected,width,freeze):
    require(set(record['queries'])==set(expected),'complete query inventory differs')
    rows=[]
    for name,(module,total,want) in expected.items():
        row=record['queries'][name];paths={}
        for key in ('graph','script','log'):
            path=Path(row[key]).resolve();freeze(path,hashes[str(path)]);paths[key]=path
        require(read(paths['graph'])=={'modules':{'gold':module}},'whole actual query graph replay differs')
        require(paths['script'].read_text()==(query_script(paths['graph'],'gold') if total else equality_script(paths['graph'])),
                'actual query constraints differ')
        answer=classify(paths['log'].read_text(),[{'port':PROBE,'offset_lsb':0,'width':width}]) if total else {'status':result(paths['log'].read_text())}
        require(answer['status']==row['status']==want,'actual terminal result differs')
        if name=='undefined-fault':require(any(r['bit_index_lsb']==0 for r in answer['undefined_locations']),'actual fault location differs')
        rows.append({'name':name,'graph_sha256':hashes[str(paths['graph'])],'status':want})
    return rows


def qualify_batch(record,hashes,source,freeze):
    require(record['schema_version']==1 and record['certificate_kind']=='archived_eight_swapped_predicate_operand_lemmas' and
            record['status']=='complete_operand_totality_and_equality_certified' and
            all(record[k] is True for k in ('operand_definedness_proven','operand_equality_proven','negative_controls_passed')),
            'complete eight-pair operand certificate required')
    require((record['pair_count'],record['totality_bit_count'],record['equality_pair_count'])==(8,1024,512),
            'complete operand counts differ')
    require(record['defined_full_Q_required'] is True and record['defined_external_RAM_FP_returns_required'] is True and
            record['RAM_FP_child_output_definedness_discharged'] is False,'operand defined-root domain differs')
    operands,manifest=construct(source)
    # The batch publisher annotates the same target objects that are also
    # referenced by each pair's ancestry manifest. Replay that exact annotation
    # in both places, bound to the actual complete source-cone bytes.
    source_path=Path(record['active_artifacts']['source_cone']).resolve()
    for target in manifest['target_cells'].values():
        target['full_body_pinned_by_diagnostic_graph_sha256']=hashes[str(source_path)]
    path=Path(record['active_artifacts']['operand-manifest']).resolve();freeze(path,hashes[str(path)]);old=read(path)
    for key,value in manifest.items():
        require(old[key]==value,'operand manifest correspondence differs: '+key)
    rows=qualify_queries(record,hashes,{
        'operand-totality':(operands,True,'all_obligations_defined'),
        'operand-equality':(equality(operands),False,'equal'),
        'undefined-fault':(mutate(operands,'undefined'),True,'undefined_obligation_witness'),
        'different-fault':(equality(mutate(operands,'different')),False,'counterexample')},1024,freeze)
    return old,rows


def qualify_rule(record,hashes,freeze):
    require(record['schema_version']==1 and record['certificate_kind']=='actual_satgen_unsigned32_gt_lt_rule' and
            record['status']=='complete_actual_satgen_comparison_rule' and record['comparison_rule_proven'] is True,
            'complete actual comparison rule required')
    require(record['domain']=={'A_WIDTH':32,'B_WIDTH':32,'A_SIGNED':0,'B_SIGNED':0,'Y_WIDTH':1,'all64_input_bits_defined':True},
            'comparison rule domain differs')
    return qualify_queries(record,hashes,{
        'outputs-totality':(rule_graph(),True,'all_obligations_defined'),
        'swapped-equality':(rule_graph(),False,'equal'),
        'wrong-orientation':(rule_graph(False),False,'counterexample')},2,freeze)
