"""Production applicability of initialized DSP primitive-model leaf relations.

Parameter-elaborated formal initialization, including shared arbitrary undefined
native state. No raw time-zero four-state simulation, device power-up, cascade,
whole-dot, whole-MXU or whole-board initialization claim.
"""
import argparse
from pathlib import Path
import signal
import sys

from check_sparkle_fp_state_consumers import selected_modules, digest_tokens
from check_sparkle_fpga_top_complete import bounded_context, require, global_directives
from qualify_sparkle_specialization_binding import Evidence, read, save, normalized_hashes, json_projection
from sparkle_provenance import ROOT, archive
import check_sparkle_mxu_dsp_initial as initial

PROOF=ROOT/'build/sparkle/mxu-dsp-initial-second/summary.json'
PROOF_SHA='4925be848d0864d4daf04b129ae199040ceea530f000c99fe469f46bc501de66'
MODULE_BY_CASE={c:('otpu_mxu_pe_dsp_'+c[3:] if c.startswith('pe_') else 'otpu_mxu_colend_dsp_23') for c in initial.CASES}
BITS={'pe_000':134,'pe_001':219,'pe_010':85,'pe_011':170,'pe_100':134,'pe_101':219,'pe_110':85,'pe_111':170,'colend_23':709}
UNDEFINED={c:(192 if c=='colend_23' else 48 if c[-1]=='1' else 18) for c in initial.CASES}
COUNTS={'pe_000':112,'pe_001':336,'pe_010':8,'pe_011':24,'pe_100':8,'pe_101':24,'colend_23':4}


def audit_record(proof):
    require(proof['status']=='nine_dsp_leaf_initialized_refinements_proven','Complete initialized DSP proof missing')
    require(proof['whole_mxu_initialized_equivalence'] is False and proof['independent_initial_state_equivalence'] is False,'Unsupported initialization scope')
    cases=proof['cases'];require([c['case'] for c in cases]==initial.CASES,'Exact nine-case inventory differs')
    for case in cases:
        name=case['case'];mapping=case['mapping'];w=case['initialization']['native_and_reference_witness']
        require(case['status']=='initialized_refinement_proven' and case['state_bits']==BITS[name],'Leaf state scope differs')
        require(set(mapping)==set(w) and sum(mapping.values())==BITS[name],'Incomplete state correspondence')
        require(all(type(v)is int and v>0 and type(w[n])is str and len(w[n])==v and set(w[n])<=set('0?') for n,v in mapping.items()),'Concrete initial witness differs')
        require(sum(v.count('?') for v in w.values())==UNDEFINED[name]==case['initialization']['arbitrary_native_bits'],'Undefined native state scope differs')
        require(case['initialization']['defined_bits']=={'gold':BITS[name]-UNDEFINED[name],'gate':BITS[name]-UNDEFINED[name]},'Defined initialization scope differs')
        fault=case['actual_initializer_mutation']
        require(fault['status']=='rejected_by_initial_predicate_implication' and fault['failure']['reference_constraint']=='0' and fault['failure']['native_constraint']=='1','Actual initializer negative control missing')
        require(set(case['transition_bridge_net_bits'])=={'gold','gate'} and all(type(v)is int and v>0 for v in case['transition_bridge_net_bits'].values()),'Exact transition bridge missing')


def audit_projection_identity(identity,module_hash,context):
    require(identity==json_projection({'module_sha256':module_hash,'incoming_directives':context}),
            'Projection helper exact identity differs')


def bind_module(proven,actual,pc,ac,name):
    require(set(proven)==set(actual)=={name} and proven[name]==actual[name],'Complete DSP helper body/attributes differ')
    require(pc[name]==ac[name],'DSP helper directive context differs')


def primitive_parameters(case,instance):
    pe=case.startswith('pe_');last=int(case[-2]) if pe else int(instance[-1])==3
    wreg=int(case[-1]) if pe else 1
    integers={'ACASCREG':wreg,'ADREG':0,'ALUMODEREG':0,'AREG':wreg,'BCASCREG':1,'BREG':1,
        'CARRYINREG':0,'CARRYINSELREG':0,'CREG':0,'DREG':wreg,'INMODEREG':1 if pe else 0,
        'MREG':1,'OPMODEREG':0,'PREG':1-int(last) if pe else int(last),'i':3}
    params={n:format(v,'032b') for n,v in integers.items()}
    params.update({'AUTORESET_PATDET':'NO_RESET','A_INPUT':'DIRECT','B_INPUT':'DIRECT',
        'SEL_MASK':'MASK','SEL_PATTERN':'PATTERN','USE_DPORT':'TRUE','USE_MULT':'MULTIPLY',
        'USE_PATTERN_DETECT':'NO_PATDET','USE_SIMD':'ONE48','MASK':format(0x3fffffffffff,'048b'),'PATTERN':'0'*48})
    params.update({f'IS_{n}_INVERTED':'0'*w for n,w in [('ALUMODE',4),('CARRYIN',1),('CLK',1),('INMODE',5),('OPMODE',7)]})
    return params


def production_occurrences(hierarchy,binding,module_hashes,projections):
    tops=[n for n in binding['nodes'].values() if n['module']=='otpu_fpga_top_ld']
    require(len(tops)==1 and all(int(tops[0]['effective_parameters'][p],2)==v for p,v in [('MCOLS',4),('MXU_IMPL',2)]),'Exact C4/IMPL2 production configuration missing')
    paths={}
    for item in hierarchy['paths']:
        require(item['path'] not in paths,'Duplicate hierarchy path')
        paths[item['path']]=item['specialization']
    terminals={};terminal_bindings={}
    for item in hierarchy['terminals']:
        require(item['path'] not in terminals and item['path'] not in paths,'Duplicate/overlapping terminal path')
        terminals[item['path']]=item
    for item in binding['terminal_bindings']:
        require(item['path'] not in terminal_bindings,'Duplicate terminal binding path')
        terminal_bindings[item['path']]=item
    reverse={m:c for c,m in MODULE_BY_CASE.items()};found={c:[] for c in initial.CASES};dsp_paths=[]
    def bind_id(path,expected,unparameterized=False):
        require(path in paths,'Unreached primitive/helper child')
        node_id=paths[path];require(node_id in binding['nodes'],'Reached specialization ID not bound')
        node=hierarchy['nodes'][node_id];bound=binding['nodes'][node_id]
        require(node['module']==bound['module']==expected,'Reached specialization type differs')
        require(node['effective_parameters']==bound['effective_parameters'],'Reached effective parameters differ')
        if unparameterized:
            require(node['effective_parameters']==node['overrides']=={},'Unexpected helper parameter override')
            require(bound['module_sha256']==module_hashes[expected],'Reached helper body hash differs')
        return node
    for path,node_id in paths.items():
        name=hierarchy['nodes'][node_id]['module']
        if name not in reverse:continue
        case=reverse[name];node=bind_id(path,name,True);found[case].append(path)
        expected={'u_dsp'} if case.startswith('pe_') else {f'u_dsp{i}' for i in range(4)}
        children=node['children'];require(len(children)==len(expected) and {c['instance'] for c in children}==expected,'Complete DSP primitive child inventory differs')
        for child in children:
            require(child['module']=='DSP48E1','Unexpected primitive type')
            dsp_path=path+'/'+child['instance']
            require(dsp_path in terminals and dsp_path in terminal_bindings,'DSP terminal or terminal binding missing')
            primitive=terminals[dsp_path];bound=terminal_bindings[dsp_path]
            require(primitive['module']==bound['module']=='DSP48E1' and bound['parent_module']==name,'DSP terminal parent/type differs')
            require(child['overrides']==primitive['parameters']==primitive_parameters(case,child['instance']),'Complete primitive model parameters/defaults differ')
            require(child['ports']==primitive['ports'],'DSP terminal connected pin contract differs')
            require(child['unconnected_output_ports']==primitive['unconnected_output_ports']==bound['unconnected_output_ports'],'DSP terminal omitted-output ledger differs')
            projection=projections[case];record=projection['record'];occurrence=record['occurrences'][child['instance']]
            require(set(occurrence['connections'])==set(occurrence['port_directions']),'Incomplete projected pin directions')
            ports={p:{'direction':occurrence['port_directions'][p],'width':len(bits)} for p,bits in occurrence['connections'].items()}
            require(occurrence['parameters']==primitive['parameters'] and ports==primitive['ports'],'Authenticated primitive occurrence differs')
            outputs={'ACOUT':30,'BCOUT':18,'CARRYCASCOUT':1,'CARRYOUT':4,'MULTSIGNOUT':1,'OVERFLOW':1,
                'P':48,'PATTERNBDETECT':1,'PATTERNDETECT':1,'PCOUT':48,'UNDERFLOW':1}
            omitted={p:{'direction':'output','width':w} for p,w in outputs.items() if p not in ports}
            require(omitted==primitive['unconnected_output_ports'],'Exact primitive omitted output interface differs')
            require(any(r['record']==projection['path'] and r['sha256']==projection['sha256'] and
                r['selector']==['occurrences',child['instance']] for r in bound['proof_references']),'Terminal binding lacks exact occurrence certificate')
            profiles=[p for p in primitive['qualified_contracts'] if p['certificate']==projection['path'] and p['parent_module']==name and p['instance']==child['instance']]
            require(len(profiles)==1,'Missing/ambiguous authenticated terminal occurrence profile');profile=profiles[0]
            require(profile['parameters']==primitive['parameters'] and profile['ports']==ports and
                profile['declaration_module_sha256']==record['dsp_declaration_identity']['module_sha256'] and
                profile['declaration_context']==record['dsp_declaration_identity']['incoming_directives'],'DSP declaration/profile identity differs')
            dsp_paths.append(dsp_path)
    counts={c:len(p) for c,p in found.items() if p}
    require(counts==COUNTS,'Exact C4 production helper occurrence inventory differs')
    require(len(dsp_paths)==len(set(dsp_paths))==528,'Missing/aliased concrete DSP occurrence')
    require(set(dsp_paths)=={p for p,t in terminals.items() if t['module']=='DSP48E1'},'Extra or missing reachable DSP terminal outside qualified helpers')
    require(set(dsp_paths)=={p for p,t in terminal_bindings.items() if t['module']=='DSP48E1'},'Extra or missing DSP terminal binding')
    total=sum(BITS[c]*n for c,n in counts.items());require(total==102516,'Concrete reached leaf state inventory differs')
    return {'helper_paths':{c:sorted(p) for c,p in found.items() if p},'helper_counts':counts,
        'uninstantiated_proven_cases':[c for c in initial.CASES if not found[c]],
        'dsp_primitive_paths':sorted(dsp_paths),'concrete_leaf_state_bits':total}


def run(output):
    bounded_context();output=output.resolve();require(not output.exists(),'Fresh output required');output.mkdir(parents=True)
    ev=Evidence();summary=output/'summary.json';report={'status':'incomplete','scope':__doc__,'cases':[],
        'whole_mxu_initialized_equivalence':False,'cascade_initialized_composition':False,'device_powerup_equivalence':False}
    def checkpoint():report['input_sha256']=ev.observed;save(summary,report)
    def interrupted(signum,frame):raise RuntimeError('Interrupted '+str(signum))
    signal.signal(signal.SIGTERM,interrupted);checkpoint()
    try:
        for module in list(sys.modules.values()):
            path=getattr(module,'__file__',None)
            if path and Path(path).resolve().parent==ROOT/'tools':ev.direct(Path(path))
        ev.direct(Path(__file__))
        proof,digest=ev.record(PROOF,PROOF_SHA);audit_record(proof)
        hashes=normalized_hashes(proof['input_sha256']);require(len(hashes)==416,'Immutable complete DSP theorem inventory differs')
        for path,h in hashes.items():
            source=Path(path)
            if (source.suffix in ['.lean','.py','.sv'] and any(source.is_relative_to(ROOT/p) for p in ['OpenTPU','rtl','tools'])):
                ev.direct(source,h)
        def artifact(path):
            path=Path(path).resolve();require(str(path) in hashes,'Unauthenticated DSP artifact')
            return Path(ev.authenticated[(str(path),hashes[str(path)])])
        proven={};contexts={};mh={};leaf_records={};initialized_cases={c['case']:c for c in proof['cases']}
        for case in proof['cases']:
            name=case['case'];old=Path(case['historical_summary']).parent
            leaf,_=ev.record(Path(case['historical_summary']),case['historical_sha256'])
            leaf_records[name]=leaf
            require(leaf['status']=='passed' and leaf['case']==name and leaf['state_bits']==BITS[name],'Historical concrete leaf theorem differs')
            model=Path(leaf['dsp_model']);ev.direct(model,leaf['dsp_model_sha256'])
            require(model.resolve()==initial.physical.dsp_model().resolve(),'Actual primitive library differs')
            original=artifact(old/'DSP48E1.sv').read_text()
            require(initial.functional_model(model.read_text())==original,'Exact primitive functional model differs')
            expanded,certificate=initial.expand_parameter_initializer(original)
            expansion=read(artifact(case['parameter_initializer_expansion']))
            require(expansion=={**certificate,'original_model':str(old/'DSP48E1.sv'),
                'expanded_model':str(PROOF.parent/name/'DSP48E1-parameter-initial.sv')},'Parameter-elaborated initialization certificate differs')
            require(artifact(expansion['expanded_model']).read_text()==expanded,'Expanded primitive differs')
            fault=read(artifact(case['actual_initializer_mutation']['audit']))
            require(fault['status']=='rejected_by_initial_predicate_implication' and fault['failure']==case['actual_initializer_mutation']['failure'],'Actual initialization rejection differs')
            require(artifact(fault['native_model']).read_text()==initial.mutate_native_initializer(expanded),'Native-only primitive initializer mutation differs')
            # Extraction succeeded and the complete graph was checked by the
            # pinned theorem; reject a missing or unauthenticated extraction log.
            artifact(fault['extraction_log']);artifact(fault['extraction_script']);artifact(fault['extraction'])
            source=artifact(old/'native.sv');module=MODULE_BY_CASE[name]
            proven[module]=selected_modules(source,{module});_,contexts[module]=global_directives(source)
            mh[module]=digest_tokens(proven[module][module])
        coverage_path=ROOT/'build/sparkle/module-coverage-joined-first/summary.json'
        coverage,ch=ev.record(coverage_path)
        require(coverage['status']=='module_definitions_bound_scope_incomplete','Production definition coverage missing')
        report['initialized_leaf_theorem']={'summary':str(PROOF),'sha256':digest,'inputs':416,
            'initialization_semantics':'Parameter-elaborated primitive-model predicates, with undefined native bits arbitrary; no event-region/time-zero four-state equivalence'}
        for name,folder in [('gen1','specialization-binding-gen1-first'),('gen2','specialization-binding-gen2-first'),('bundle','specialization-binding-bundle-final')]:
            binding_path=ROOT/'build/sparkle'/folder/'summary.json';binding,bh=ev.record(binding_path)
            require(binding['status']=='specialized_instances_bound_scope_incomplete' and binding['case']==name,'Production specialization missing')
            require(binding['input_sha256'][str(coverage_path)]==ch,'Production coverage identity differs')
            covered=coverage['cases'][name];assembly=Path(covered['assembly']);ev.direct(assembly,covered['assembly_sha256'])
            require(binding['input_sha256'][str(assembly)]==covered['assembly_sha256'],'Production assembly identity differs')
            _,context=global_directives(assembly)
            actual_modules=selected_modules(assembly,set(MODULE_BY_CASE.values()))
            for module in MODULE_BY_CASE.values():
                bind_module(proven[module],{module:actual_modules[module]},contexts[module],context,module)
                require(covered['modules'][module]['sha256']==mh[module],'Historical DSP helper definition differs')
            folder='specialized-hierarchy-bundle-third' if name=='bundle' else f'specialized-hierarchy-{name}-first'
            hp=ROOT/'build/sparkle'/folder/'summary.json';hierarchy,_=ev.record(hp,binding['input_sha256'][str(hp)],field='inputs')
            require(hierarchy['status']=='elaborated_hierarchy_inventory_complete','Complete production hierarchy missing')
            projections={}
            for case in COUNTS:
                pp=ROOT/'build/sparkle/dsp-occurrence-projection-first'/case/'summary.json'
                require(str(pp) in binding['input_sha256'],'Projection receipt not authenticated by terminal binding')
                projection,ph=ev.record(pp,binding['input_sha256'][str(pp)])
                initialized=initialized_cases[case];leaf=leaf_records[case];module=MODULE_BY_CASE[case]
                require(projection['status']=='passed' and projection['case']==case and projection['module']==module,'Projection helper specialization differs')
                audit_projection_identity(projection['helper_identity'],mh[module],contexts[module][module])
                concrete=projection['concrete_proof']
                require(concrete['summary']==initialized['historical_summary'] and concrete['sha256']==initialized['historical_sha256'] and concrete['state_bits']==BITS[case],'Projection refers to different concrete leaf proof')
                projection_hashes=normalized_hashes(projection['input_sha256'])
                leafdir=Path(initialized['historical_summary']).parent
                require(concrete['proof_log_sha256']==hashes[str(leafdir/'proof.log')],'Projection concrete proof log differs')
                require(projection_hashes[str(assembly)]==covered['assembly_sha256'] and projection_hashes[leaf['dsp_model']]==leaf['dsp_model_sha256'] and
                    projection_hashes[str(leafdir/'DSP48E1.sv')]==hashes[str(leafdir/'DSP48E1.sv')],'Projection assembly/primitive-model identity differs')
                projections[case]={'path':str(pp),'sha256':ph,'record':projection}
            occurrences=production_occurrences(hierarchy,binding,mh,projections)
            report['cases'].append({'name':name,'assembly':str(assembly),'assembly_sha256':covered['assembly_sha256'],
                'specialization_receipt':str(binding_path),'specialization_sha256':bh,'module_sha256':mh,**occurrences})
            checkpoint()
        ev.finish();report.update(status='production_dsp_leaf_initialized_refinements_bound',remaining_obligations=[
            'Mealy cascade dependency composition and dot/controller/RAM initialization',
            'Whole-MXU/board startup and physical device timing/CDC/power-up signoff'])
        checkpoint();digest=archive(summary)
        qualification=output/'qualification.json';save(qualification,{'status':report['status'],'summary_sha256':{str(summary):digest},'cascade_initialized_composition':False});archive(qualification)
    except BaseException as error:
        report.update(status='incomplete',error=repr(error));checkpoint();archive(summary);raise
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(run(args.output)['status'])
