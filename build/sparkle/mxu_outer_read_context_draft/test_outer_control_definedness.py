"""Source-only drafted guards; run solely through the workspace resource gate."""
import copy
from pathlib import Path
import pytest
from check_outer_control_definedness import coverage_result,compiler_dependencies,ownership_contract,fail_incomplete,PROOF,HISTORICAL_SHA,CFG


def rows():
    result=[]
    for v in range(2):
        for m in range(2):
            for y in range(2):
                for u in range(2):
                    bit=int(u==m and (m or y==v))
                    result.append(f'COVERAGE value={v} mask={m} yvalue={y} yundef={u} sat={bit} expected={bit}')
    result.append('OUTER_READ_MASK_COVERAGE_PASS rows=16 sat=6 unsat=10')
    return result


def test_all_sixteen_actual_pair_results_required():
    assert coverage_result('\n'.join(rows()))['all_value_undef_pairs_covered']


@pytest.mark.parametrize('fault',['missing','duplicate','wrong','timeout','marker'])
def test_coverage_rejects_partial_or_wrong_actual_result(fault):
    text=rows()
    if fault=='missing':text.pop(3)
    elif fault=='duplicate':text.insert(0,text[0])
    elif fault=='wrong':text[0]=text[0].replace('sat=1','sat=0')
    elif fault=='timeout':text.append('TIMEOUT')
    else:text.pop()
    message={'missing':'incomplete actual mask coverage','duplicate':'duplicate coverage row',
             'wrong':'coverage relation differs','timeout':'coverage failed','marker':'incomplete actual mask coverage'}[fault]
    with pytest.raises(RuntimeError,match=message):coverage_result('\n'.join(text))


def test_dependency_manifest_complete_and_existing(tmp_path):
    one=tmp_path/'one.h';two=tmp_path/'two.h';one.write_text('');two.write_text('')
    dep=tmp_path/'source.d';dep.write_text('source.o: '+str(one)+' \\\n '+str(two)+'\n')
    assert compiler_dependencies(dep)==sorted([one,two])
    two.unlink()
    with pytest.raises(RuntimeError,match='missing compiler dependency'):compiler_dependencies(dep)


def record():
    return {'status':'complete_archived_outer_initial_ownership_mapped_quotient_and_RAM_identity_certified',
            'configuration':list(CFG),'historical_receipt':{'path':str(PROOF),'sha256':HISTORICAL_SHA},
            'original_to_mapped_initial_ownership':{'original_array_bits':2297},
            'retained_initialization':{'retained_bits':5928,'pruned_bits_per_side':1508},
            'RAM_identity':{'state_bits':1204224},
            'generation_provenance':{'generation_source_closure_available':False}}


def test_exact_scoped_ownership_contract():
    ownership_contract(record())


@pytest.mark.parametrize('fault',['status','config','historical','state','RAM','source_scope'])
def test_wrong_ownership_cannot_qualify_control_model(fault):
    item=record()
    if fault=='status':item['status']='incomplete'
    elif fault=='config':item['configuration'][0]=64
    elif fault=='historical':item['historical_receipt']['sha256']='0'*64
    elif fault=='state':item['retained_initialization']['pruned_bits_per_side']=0
    elif fault=='RAM':item['RAM_identity']['state_bits']=0
    else:item['generation_provenance']['generation_source_closure_available']=True
    message={'status':'initial ownership incomplete','config':'ownership specialization differs',
             'historical':'ownership historical identity differs','state':'ownership state inventory differs',
             'RAM':'ownership state inventory differs','source_scope':'unexpected historical generation scope'}[fault]
    with pytest.raises(RuntimeError,match=message):ownership_contract(item)


def test_late_finalization_failure_revokes_both_flags_and_retries_publication(tmp_path):
    partial=tmp_path/'query.log';partial.write_text('finished query')
    report={'status':'complete_auxiliary_control_definedness_certified',
            'control_definedness_proven':True,'read_cut_model_extension_proven':True,
            'active_artifacts':{'log':str(partial)}}
    archived=[];published=[]
    def freeze(path):archived.append(path)
    def checkpoint(stage):
        published.append((stage,copy.deepcopy(report)))
        if len(published)==1:raise OSError('injected publication failure')
    fail_incomplete(report,RuntimeError('injected ev.finish failure'),freeze,checkpoint)
    assert archived==[partial]
    assert [stage for stage,_ in published]==['incomplete','incomplete_retry']
    for _,snapshot in published:
        assert snapshot['status']=='incomplete'
        assert not snapshot['control_definedness_proven']
        assert not snapshot['read_cut_model_extension_proven']
    assert 'incomplete_publication_error' in report
