"""Unexecuted four-bit SE-tail source counter extension and FIFO observer proof.

Exact8/7/1 only. Actual authenticated pre-clean Q/D cone; no handwritten next
state. FIFO observer binds the existing simulation-only SeTailABI assertion.
Parent89824-bit theorem stays separate; this adds four diagnostic source bits.
"""
import argparse
import copy
import json
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3] if Path(__file__).parent.name=='se_tail_diagnostic_draft' else Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import bounded_context,require
from qualify_sparkle_specialization_binding import Evidence,normalized_hashes,save
from sparkle_provenance import archive
from sparkle_transition import expose_steps
from prove_sparkle_fp_state import initial_bits
from prove_sparkle_vtree_product import concrete_counterexample
from sparkle_compiled_lean import run_generator,import_closure

OLD=ROOT/'build/sparkle/formal_se_tail/8_7_1'
PARENT_SHA256='e2c3abb46217bfb10e0d74ee5083d715baa06c01b07844d5a0a48e1b056760ec'
BOUNDARIES={'warm':8,'ub_q':273,'dv_5':1}
INPUTS={'clk':1,'rst':1,'init':1,'pe':1}
COMBINATIONAL={'$buf','$mux','$pmux','$bmux','$eq','$ne','$eqx','$add','$sub','$not','$neg',
    '$logic_not','$logic_and','$logic_or','$and','$or','$xor','$xnor','$reduce_and',
    '$reduce_or','$reduce_xor','$reduce_bool','$lt','$le','$gt','$ge','$shl','$shr','$sshr'}
ASSERTION='''`ifndef SYNTHESIS
  always_ff @(posedge clk)
    if (!rst && pe && ((d_pop && dq_n == 0) || (dv && !d_pop && 32'(dq_n) == DFD)))
      $fatal(1, "otpu_se_tail: d FIFO %s", (d_pop && dq_n == 0) ? "underflow" : "overflow");
`endif'''
NATIVE_ASSERTION='''`ifndef SYNTHESIS
  always @(posedge clk)
    if(!rst && pe && ((impl.d_pop && impl.dq_n==0) || (impl.dv && !impl.d_pop && impl.dq_n==8)))
      $fatal(1, "otpu_se_tail: d FIFO underflow/overflow");
`endif'''

def audit_assertion(source):
    require(source.count(ASSERTION)==1,'Exact original FIFO assertion predicate/guard differs')
    # Static source bounds bind the observer's8-entry fullness constant. A
    # different spelling fails closed until the exact source is reviewed.
    require(len(re.findall(r'\bDFD\s*=\s*8\s*;',source))==1,'FIFO depth source anchor differs')
    return {'predicate':"!rst && pe && ((d_pop && dq_n==0) || (dv && !d_pop && dq_n==8))",
        'arithmetic':'Four-bit unsigned occupancy; original fullness casts to32bits',
        'init_is_not_a_diagnostic_mask':True,'source_guard':'ifndef SYNTHESIS',
        'native_observer':'Existing simulation-only ABI assertion over actual native internal state/signals'}

def audit_native_wrapper(text):
    require(text.count(NATIVE_ASSERTION)==1,'Existing native ABI FIFO assertion differs')
    require(text.count('parameter int LANES=8, TA=7, QD=1')==1,'Native ABI specialization differs')
    require(text.count('otpu_se_tail_sparkle impl(.clk,.rst,.init,')==1,'Native assertion/core instance bridge differs')
    require(len(re.findall(r'\bimpl\.dq_n\b',text))==2 and len(re.findall(r'\bimpl\.d_pop\b',text))==2 and
            len(re.findall(r'\bimpl\.dv\b',text))==1,'Additional native diagnostic alias/use differs')
    require(text.count('always @(posedge clk)')==1,'Native assertion clock differs')
    return {'trigger_equivalence':'Two-state sampled predicate equality for existing original and generated native wrapper assertions',
        'native_has_existing_assertion':True,'message_equivalence':False,
        'message_difference':'Original chooses underflow or overflow; native currently emits generic underflow/overflow text'}

def qd(module):
    result={};owners={}
    for name,cell in module['cells'].items():
        if cell['type']!='$dff':continue
        c=cell['connections']
        require(cell['port_directions']=={'CLK':'input','D':'input','Q':'output'},'DFF pin directions differ')
        require(c['CLK']==module['ports']['clk']['bits'] and int(cell['parameters']['CLK_POLARITY'],2)==1,'DFF clock differs')
        require(len(c['Q'])==len(c['D'])==int(cell['parameters']['WIDTH'],2),'Malformed D/Q')
        for q,d in zip(c['Q'],c['D']):
            require(type(q)is int and q not in result,'Multiply driven/constant Q')
            result[q]=d;owners[q]=name
    return result,owners

def identity_bridge(module,output,source):
    """Prove an actual ordered endpoint connection through identity $bufs only."""
    require(len(output)==len(source)>0 and len(set(output))==len(output) and
            len(set(source))==len(source) and all(type(b)is int for b in output+source),
            'Malformed identity bridge endpoints')
    drivers={}
    for name,port in module['ports'].items():
        if port['direction']=='input':
            for bit in port['bits']:
                require(type(bit)is int and bit not in drivers,'Ambiguous bridge input driver')
                drivers[bit]=None
    for name,cell in module['cells'].items():
        require(set(cell['connections'])==set(cell['port_directions']),'Bridge cell directions missing')
        for port,bits in cell['connections'].items():
            require(cell['port_directions'][port] in ['input','output'],'Unsupported bridge pin direction')
            if cell['port_directions'][port]!='output':continue
            for bit in bits:
                require(type(bit)is int and bit not in drivers,'Ambiguous bridge cell driver')
                drivers[bit]=(name,port)
    traversed=set()
    for final,expected in zip(output,source):
        bit=final;seen=set()
        while bit!=expected:
            require(bit not in seen and bit in drivers and drivers[bit] is not None,
                    'Identity bridge cyclic, missing or externally driven')
            seen.add(bit);name,port=drivers[bit];cell=module['cells'][name]
            require(cell['type']=='$buf' and set(cell['parameters'])=={'WIDTH'} and
                    cell['port_directions']=={'A':'input','Y':'output'} and port=='Y',
                    'Nonidentity cell on endpoint bridge')
            connections=cell['connections'];width=int(cell['parameters']['WIDTH'],2)
            require(width>0 and len(connections['A'])==len(connections['Y'])==width and
                    all(type(b)is int for b in connections['A']+connections['Y']) and
                    len(set(connections['Y']))==width,'Malformed identity buffer')
            bit=connections['A'][connections['Y'].index(bit)];traversed.add(name)
        require(expected in drivers,'Missing bridge source driver')
    return sorted(traversed)

def boundaries(graph,side):
    module=graph['modules'][side];state,_=qd(module)
    result={name:module['netnames'][name]['bits'][:] for name in ['warm','ub_q']}
    for name,width in [('warm',8),('ub_q',273)]:
        require(len(result[name])==width and set(result[name])<=set(state),'Actual parent boundary is not complete Q: '+name)
    dv=module['netnames']['dv']['bits']
    if side=='gate':
        result['dv_5']=module['netnames']['dv_5']['bits'][:]
        require(len(result['dv_5'])==1 and set(result['dv_5'])<=set(state),
                'Native mapped dv_5 is not actual Q')
        identity_bridge(module,dv,result['dv_5'])
    else:
        instance=module['cells']['u_dv'];leaf=graph['modules'][instance['type']]
        require(instance['connections']['q']==dv and instance['connections']['clk']==module['ports']['clk']['bits'],
                'Original dv endpoint/root clock bridge differs')
        require(instance['connections']['en']==module['ports']['pe']['bits'],'Original dv enable bridge differs')
        require(instance['port_directions']['q']=='output' and instance['port_directions']['clk']=='input' and instance['port_directions']['en']=='input','Original dv pin directions differ')
        endpoint=leaf['netnames']['g_regs.qr']['bits'];leafstate,_=qd(leaf)
        require(len(endpoint)==1 and set(endpoint)<=set(leafstate),
                'Original dv endpoint is not mapped u_dv.g_regs.qr Q')
        require(leaf['ports']['q']['direction']=='output','Original dv leaf endpoint direction differs')
        identity_bridge(leaf,leaf['ports']['q']['bits'],endpoint)
        result['dv_5']=dv[:]
    require(len(result['dv_5'])==1,'dv endpoint width differs')
    flattened=[b for values in result.values() for b in values]
    require(len(flattened)==len(set(flattened))==282,'Boundary aliases overlap')
    return result

def project(graph,side,allow_x=False):
    """Extract actual counter Q/D plus combinational d_pop/dv cones only.

    All other state is cut only at independently named parent correspondence
    boundaries. Unknown inputs, memory/arithmetic/opaque cells, unsupported
    operators, ambiguous drivers, X/Z or other state dependencies fail closed.
    """
    module=graph['modules'][side];state,owners=qd(module)
    counter=module['netnames']['dq_n']['bits'][:]
    require(len(counter)==len(set(counter))==4 and set(counter)<=set(state),'Missing actual four-bit diagnostic counter')
    bounds=boundaries(graph,side)
    inbits={name:module['ports'][name]['bits'][:] for name in INPUTS}
    for name,width in INPUTS.items():
        require(module['ports'][name]['direction']=='input' and len(inbits[name])==width,'External cone input mismatch')
    stopbits=[b for values in [*bounds.values(),*inbits.values(),counter] for b in values]
    require(all(type(b)is int for b in stopbits) and len(stopbits)==len(set(stopbits)),'Cone state/input overlap')
    stops=set(stopbits);drivers={}
    for name,cell in module['cells'].items():
        require(set(cell['connections'])==set(cell['port_directions']),'Missing actual pin directions')
        for p,values in cell['connections'].items():
            if cell['port_directions'][p]!='output':continue
            for bit in values:
                if type(bit)is not int:continue
                require(bit not in drivers,'Ambiguous actual cone driver')
                drivers[bit]=name
    chosen=set();visited=set();active=set();unknowns=[]
    def visit(bit,path=()):
        if bit in ('0','1') or bit in visited or bit in stops:return
        if bit=='x' and allow_x:
            unknowns.append({'literal':'x','path':list(path)})
            return
        require(type(bit)is int,'X/Z in diagnostic cone: side='+side+' literal='+repr(bit)+
                ' path='+' -> '.join(path))
        require(bit not in active and bit in drivers,'Cyclic or undriven cone')
        require(bit not in state,'Unmapped parent state dependency')
        active.add(bit);name=drivers[bit];cell=module['cells'][name]
        require(cell['type'] in COMBINATIONAL,'Unexpected memory/FP/hierarchical dependency: '+name)
        chosen.add(name)
        for port,values in cell['connections'].items():
            if cell['port_directions'][port]=='input':
                for index,value in enumerate(values):visit(value,(*path,name+':'+cell['type']+'.'+port+'['+str(index)+']'))
        active.remove(bit);visited.add(bit)
    actual_outputs={'count':counter,'d_pop':module['netnames']['d_pop']['bits'][:],
                    'dv':module['netnames']['dv']['bits'][:]}
    require(len(actual_outputs['d_pop'])==len(actual_outputs['dv'])==1,'Diagnostic operand width differs')
    for index,q in enumerate(counter):visit(state[q],('dq_n.D['+str(index)+']',))
    for output in ['d_pop','dv']:
        for index,bit in enumerate(actual_outputs[output]):visit(bit,(output+'['+str(index)+']',))
    flops={owners[q] for q in counter}
    require({b for name in flops for b in module['cells'][name]['connections']['Q']}==set(counter),'Counter flop includes unmapped Q bits')
    chosen|=flops
    ports={name:{'direction':'input','bits':bits} for name,bits in inbits.items()}
    ports.update({'parent_'+name:{'direction':'input','bits':bits} for name,bits in bounds.items()})
    ports.update({name:{'direction':'output','bits':bits} for name,bits in actual_outputs.items()})
    cells={name:copy.deepcopy(module['cells'][name]) for name in chosen}
    # All original init aliases are audited first. Project only their counter
    # constraints; parent boundary initial predicates belong to the parent proof.
    init=initial_bits(module);counter_init={q:init[q] for q in counter if q in init}
    names={name:{'hide_name':0,'bits':port['bits'][:],'attributes':{}} for name,port in ports.items()}
    names['dq_n']={'hide_name':0,'bits':counter,'attributes':{'init':''.join(reversed([counter_init.get(q,'x') for q in counter]))}}
    result={'attributes':{},'ports':ports,'netnames':names,'cells':cells}
    return result,{'counter_bits':4,'parent_boundaries':{n:len(v) for n,v in bounds.items()},
        'original_counter_Q':counter,'original_counter_D':[state[q] for q in counter],
        'selected_actual_cells':sorted(chosen),'initial_bits_msb_first':names['dq_n']['attributes']['init'],
        'preserved_x_occurrences':unknowns,
        'scope':'Actual Q/D and signal cones; only282 parent state bits and four external pins are cut'}

def normalize_buffers(module):
    """Exact local identity $buf(A) -> unsigned $or(A,zero), including X."""
    result=copy.deepcopy(module);changed=[]
    for name,cell in result['cells'].items():
        if cell['type']!='$buf':continue
        require(set(cell['parameters'])=={'WIDTH'} and cell['port_directions']=={'A':'input','Y':'output'} and
                set(cell['connections'])=={'A','Y'},'Malformed projected buffer')
        bits=cell['parameters']['WIDTH'];width=int(bits,2);c=cell['connections']
        require(width>0 and len(c['A'])==len(c['Y'])==width and all(type(b)is int for b in c['Y']) and
                len(set(c['Y']))==width and all(type(b)is int or b in ['0','1','x'] for b in c['A']),
                'Malformed projected buffer widths/bits')
        cell.update(type='$or',parameters={'A_SIGNED':'0','B_SIGNED':'0','A_WIDTH':bits,'B_WIDTH':bits,'Y_WIDTH':bits},
            port_directions={'A':'input','B':'input','Y':'output'},connections={'A':c['A'],'B':['0']*width,'Y':c['Y']})
        changed.append(name)
    require(result['ports']==module['ports'] and result['netnames']==module['netnames'] and
            qd(result)==qd(module) and initial_bits(result)==initial_bits(module),
            'Buffer normalization changed state, aliases or interface')
    return result,sorted(changed)

def sat_command(prop,model,definedness=False):
    if definedness:theorem='-set-any-undef observed -prove impossible 1'
    else:
        require(prop in ['step_ok','output_ok','observer_ok'],'Unknown property')
        theorem='-prove '+prop+' 1'
    return 'sat -enable_undef -set-def-inputs '+theorem+' -verify -show-inputs -show-outputs -dump_json '+str(model)+'\n'

def undefined_counterexample(path):
    concrete_counterexample(path,'impossible')
    with path.open() as stream:record=json.load(stream)
    found=[s for s in record['signal'] if s['name']=='observed']
    require(len(found)==1,'Missing observed undefinedness model')
    item=found[0];wave=item.get('wave','');data=item.get('data',[])
    require(wave.startswith('x') or (wave.startswith('=') and type(data)is list and
            len(data)>0 and type(data[0])is str and 'x' in data[0].lower()),
            'Definedness counterexample has no observed X')

def counter_witness(raw):
    maps={s:initial_bits(m) for s,m in raw['modules'].items()};values=[]
    for g,n in zip(raw['modules']['gold']['netnames']['dq_n']['bits'],raw['modules']['gate']['netnames']['dq_n']['bits']):
        require(n in maps['gate'],'Native counter init unspecified')
        require(g not in maps['gold'] or maps['gold'][g]==maps['gate'][n],'Initial counter constraints conflict')
        values.append(maps['gate'][n])
    return ''.join(reversed(values))

def hardware_fault(module,fault):
    """Change actual projected counter D or initializer, never a miter output."""
    changed=copy.deepcopy(module);counter=changed['netnames']['dq_n']['bits']
    if fault=='initial':
        attrs=changed['netnames']['dq_n']['attributes'];require(attrs['init']=='0000','Native counter initial target differs')
        attrs['init']='0001'
    elif fault in ['next','undefined']:
        target=[c for c in changed['cells'].values() if c['type']=='$dff' and counter[0] in c['connections']['Q']]
        require(len(target)==1,'Counter mutation Q driver differs')
        cell=target[0];offset=cell['connections']['Q'].index(counter[0]);old=cell['connections']['D'][offset]
        if fault=='undefined':
            cell['connections']['D'][offset]='x'
            return changed
        bits=[b for c in changed['cells'].values() for values in c['connections'].values() for b in values if type(b)is int]
        bit=max(bits)+1;cell['connections']['D'][offset]=bit
        require('diagnostic_fault_not' not in changed['cells'],'Mutation name collision')
        changed['cells']['diagnostic_fault_not']={'type':'$not','parameters':{'A_SIGNED':'0','A_WIDTH':'1','Y_WIDTH':'1'},
            'port_directions':{'A':'input','Y':'output'},'connections':{'A':[old],'Y':[bit]},'attributes':{}}
    else:raise ValueError('Unknown actual cone fault')
    return changed

def harness():
    lines=['module check(input clk,rst,init,pe,input [7:0] parent_warm,input [272:0] parent_ub_q,input parent_dv_5,input [3:0] state_dq_n,output step_ok,output_ok,observer_ok,output [21:0] observed,output impossible);']
    for side in ['gold','gate']:
        lines += [f'wire [3:0] {side}_next,{side}_count; wire {side}_pop,{side}_dv;',
            f'{side} u_{side}(.clk(clk),.rst(rst),.init(init),.pe(pe),.parent_warm(parent_warm),.parent_ub_q(parent_ub_q),.parent_dv_5(parent_dv_5),.state_dq_n(state_dq_n),.next_dq_n({side}_next),.count({side}_count),.d_pop({side}_pop),.dv({side}_dv));',
            f"wire {side}_fault=!rst && pe && (({side}_pop && {side}_count==4'd0) || ({side}_dv && !{side}_pop && {{28'd0,{side}_count}}==32'd8));"]
    lines += ['assign step_ok=(gold_next==gate_next);',
        'assign output_ok=(gold_count==gate_count)&&(gold_pop==gate_pop)&&(gold_dv==gate_dv);',
        'assign observer_ok=(gold_fault==gate_fault);',
        'assign observed={gold_next,gold_count,gold_pop,gold_dv,gold_fault,gate_next,gate_count,gate_pop,gate_dv,gate_fault};',
        "assign impossible=1'b0;",'endmodule']
    return '\n'.join(lines)+'\n'

def main(parent_path,output):
    bounded_context();parent_path=parent_path.resolve();output=output.resolve();require(not output.exists(),'Fresh output required');output.mkdir(parents=True)
    ev=Evidence();report={'status':'incomplete','config':[8,7,1],'added_counter_bits':4,
        'whole_vpu_initialized_equivalence':False,'proofs':{},'mutations':{}}
    summary=output/'summary.json'
    def checkpoint():report['input_sha256']=ev.observed;save(summary,report)
    def freeze(path):ev.direct(path);archive(path);checkpoint()
    checkpoint()
    def interrupted(signum,frame):raise RuntimeError('Interrupted '+str(signum))
    signal.signal(signal.SIGTERM,interrupted)
    try:
        for module in list(sys.modules.values()):
            path=getattr(module,'__file__',None)
            if path and Path(path).resolve().parent==ROOT/'tools':freeze(Path(path))
        freeze(Path(__file__).resolve())
        parent,ph=ev.record(parent_path,PARENT_SHA256)
        require(parent['status']=='se_tail_8_7_1_initialized_synthesized_product_refinement_proven' and parent['config']==[8,7,1] and parent['state_bits_per_design']==89824,'Complete retained parent product missing')
        require(parent['parent_bits']==82820 and parent['concrete_fp_bits']==7004 and parent['arbitrary_shared_ram_bits']==76160,'Parent complete state scope differs')
        hashes=normalized_hashes(parent['input_sha256'])
        def artifact(path):
            key=str(Path(path).resolve());require(key in hashes,'Unauthenticated cone source')
            return Path(ev.authenticated[(key,hashes[key])])
        source=ROOT/'rtl/vpu/otpu_se_tail.sv';ev.direct(source,hashes[str(source)])
        report['observer_contract']=audit_assertion(source.read_text())
        generator=output/'Wrapper.lean';wrapper=output/'native-wrapper.sv'
        generator.write_text('import OpenTPU.SeTailABI\ndef main : IO Unit :=\n'+
            f'  IO.FS.writeFile "{wrapper}" (OpenTPU.SeTail.wrapper {{lanes := 8, inputLatency := 7, treeDelay := 1}})\n')
        for path in [generator,*[p for _,p in import_closure(generator).values()]]:freeze(path)
        with (output/'wrapper-build.log').open('w') as stream:
            subprocess.run(['lake','build','OpenTPU.SeTailABI'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        freeze(output/'wrapper-build.log');report['wrapper_runner']=run_generator(generator)
        for path in [generator.with_suffix(s) for s in ['.runner.json','.c','.c.o','.exe']]+[Path(p) for p in report['wrapper_runner']['linked_sha256']]:freeze(path)
        freeze(wrapper);report['native_wrapper_contract']=audit_native_wrapper(wrapper.read_text())
        # The parent product authenticates this exact hierarchy/native graph,
        # validates its complete transformations and matches fresh compiled code.
        with artifact(OLD/'hierarchy.json').open() as stream:graph=json.load(stream)
        raw={'modules':{}};audits={}
        for side in ['gold','gate']:raw['modules'][side],audits[side]=project(graph,side,allow_x=True)
        del graph
        init=counter_witness(raw);require(init=='0000','Unexpected native counter base; review scope')
        parent_witness=parent['parent']['initialization_witness']
        for field,width in BOUNDARIES.items():require(field in parent_witness and len(parent_witness[field])==width,'Actual boundary absent from complete parent witness')
        report.update(parent_summary=str(parent_path),parent_sha256=ph,projection=audits,initial_counter_witness=init,
            parent_boundary_relation='All named parent boundary bits are equal in authenticated complete retained product')
        yosys=Path(shutil.which('yosys')).resolve();freeze(yosys)
        for fault in ['none','next','undefined','initial']:
            variant=copy.deepcopy(raw)
            if fault!='none':variant['modules']['gate']=hardware_fault(variant['modules']['gate'],fault)
            original=output/(fault+'-counter.json');save(original,variant);freeze(original)
            if fault=='initial':
                # Reference is unspecified, so native1 still admits an equal
                # reference witness! This is a guard that such a change must NOT
                # be mislabeled as an initialization mismatch.
                require(counter_witness(variant)=='0001','Changed native counter witness not respected')
                report['mutations'][fault]={'status':'accepted_as_valid_reference_witness','scope':'Native counter initializer alone is not an equivalence-breaking fault because reference initial state is unspecified'}
                continue
            conversions={}
            for side in ['gold','gate']:variant['modules'][side],conversions[side]=normalize_buffers(variant['modules'][side])
            normalized=output/(fault+'-normalized.json');save(normalized,variant);freeze(normalized)
            report.setdefault('buffer_normalization',{})[fault]=conversions
            steps=expose_steps(variant,{'dq_n':4});stepfile=output/(fault+'-steps.json');save(stepfile,steps);freeze(stepfile)
            bench=output/(fault+'-check.sv');bench.write_text(harness());freeze(bench)
            for prop in (['definedness','step_ok','output_ok','observer_ok'] if fault=='none' else ['definedness'] if fault=='undefined' else ['step_ok']):
                model=output/(fault+'-'+prop+'-counterexample.json');script=output/(fault+'-'+prop+'.ys');log=output/(fault+'-'+prop+'.log')
                script.write_text(f'read_json {stepfile}\nread_verilog -sv {bench}\nhierarchy -top check\nflatten\nopt_clean\n'+sat_command(prop,model,definedness=prop=='definedness'));freeze(script)
                try:
                    with log.open('w') as stream:result=subprocess.run([str(yosys),'-Q','-T','-s',str(script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=180)
                finally:freeze(log)
                text=log.read_text()
                if fault=='none':require(result.returncode==0 and 'SAT proof finished - no model found: SUCCESS!' in text,'Complete counter/observer property failed');report['proofs'][prop]=str(log)
                else:
                    require(result.returncode==1 and 'proof did fail' in text and 'SUCCESS!' not in text,'Actual counter-D mutation not detected')
                    if fault=='undefined':undefined_counterexample(model)
                    else:concrete_counterexample(model,prop)
                    freeze(model);report['mutations'][fault]={'log':str(log),'counterexample':str(model),
                        'scope':'Actual projected native counter D bit replaced by X before state exposure' if fault=='undefined' else 'Actual projected native counter D bit inverted before state exposure'}
                checkpoint()
        ev.finish();report.update(status='se_tail_four_source_counter_bits_and_fifo_assertion_trigger_parity_proven',
            combined_source_state_bits=89828,sampled_reset_required=False,
            observed_outputs_and_next_state_defined=True,production_assertion_parity=False,
            remaining=['Production synthesized parent still has89824bits; dq_n and observer are source diagnostic extension',
                       'Existing fatal message text differs; full simulation stopping/event semantics and four-state diagnostics are not proved',
                       'Production datapath instantiates the core directly and bypasses standalone ABI assertion; production diagnostic emission remains missing',
                       'Other configurations and wholeVPU/board initialized composition remain separate'])
        checkpoint();archive(summary)
    except BaseException as error:
        report['error']=repr(error);checkpoint();archive(summary);raise
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--parent',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(main(args.parent,args.output)['status'])
