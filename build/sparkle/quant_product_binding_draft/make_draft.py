from pathlib import Path
p=Path('tools/check_sparkle_qscale_product_consumers.py').read_text()
a=p.index('MODULES=');b=p.index('\n\ndef run(',a)
p=p[:a]+'''# Pending final receipt input inventory; refuse to qualify until finalized.
EXPECTED_INPUTS = None
import check_sparkle_quant_product as product
import check_sparkle_qread_product_consumers as reader
import check_sparkle_qwrite_product_consumers as writer
import check_sparkle_qscale_product_consumers as scaler
MODULES={'otpu_quant_sparkle'} | reader.MODULES | writer.MODULES | scaler.MODULES
LEAVES={'reader':(reader,4290),'writer':(writer,2308),'scaler':(scaler,4111)}
CHILDREN={'reader':'otpu_qread_sparkle','writer':'otpu_qwrite_sparkle','scaler':'otpu_qscale_sparkle'}
OUTPUTS={'reader':{'xp':256,'mp':126,'mc':126,'mp_baddr':32,'cmax':32},
         'writer':{'wqd':100,'qb':64,'wsc_d':32},
         'scaler':{'ov':1,'otag':2,'sc':32,'inv':32}}


def audit_record(record):
    require(record['status']=='quant128_8_initialized_product_refinement_proven','Complete initialized Quant product proof missing')
    require(record['config']=={'D':128,'LANES':8} and record['state_bits_per_design']==28676,'Production product configuration/state differs')
    require(record['independent_initial_state_equivalence'] is False,'Unsupported independent initialization claim')
    require(set(record['mutations'])=={'completion','buffer','reader_enable'},'Missing production fault control')
    require(all(set(r)=={'source','log','counterexample'} for r in record['mutations'].values()),'Missing concrete production fault evidence')
    parent=record['parent'];fields={product.clean(n):w for n,w,_ in product.parent_fields()}
    witness=parent['initialization_witness']
    require(parent['state_bits']==17967 and set(witness)==set(fields),'Incomplete parent state inventory')
    require(all(type(witness[n])is str and len(witness[n])==w and set(witness[n])<=set('01?') for n,w in fields.items()),'Invalid parent initial witness')
    require(sum(s.count('?') for s in witness.values())==16960,'Unspecified parent initialization scope differs')
    require(set(parent['cuts'])==set(LEAVES) and set(record['leaves'])==set(LEAVES),'Missing complete child relation')
    for name,(_,bits) in LEAVES.items():
        leaf=record['leaves'][name]
        require(leaf['state_bits']==bits and set(leaf['moore'])=={'gold','gate'},'Leaf state/Moore scope differs')
        for side in ['gold','gate']:
            require(leaf['moore'][side]['outputs']==OUTPUTS[name],'Incomplete Moore output inventory')
        cuts=parent['cuts'][name]
        require(set(cuts)=={'gold','gate'} and cuts['gold']['ports']==cuts['gate']['ports'],'Parent complete child inputs differ')
        require(all(cuts[s]['parameters']=={} for s in cuts),'Unresolved cut parameters')
        require(cuts['gate']['type']==CHILDREN[name] and cuts['gold']['type'].split('$')[0]==CHILDREN[name].removesuffix('_sparkle'),'Cut module differs')
    logic=record['generic_composition_logic']
    require('not a concrete Lean-kernel instantiation' in logic['scope'],'Generic logical rule scope overstated')


def bind_modules(proven,actual,proven_context,actual_context):
    require(set(proven)==set(actual)==MODULES,'Complete Quant module inventory differs')
    for name in MODULES:
        require(proven[name]==actual[name],'Quant module body/attributes differ: '+name)
        require(proven_context[name]==actual_context[name],'Quant directive context differs: '+name)


def quant_occurrences(hierarchy):
    paths={}
    for entry in hierarchy['paths']:
        require(entry['path'] not in paths,'Duplicate hierarchy path')
        paths[entry['path']]=entry['specialization']
    roots=[p for p,n in paths.items() if hierarchy['nodes'][n]['module']=='otpu_quant_sparkle']
    require(len(roots)==1,'Expected one production Quant instance')
    root=roots[0];children=hierarchy['nodes'][paths[root]]['children']
    require(len(children)==3 and {c['instance'] for c in children}==set(CHILDREN),'Whole Quant direct child inventory differs')
    for child in children:
        name=child['instance'];path=root+'/'+name
        require(child['module']==CHILDREN[name] and child['overrides']=={},'Quant child type/overrides differ')
        require(path in paths and hierarchy['nodes'][paths[path]]['module']==CHILDREN[name],'Quant child not independently reached')
    require(reader.reader_occurrences(hierarchy)==[root+'/reader'],'Reader not owned by proven Quant')
    require(writer.writer_occurrences(hierarchy)==[root+'/writer'],'Writer not owned by proven Quant')
    require(scaler.scale_occurrences(hierarchy)==[root+'/scaler'],'Scaler not owned by proven Quant')
    return roots
''' + p[b:]
p=p.replace('len(hashes)==184', 'EXPECTED_INPUTS is not None and len(hashes)==EXPECTED_INPUTS').replace('Expected immutable production theorem 184-input inventory','Finalized complete product input inventory required')
p=p.replace("[ROOT/'OpenTPU/QuantScale.lean',ROOT/'OpenTPU/Float.lean',ROOT/'rtl/top/otpu_pkg.sv'", "[Path(product.__file__),*[ROOT/'OpenTPU'/n for n in ['Quant.lean','QuantRead.lean','QuantWrite.lean','QuantScale.lean','Float.lean','ProductComposition.lean']],ROOT/'rtl/top/otpu_pkg.sv'")
a=p.index("        for negative,field in [(False,'proofs')");b=p.index("        proven=selected_modules",a)
p=p[:a]+'''        for fault,item in proof['mutations'].items():
            log_result(artifact(item['log']).read_text(),True)
            product.audit_counterexample(read(artifact(item['counterexample'])))
            expected=product.mutate_native(artifact(proof_path.parent/'native.sv').read_text(),fault)
            require(artifact(item['source']).read_text()==expected,'Actual production mutation differs')
        for name,(auditor,_) in LEAVES.items():
            leaf=proof['leaves'][name]
            original,_=evidence.record(Path(leaf['summary']),leaf['sha256']);auditor.audit_record(original)
            require(leaf['initialization_witness']==original['initialization_witness'],'Leaf initial witness differs')
        logic=proof['generic_composition_logic']
        require(hashes[str(Path(logic['source']).resolve())]==logic['source_sha256'] and
                hashes[str(Path(logic['kernel_check_log']).resolve())]==logic['kernel_check_log_sha256'],'Supporting generic rule identity differs')
        require('BOUNDED_EXIT {"exit_code": 0, "status": "passed"}' in artifact(logic['kernel_check_log']).read_text(),'Supporting generic rule check missing')
        source=artifact(proof_path.resolve().parent/'native.sv')
        require(set(module_hashes(source))==MODULES,'Native product complete module inventory differs')
''' + p[b:]
a=p.index("        report['product_theorem']");b=p.index("        for name,folder",a)
p=p[:a]+'''        report['product_theorem']={'summary':str(proof_path.resolve()),'sha256':digest,'inputs':len(hashes),
            'state_bits_per_quant':28676,'parent_bits':17967,'concrete_leaf_bits':10709,
            'relation':'Initialized synchronous product refinement with shared arbitrary unspecified parent RAM and corresponding FP state; concrete obligations externally proved, not Lean-kernel instantiated'}
''' + p[b:]
p=p.replace('paths=scale_occurrences(hierarchy)','paths=quant_occurrences(hierarchy)').replace("'scale_paths':paths,'module_sha256':proof['native_module_hashes']", "'quant_paths':paths,'module_sha256':module_hashes(source)")
p=p.replace('qscale_product_initialized_refinement_bound','quant_product_initialized_refinement_bound').replace('whole_quant_initialized_equivalence','whole_board_initialized_equivalence').replace('Whole Quant/parent complete initial-state witnesses and composition','Whole board complete initial-state witnesses and composition; configurations other than D128/LANES8').replace('formal_qscale_product/attempt1','quant_product/attempt2')
p=p.replace('Old scale module','Old Quant module').replace('specialized scale/module','specialized Quant/module')
a=p.index('"""');b=p.index('"""',a+3)
p='''"""Whole Quant128/8 initialized product applicability in Gen1, Gen2 and CLI.

Does not establish whole-board initialization or independent-initial-state equality.
Concrete RTL obligations use external proofs; the generic Lean composition rule
is supporting logic and is not a concrete kernel instantiation.
"""'''+p[b+3:]
Path('build/sparkle/quant_product_binding_draft/check_sparkle_quant_product_consumers.py').write_text(p)
