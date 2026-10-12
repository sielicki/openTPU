"""Independent bridge for the newly emitted native-core FIFO diagnostic.

Exact8/7/1 generator only. Historical receipts remain immutable; current source
is covered only after this bridge succeeds. Production assemblies must still be
regenerated and bound separately. Focused simulation forces diagnostic operands;
it does not claim legal-traffic reachability or whole-VPU simulation equivalence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import sys

from check_sparkle_fpga_top_complete import bounded_context,require,global_directives,module_hashes
from check_sparkle_fp_state_consumers import selected_modules,log_result
from qualify_sparkle_specialization_binding import Evidence,normalized_hashes,save
from sparkle_provenance import ROOT,ARCHIVE,archive,sha256,verify
from sparkle_compiled_lean import import_closure,run_generator
from audit_sparkle_rtlil_roundtrip import Owners
from prove_sparkle_trace_ports import frontend_plugins
from se_tail_product_inventory import arithmetic_instances

DIAGNOSTIC=ROOT/'build/sparkle/se-tail-diagnostic-sixth/summary.json'
DIAGNOSTIC_SHA='5d0668bf99db1bf039884fbaf2e9101b4c1426b005958096c5a227d51b884a8d'
PRODUCT=ROOT/'build/sparkle/se_tail_product/attempt1/summary.json'
PRODUCT_SHA='e2c3abb46217bfb10e0d74ee5083d715baa06c01b07844d5a0a48e1b056760ec'
MODULES={'otpu_se_tail_sparkle','otpu_se_tail_mul','otpu_se_tail_add'}
GRAPH_MODULES={'otpu_se_tail_sparkle'} | {
    f'otpu_se_tail_{kind}$otpu_se_tail_sparkle.{native}'
    for native,_,kind,_ in arithmetic_instances()}
WRAPPER={'otpu_se_tail'}
CHANGED_SOURCES={ROOT/'OpenTPU/SeTail.lean',ROOT/'OpenTPU/SeTailABI.lean'}
CORE_BLOCK='''`ifndef SYNTHESIS
  always @(posedge clk)
    if (!rst && pe && ((d_pop && dq_n == 0) || (dv && !d_pop && {28'd0, dq_n} == 32'd8)))
      $fatal(1, "otpu_se_tail: d FIFO %s", (d_pop && dq_n == 0) ? "underflow" : "overflow");
`endif'''
OLD_WRAPPER_BLOCK='''`ifndef SYNTHESIS
  always @(posedge clk)
    if(!rst && pe && ((impl.d_pop && impl.dq_n==0) || (impl.dv && !impl.d_pop && impl.dq_n==8)))
      $fatal(1, "otpu_se_tail: d FIFO underflow/overflow");
`endif'''
# rst, init, pe, count, pop, dv, expected fatal reason (None means survive).
STIMULI={
    'underflow':(0,0,1,0,1,0,'underflow'),
    'overflow':(0,0,1,8,0,1,'overflow'),
    'init_underflow':(0,1,1,0,1,0,'underflow'),
    'init_overflow':(0,1,1,8,0,1,'overflow'),
    'disabled_underflow':(0,0,0,0,1,0,None),
    'reset_overflow':(1,0,1,8,0,1,None),
    'empty_idle':(0,0,1,0,0,0,None),
    'full_simultaneous_pop_push':(0,0,1,8,1,1,None),
    'occupied_pop':(0,0,1,3,1,0,None),
    'past_full_exact_predicate':(0,0,1,9,0,1,None),
}


class HistoricalEvidence(Evidence):
    """Pin historical closures to immutable archives before rebuilding objects."""
    def closure(self,hashes):
        for original,digest in hashes.items():
            key=(str((ROOT/original).resolve()),digest)
            if key in self.authenticated:continue
            snapshot=ARCHIVE/digest
            if not snapshot.exists():
                location=verify({original:digest})[original]
                require(archive(ROOT/location)==digest,'Historical snapshot changed')
            require(sha256(snapshot)==digest,'Historical archive identity differs')
            self.direct(snapshot,digest)
            self.authenticated[key]=str(snapshot)


def strip_core_block(text):
    require(text.count(CORE_BLOCK+'\n')==1,'Missing/duplicate/changed exact core diagnostic')
    before,after=text.split(CORE_BLOCK+'\n')
    require(before.count('module otpu_se_tail_sparkle (')==1 and
            before.count('endmodule')==0 and after.startswith('endmodule\n'),
            'Diagnostic is not at the actual core module end')
    require(text.count('otpu_se_tail: d FIFO')==1,'Duplicate FIFO diagnostic process')
    return before+after


def strip_old_wrapper(text):
    require(text.count(OLD_WRAPPER_BLOCK+'\n')==1,'Historical ABI assertion differs')
    return text.replace(OLD_WRAPPER_BLOCK+'\n','',1)


def compare_definitions(old,new,names):
    require(selected_modules(old,names)==selected_modules(new,names),
            'Complete module tokens/attributes differ beyond exact assertion edit')
    require(global_directives(old)==global_directives(new),
            'Incoming module/global directive context differs')


def audit_receipts(diag,product):
    require(diag['status']=='se_tail_four_source_counter_bits_and_fifo_assertion_trigger_parity_proven' and
            diag['config']==[8,7,1] and diag['added_counter_bits']==4 and
            diag['combined_source_state_bits']==89828 and diag['initial_counter_witness']=='0000',
            'Complete actual diagnostic counter theorem differs')
    require(diag['parent_sha256']==PRODUCT_SHA and diag['observed_outputs_and_next_state_defined'] is True and
            diag['sampled_reset_required'] is False and diag['production_assertion_parity'] is False and
            diag['whole_vpu_initialized_equivalence'] is False,'Historical diagnostic scope differs')
    require(set(diag['proofs'])=={'definedness','step_ok','output_ok','observer_ok'} and
            set(diag['mutations'])=={'next','undefined','initial'},'Missing positive or actual mutation evidence')
    require(product['status']=='se_tail_8_7_1_initialized_synthesized_product_refinement_proven' and
            product['config']==[8,7,1] and product['state_bits_per_design']==89824,
            'Retained concrete product theorem differs')


def clean_location_attributes(record):
    """Ignore source-location metadata only; preserve every semantic field."""
    if isinstance(record,list):return [clean_location_attributes(x) for x in record]
    if not isinstance(record,dict):return record
    return {key:({k:clean_location_attributes(v) for k,v in value.items() if k!='src'}
                 if key=='attributes' and isinstance(value,dict) else clean_location_attributes(value))
            for key,value in record.items()}


def graph_inventory(path):
    """Stream every JSON owner, preserving literal net numbers and all init aliases.

    No optimizer or alpha-renaming tolerance: independent extraction must yield
    exact graphs after removing source-location annotations only. Differences
    fail closed. Per-owner digests keep memory independent of the full graph size.
    """
    result={};top_seen=set()
    with Path(path).open() as stream:
        reader=Owners(stream)
        for top in reader.object():
            require(top not in top_seen,'Duplicate top-level graph key');top_seen.add(top)
            if top=='creator':reader.value();continue
            require(top=='modules','Unexpected top-level graph schema')
            for module in reader.object():
                require(module not in result,'Duplicate graph module')
                groups={};dff_bits=0;init_alias_bits=0
                for category in reader.object():
                    require(category not in groups,'Duplicate module graph category')
                    require(category in {'attributes','parameter_default_values','ports','cells','netnames','memories'},
                            'Unknown module graph category: '+category)
                    if category in ['attributes','parameter_default_values']:
                        value=reader.value()
                        if category=='attributes':value={k:v for k,v in value.items() if k!='src'}
                        groups[category]=value;continue
                    owners={}
                    for name in reader.object():
                        require(name not in owners,'Duplicate graph owner')
                        value=reader.value();canonical=clean_location_attributes(value)
                        blob=json.dumps(canonical,sort_keys=True,separators=(',',':')).encode()
                        owners[name]=hashlib.sha256(blob).hexdigest()
                        if category=='cells' and value['type']=='$dff':
                            c=value['connections'];require(len(c['Q'])==len(c['D'])==int(value['parameters']['WIDTH'],2),
                                                           'Malformed actual DFF in emission graph')
                            dff_bits+=len(c['Q'])
                        if category=='netnames' and 'init' in value.get('attributes',{}):
                            require(len(value['bits'])==len(value['attributes']['init']),'Malformed initializer alias')
                            init_alias_bits+=len(value['bits'])
                    groups[category]=owners
                result[module]={'categories':groups,'dff_bits':dff_bits,'init_alias_bits':init_alias_bits}
        reader.whitespace();require(reader.eof and reader.pos==len(reader.buf),'Trailing graph data')
    require(top_seen=={'creator','modules'} and set(result)==GRAPH_MODULES,'Complete native graph module set differs')
    return result


def input_connections(text):
    require(text.count('module otpu_se_tail_sparkle (')==1,'Core header missing')
    header=text.split('module otpu_se_tail_sparkle (',1)[1].split(');',1)[0]
    ports={}
    for line in header.splitlines():
        if not line.strip():continue
        match=re.fullmatch(r'\s*(input|output) logic(?: \[([0-9]+):0\])? ([A-Za-z0-9_]+),?\s*',line)
        require(match is not None,'Unexpected actual core port declaration')
        direction,msb,name=match.groups();require(name not in ports,'Duplicate core port')
        ports[name]=(direction,int(msb)+1 if msb else 1)
    require(all(ports.get(name)==('input',1) for name in ['clk','rst','init','pe']),
            'Diagnostic external pin contract differs')
    return {name:(name if name in ['clk','rst','init','pe'] else "'0")
            for name,(direction,_) in ports.items() if direction=='input'}


def testbench(core):
    connections=input_connections(core)
    rows=['`timescale 1ns/1ps','module tb;','logic clk=0,rst=0,init=0,pe=0;',
          'logic [3:0] injected_count; logic injected_pop,injected_dv; integer case_id;',
          'otpu_se_tail_sparkle dut('+','.join('.'+n+'('+v+')' for n,v in connections.items())+');',
          'initial begin',"if (!$value$plusargs(\"CASE=%d\",case_id)) $fatal(1,\"missing diagnostic case\");",
          'case (case_id)']
    for index,(_,values) in enumerate(STIMULI.items()):
        rst,init,pe,count,pop,dv,_=values
        rows.append(f'{index}: begin rst={rst}; init={init}; pe={pe}; injected_count=4\'d{count}; injected_pop={pop}; injected_dv={dv}; end')
    rows+=['default: $fatal(1,"unknown diagnostic case");','endcase',
           '#1; force dut.dq_n=injected_count; force dut.d_pop=injected_pop; force dut.dv=injected_dv;',
           '#1; $display("DIAGNOSTIC_FIXTURE case=%0d",case_id); clk=1;',
           '#1; $display("DIAGNOSTIC_SURVIVED case=%0d",case_id); $finish;','end','endmodule']
    return '\n'.join(rows)+'\n'


def audit_simulation(index,reason,result,text):
    require(f'DIAGNOSTIC_FIXTURE case={index}' in text,'Simulation did not reach actual diagnostic fixture')
    if reason is None:
        require(result==0 and f'DIAGNOSTIC_SURVIVED case={index}' in text and
                'otpu_se_tail: d FIFO' not in text,'Unexpected diagnostic or incomplete safe case')
    else:
        # The original ternary is a nine-byte packed string: its eight-byte
        # "overflow" arm is left-padded when Verilator formats %s.
        message='otpu_se_tail: d FIFO '+(' ' if reason=='overflow' else '')+reason
        require(result in [-6,134,1] and message in text and
                'DIAGNOSTIC_SURVIVED' not in text and 'underflow/overflow' not in text,
                'Actual assertion trigger/message not observed')
        if result==1:
            require('%Fatal:' in text and 'Assertion failed in tb.dut:' in text and
                    'Verilog $stop' in text and 'Aborting...' in text,
                    'Exit one lacks actual core fatal termination transcript')
        other='overflow' if reason=='underflow' else 'underflow'
        require(re.search(r'otpu_se_tail: d FIFO +'+other+r'(?:\n|$)',text) is None,
                'Wrong or duplicate diagnostic reason')


def main(output):
    bounded_context();output=output.resolve();require(not output.exists(),'Fresh bridge output required');output.mkdir(parents=True)
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    evidence=HistoricalEvidence();report={'status':'incomplete','config':[8,7,1],
        'production_assemblies_refreshed':False,'whole_vpu_initialized_equivalence':False,'simulation':{}}
    def checkpoint():report['input_sha256']=dict(evidence.observed);save(output/'summary.json',report)
    def freeze(path,expected=None):
        digest=evidence.direct(Path(path),expected);require(archive(Path(path))==digest,'Artifact changed during archive');checkpoint();return digest
    def interrupted(signum,frame):raise RuntimeError('Interrupted '+str(signum))
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted);checkpoint()
    def run(name,args,timeout=1200):
        log=output/(name+'.log');command=output/(name+'-command.json');save(command,{'argv':list(map(str,args)),'cwd':str(ROOT)});freeze(command)
        try:
            with log.open('w') as stream:result=subprocess.run(list(map(str,args)),cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=timeout)
        finally:freeze(log)
        return result.returncode,log
    try:
        for module in list(sys.modules.values()):
            path=getattr(module,'__file__',None)
            if path and Path(path).resolve().parent==ROOT/'tools':freeze(path)
        diag,diag_sha=evidence.record(DIAGNOSTIC,DIAGNOSTIC_SHA)
        product,product_sha=evidence.record(PRODUCT,PRODUCT_SHA);audit_receipts(diag,product)
        all_hashes=normalized_hashes(diag['input_sha256'])
        for name,digest in normalized_hashes(product['input_sha256']).items():
            require(name not in all_hashes or all_hashes[name]==digest,'Conflicting historical artifact identity');all_hashes[name]=digest
        def artifact(path):
            key=str(Path(path).resolve());require(key in all_hashes,'Unauthenticated historical artifact')
            return Path(evidence.authenticated[(key,all_hashes[key])])
        for prop,path in diag['proofs'].items():log_result(artifact(path).read_text(),False)
        for name in ['next','undefined']:log_result(artifact(diag['mutations'][name]['log']).read_text(),True)
        # Historical sources stay archived. Explicitly permit only the two reviewed
        # Lean changes; unaffected live Lean/RTL sources must retain their identity.
        for name,digest in all_hashes.items():
            path=Path(name)
            if path not in CHANGED_SOURCES and ((path.suffix=='.lean' and path.is_relative_to(ROOT/'OpenTPU')) or
                                                (path.suffix=='.sv' and path.is_relative_to(ROOT/'rtl'))):freeze(path,digest)
        for path in CHANGED_SOURCES:freeze(path)
        report['historical']={'diagnostic_sha256':diag_sha,'product_sha256':product_sha,
            'changed_live_sources':[str(p) for p in sorted(CHANGED_SOURCES)]};checkpoint()
        generator=output/'Generate.lean';native=output/'native.sv';wrapper=output/'wrapper.sv'
        generator.write_text('import OpenTPU.SeTailABI\ndef main : IO Unit := do\n'+
            '  let c : OpenTPU.SeTail.Config := {lanes := 8, inputLatency := 7, treeDelay := 1}\n'+
            '  let rtl ← match OpenTPU.SeTail.toVerilog c with\n    | .ok value => pure value\n    | .error error => throw (IO.userError error)\n'+
            f'  IO.FS.writeFile "{native}" rtl\n  IO.FS.writeFile "{wrapper}" (OpenTPU.SeTail.wrapper c)\n')
        for path in [generator,*[p for _,p in import_closure(generator).values()]]:freeze(path)
        code,_=run('build',['lake','build','opentpu-gen','OpenTPU.SeTailABI']);require(code==0,'Fresh native build incomplete')
        report['runner']=run_generator(generator)
        for path in [generator.with_suffix(s) for s in ['.runner.json','.c','.c.o','.exe']]+[Path(p) for p in report['runner']['linked_sha256']]:freeze(path)
        for path in [native,wrapper]:freeze(path)
        stripped=output/'new-core-without-assertion.sv';stripped.write_text(strip_core_block(native.read_text()));freeze(stripped)
        old_native=artifact(PRODUCT.parent/'none.sv');compare_definitions(old_native,stripped,MODULES)
        require(module_hashes(old_native)==product['native_module_hashes'],'Historical full module identities differ')
        old_wrapper=artifact(DIAGNOSTIC.parent/'native-wrapper.sv')
        old_stripped=output/'old-wrapper-without-assertion.sv';old_stripped.write_text(strip_old_wrapper(old_wrapper.read_text()));freeze(old_stripped)
        require('otpu_se_tail: d FIFO' not in wrapper.read_text(),'Duplicate current wrapper assertion')
        compare_definitions(old_stripped,wrapper,WRAPPER)
        report['token_bridge']={'modules':sorted(MODULES),'complete_body_attributes_and_directives':True,
                               'wrapper_duplicate_removed':True,'new_module_hashes':module_hashes(native)};checkpoint()
        yosys=Path(shutil.which('yosys')).resolve();freeze(yosys)
        code,log=run('frontend',[yosys,'-Q','-T','-p','plugin -l; help read_slang']);require(code==0,'Frontend help failed')
        for path in frontend_plugins(log.read_text()):freeze(path)
        graphs={}
        for label,source in [('old',old_native),('new',native)]:
            target=output/(label+'-synthesis.json');script=output/(label+'-synthesis.ys')
            script.write_text(f'read_slang --keep-hierarchy -D SYNTHESIS --top otpu_se_tail_sparkle {source}\nproc\nwrite_json {target}\n');freeze(script)
            code,_=run(label+'-synthesis',[yosys,'-Q','-T','-s',script]);require(code==0,'Independent pre-clean synthesis extraction failed')
            freeze(target);graphs[label]=graph_inventory(target)
            inventory=output/(label+'-graph-inventory.json');save(inventory,graphs[label]);freeze(inventory)
        require(graphs['old']==graphs['new'],'Complete pre-clean synthesis graph/init correspondence failed')
        report['synthesis_bridge']={'all_modules_cells_ports_nets_memories_initializers_equal':True,
            'ignored_metadata':['creator','attributes.src'],
            'module_counts':{name:{key:graphs['new'][name][key] for key in ['dff_bits','init_alias_bits']} for name in GRAPH_MODULES}}
        del graphs;checkpoint()
        verilator=Path(shutil.which('verilator')).resolve();freeze(verilator)
        for tool in ['make','c++']:
            path=shutil.which(tool);require(path is not None,'Missing native simulation build tool');freeze(Path(path).resolve())
        code,_=run('verilator-version',[verilator,'--version']);require(code==0,'Simulation tool version failed')
        bench=output/'tb.sv';bench.write_text(testbench(native.read_text()));freeze(bench);obj=output/'obj'
        code,_=run('simulation-build',[verilator,'--binary','--timing','-j','1','-Wno-fatal','--top-module','tb','--Mdir',obj,native,bench])
        require(code==0,'Actual emitted core simulation build failed')
        for path in sorted(obj.rglob('*')):
            if path.is_file():freeze(path)
        binary=obj/'Vtb';require(binary.is_file(),'Missing actual simulation binary')
        for index,(name,values) in enumerate(STIMULI.items()):
            code,log=run('simulation-'+name,[binary,'+CASE='+str(index)],timeout=30)
            audit_simulation(index,values[-1],code,log.read_text())
            report['simulation'][name]={'returncode':code,'expected_reason':values[-1],'stimulus':list(values[:-1]),'log':str(log)};checkpoint()
        evidence.finish();report.update(status='se_tail_core_assertion_emission_bridge_validated',
            new_core_assertion_trigger_and_message_checked=True,
            retained_initialized_product_bits=89824,source_counter_extension_bits=4,
            remaining=['Regenerate and independently bind current production assemblies and runtime checkpoints',
                       'Four-state/event-order equivalence and whole-VPU/board initialized composition remain separate'])
        checkpoint();archive(output/'summary.json')
    except BaseException as error:
        report['error']=repr(error);checkpoint();archive(output/'summary.json');raise
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    print(main(parser.parse_args().output)['status'])
