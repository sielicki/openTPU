"""Exact whole-assembly assertion-only refresh for Gen1/Gen2/CLI production.

Retains historical synthesis reachability and qualified scopes by complete token,
attribute and directive equality after only the audited diagnostic relocation.
No current runtime qualification, new behavioral theorem, or physical signoff.
"""
import argparse
from itertools import zip_longest
from pathlib import Path
import re
import signal
import subprocess
import sys

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import bounded_context,require,tokens,global_directives,module_hashes,same_concatenation
from check_sparkle_fp_state_consumers import selected_modules
from qualify_sparkle_specialization_binding import normalized_hashes,save
from sparkle_provenance import archive
from sparkle_compiled_lean import import_closure,run_generator
from check_sparkle_fpga_cli import FPGA_FIELDS,values
from prepare_sparkle_fpga_bundle import named_configuration
import check_sparkle_se_tail_assertion_emission as emission
import check_sparkle_se_tail_product_consumers as product_binding

BINDING=ROOT/'build/sparkle/se-tail-product-consumer-binding-first/summary.json'
BINDING_SHA='6bf841f663c0fb58100e5ce74f54db4abe9a23ccc209e2c11c43c0d96db39950'
CASES=['gen1','gen2','bundle']


def module_spans(path):
    spans={};active=None;pending=None
    for line,token in tokens(path,with_lines=True):
        if pending is not None:
            require(active is None and token not in spans,'Duplicate/nested module')
            active=token;spans[token]=[pending,None];pending=None
        elif token=='module':
            require(active is None,'Nested module');pending=line
        elif token=='endmodule':
            require(active is not None,'Unmatched module end');spans[active][1]=line;active=None
    require(active is None and pending is None,'Incomplete assembly module')
    return spans


def normalize_assembly(source,destination,current):
    """Streaming removal of only exact blocks at the end of named modules."""
    spans=module_spans(source);require('otpu_se_tail_sparkle' in spans,'Production core absent')
    target='otpu_se_tail_sparkle' if current else 'otpu_se_tail'
    block=(emission.CORE_BLOCK if current else emission.OLD_WRAPPER_BLOCK)+'\n'
    expected_lines=block.splitlines(keepends=True);removed=0;line_number=0
    with Path(source).open() as src,Path(destination).open('w') as dst:
        while True:
            line=src.readline()
            if not line:break
            line_number+=1
            inside=target in spans and spans[target][0]<line_number<spans[target][1]
            if inside and line==expected_lines[0]:
                start=line_number;candidate=[line]
                for _ in expected_lines[1:]:candidate.append(src.readline());line_number+=1
                require(candidate==expected_lines,'Changed/extra preprocessor block in diagnostic module')
                require(start+len(expected_lines)==spans[target][1],'Diagnostic not at exact named module end')
                removed+=1;continue
            dst.write(line)
    require(removed==(1 if current or target in spans else 0),'Missing/duplicate expected assertion edit')
    return {'removed_blocks':removed,'module_spans':spans,'target':target}


def exact_whole_assembly(old,new):
    count=0;sentinel=object()
    for a,b in zip_longest(tokens(old),tokens(new),fillvalue=sentinel):
        require(a==b,'Unreviewed whole-assembly token difference at token '+str(count));count+=1
    require(global_directives(old)==global_directives(new),'Assembly directive boundaries/context differ')
    identities=module_hashes(old);require(identities==module_hashes(new),'Complete module/attribute inventory differs')
    return {'token_count':count,'modules':identities,'global_directives_and_contexts_equal':True}


def top_parameters(binding):
    tops=[n for n in binding['nodes'].values() if n['module']=='otpu_fpga_top_ld']
    require(len(tops)==1,'Exact historical top specialization absent')
    parameters=tops[0]['effective_parameters'];require(set(parameters)==set(FPGA_FIELDS),'Complete top parameter inventory differs')
    result=[]
    for name in FPGA_FIELDS:
        bits=parameters[name];require(type(bits)is str and bits and set(bits)<={'0','1'},'Malformed evaluated parameter')
        result.append(int(bits,2))
    require(dict(zip(FPGA_FIELDS,result))['LANES']==8 and dict(zip(FPGA_FIELDS,result))['VPU_CL']==2,'Production lane/composite scope differs')
    return result


def generation_source(output,parameters):
    lines=['import Lean','import OpenTPU.FpgaTopCompleteABI','open OpenTPU','def main : IO Unit := do']
    for name in CASES:
        config='{}' if name=='gen1' else '{pcieGen:=2}' if name=='gen2' else named_configuration(parameters[name])
        lines.extend([f'  let {name} : FpgaTop.Config := {config}',
            f'  IO.FS.writeFile "{output/name}/native.sv" (← IO.ofExcept (FpgaTop.physicalAbiVerilog {name}))',
            f'  IO.FS.writeFile "{output/name}/parameters.json" (Lean.Json.compress (Lean.toJson {name}.parameters))'])
    return '\n'.join(lines)+'\n'


def audit_hierarchy_environment(manifest,assembly,assembly_hash):
    require(set(manifest)=={'sources','root','parameters','terminals','defines'},'Historical hierarchy manifest schema differs')
    require(manifest['root']=='otpu_fpga_top_ld' and manifest['defines']==['SYNTHESIS','YOSYS'],
            'Historical reachability is not in exact synthesis environment')
    selected=[s for s in manifest['sources'] if Path(s['path']).resolve()==Path(assembly).resolve()]
    require(len(selected)==1 and selected[0]['sha256']==assembly_hash and selected[0]['role']=='module',
            'Historical reachability did not consume exact assembly')


def run(emission_path,emission_sha,output):
    bounded_context();require(re.fullmatch('[0-9a-f]{64}',emission_sha) is not None,'Reviewed emission receipt SHA required')
    emission_path=emission_path.resolve();output=output.resolve();require(not output.exists(),'Fresh output required');output.mkdir(parents=True)
    ev=emission.HistoricalEvidence();report={'status':'incomplete','cases':[],
        'current_runtime_qualified':False,'whole_vpu_initialized_equivalence':False,'physical_signoff':False}
    def checkpoint():report['input_sha256']=dict(ev.observed);save(output/'summary.json',report)
    def freeze(path,expected=None):
        h=ev.direct(Path(path),expected);require(archive(Path(path))==h,'Snapshot changed');checkpoint();return h
    def interrupted(signum,frame):raise RuntimeError('Interrupted '+str(signum))
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted);checkpoint()
    def command(name,args):
        path=output/(name+'-command.json');save(path,{'argv':list(map(str,args))});freeze(path);log=output/(name+'.log')
        try:
            with log.open('w') as stream:r=subprocess.run(list(map(str,args)),cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=1800)
        finally:freeze(log)
        require(r.returncode==0,'Incomplete generation command '+name)
    try:
        for m in list(sys.modules.values()):
            p=getattr(m,'__file__',None)
            if p and Path(p).resolve().parent in [ROOT/'tools',Path(__file__).resolve().parent]:freeze(p)
        proof,ph=ev.record(emission_path,emission_sha)
        require(proof['status']=='se_tail_core_assertion_emission_bridge_validated' and proof['config']==[8,7,1] and
                proof['new_core_assertion_trigger_and_message_checked'] is True and proof['production_assemblies_refreshed'] is False,
                'Exact completed emission/synthesis/simulation bridge required')
        require(proof['retained_initialized_product_bits']==89824 and proof['source_counter_extension_bits']==4,
                'Complete emission theorem state inventory differs')
        eh=normalized_hashes(proof['input_sha256'])
        def emission_artifact(path):
            key=str(Path(path).resolve());require(key in eh,'Unbound emission artifact')
            return Path(ev.authenticated[(key,eh[key])])
        for path,h in proof['runner']['source_sha256'].items():
            p=Path(path)
            if p.is_relative_to(ROOT/'OpenTPU') or p.is_relative_to(ROOT.parent/'sparkle'):freeze(p,h)
        current_core=emission_artifact(emission_path.parent/'native.sv')
        core_modules=selected_modules(current_core,emission.MODULES);_,core_context=global_directives(current_core)
        baseline,bh=ev.record(BINDING,BINDING_SHA)
        require(baseline['status']=='se_tail_product_initialized_refinement_bound' and
                [c['name'] for c in baseline['cases']]==CASES,'Historical production applicability missing')
        historical={};parameters={}
        for case in baseline['cases']:
            name=case['name'];bp=Path(case['specialization_receipt']);binding,_=ev.record(bp,case['specialization_sha256'])
            require(binding['status']=='specialized_instances_bound_scope_incomplete' and binding['case']==name,'Historical full specialization binding differs')
            parameters[name]=top_parameters(binding)
            old=Path(case['assembly']);freeze(old,case['assembly_sha256'])
            directory='specialized-hierarchy-bundle-third' if name=='bundle' else f'specialized-hierarchy-{name}-first'
            hp=ROOT/'build/sparkle'/directory/'summary.json'
            hierarchy,hh=ev.record(hp,binding['input_sha256'][str(hp)],field='inputs')
            require(hierarchy['status']=='elaborated_hierarchy_inventory_complete','Historical reached inventory incomplete')
            paths=product_binding.se_tail_occurrences(hierarchy)
            product_binding.bind_reached_specializations(hierarchy,binding,paths,case['module_sha256'])
            require(paths==case['se_tail_paths'],'Historical reached core identities differ')
            mp=ROOT/'build/sparkle/specialized-hierarchy-manifests-first'/f'{name}.json'
            manifest,_=ev.record(mp,hierarchy['inputs'][str(mp)],field=None)
            audit_hierarchy_environment(manifest,old,case['assembly_sha256'])
            require(set(manifest['parameters'])==set(FPGA_FIELDS) and
                    [int(manifest['parameters'][key],2) for key in FPGA_FIELDS]==parameters[name],
                    'Historical root override vector differs from exact evaluated parameters')
            require(len({str(Path(source['path']).resolve()) for source in manifest['sources']})==len(manifest['sources']),
                    'Duplicate ordered historical source unit')
            for source in manifest['sources']:
                p=Path(source['path'])
                if p.resolve()!=old.resolve():freeze(p,source['sha256'])
            historical[name]=(case,binding,hierarchy,hh,manifest)
            (output/name).mkdir()
        generator=output/'Generate.lean';generator.write_text(generation_source(output,parameters));freeze(generator)
        for source in [generator,ROOT/'OpenTPU/Generate.lean']:
            freeze(source)
            for _,path in import_closure(source).values():freeze(path)
        command('build',['lake','build','opentpu-gen','OpenTPU.FpgaTopCompleteABI'])
        runner=run_generator(generator);report['runner']=runner
        for path in [generator.with_suffix(s) for s in ['.runner.json','.c','.c.o','.exe']]+[Path(p) for p in runner['linked_sha256']]:freeze(path)
        if generator.with_suffix('.dependencies.log').exists():freeze(generator.with_suffix('.dependencies.log'))
        binary=ROOT/'.lake/build/bin/opentpu-gen';freeze(binary)
        for suffix in ['.rsp','.trace']:freeze(binary.with_suffix(suffix))
        cli=output/'bundle/cli.sv';command('bundle-cli',[binary,'fpga-top-physical',*[str(v) for v in parameters['bundle']],cli]);freeze(cli)
        same_concatenation(cli,[output/'bundle/native.sv'])
        for name in CASES:
            case,binding,hierarchy,hh,manifest=historical[name];folder=output/name;new=folder/'native.sv';freeze(new)
            param_file=folder/'parameters.json';freeze(param_file)
            import json
            actual=values(json.loads(param_file.read_text()),FPGA_FIELDS)
            require(actual==[str(v) for v in parameters[name]],'Current complete top parameters differ')
            old=Path(case['assembly']);old_normal=folder/'old-normalized.sv';new_normal=folder/'new-normalized.sv'
            old_edits=normalize_assembly(old,old_normal,False);new_edits=normalize_assembly(new,new_normal,True)
            freeze(old_normal);freeze(new_normal)
            correspondence=exact_whole_assembly(old_normal,new_normal)
            current_modules=selected_modules(new,emission.MODULES);_,context=global_directives(new)
            require(current_modules==core_modules and all(context[n]==core_context[n] for n in emission.MODULES),
                    'Actual reached core/helpers differ from independently synthesized/simulated emission')
            require(set(module_hashes(old))==set(module_hashes(new))==set(correspondence['modules']),
                    'Added/removed production module')
            report['cases'].append({'name':name,'old_assembly':str(old),'old_assembly_sha256':case['assembly_sha256'],
                'new_assembly':str(new),'new_assembly_sha256':ev.observed[str(new)],'parameters':actual,
                'historical_specialization_receipt':case['specialization_receipt'],
                'historical_specialization_sha256':case['specialization_sha256'],'historical_hierarchy_sha256':hh,
                'preserved_paths':len(hierarchy['paths']),'preserved_terminals':len(hierarchy['terminals']),
                'se_tail_paths':case['se_tail_paths'],'whole_assembly_correspondence':correspondence,
                'old_wrapper_assertions_removed':old_edits['removed_blocks'],'new_core_assertions_removed_for_comparison':new_edits['removed_blocks'],
                'reachability_scope':'Preserved by complete synthesis-source correspondence under identical SYNTHESIS/YOSYS defines, parameters, unchanged ordered support/vendor units, and no hierarchy edits in the exact diagnostic block',
                'fresh_whole_design_elaboration_claim':False,'current_runtime_qualified':False})
            checkpoint()
        ev.finish();report.update(status='se_tail_assertion_current_assemblies_correspondence_validated',
            emission_bridge={'summary':str(emission_path),'sha256':ph},historical_product_binding_sha256=bh,
            remaining=['Fresh runtime qualification/checkpoint receipts are required',
                       'Historical behavioral gaps, vendor/CDC/physical-signoff scopes remain inherited unchanged'])
        checkpoint();archive(output/'summary.json')
    except BaseException as error:
        report['error']=repr(error);checkpoint();archive(output/'summary.json');raise
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--emission',required=True,type=Path);p.add_argument('--emission-sha256',required=True);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();print(run(a.emission,a.emission_sha256,a.output)['status'])
