"""Exact production NativeDram: concrete RAM induction + exhaustive local state.

All phases run in the bounded gate. No queue/handshake/address assumptions.
Architectural RAM contents are retained by separate concrete-array induction;
every RAM input pin, primary output and local next-state bit is compared.
"""
import argparse
import copy
import gc
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

from check_sparkle_fpga_top_complete import bounded_context
from audit_sparkle_rtlil_roundtrip import Owners
from collect_sparkle_native_dram_production import CONFIG, ROOT, require, save, snapshot, verify, RAM_PORTS
from native_dram_ram_contract import canonical_memory, inject_write_address_fault
from prove_sparkle_native_dram import state_pairs, combinational_pairs
from prove_sparkle_control_production import qbits
from sparkle_transition import expose_steps, step_miter
from sparkle_provenance import sha256, verify as resolve_archived


COMMANDS=('equiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\n'
          'simplemap t:$logic_and t:$logic_or t:$logic_not t:$and t:$or t:$not\n'
          'opt -full\nequiv_simple -short -undef\nequiv_status -assert\n')


def run(command,log,timeout,negative=False):
    process=None
    if log.exists():
        i=1
        while log.with_name(log.name+f'.attempt{i}').exists():i+=1
        log.rename(log.with_name(log.name+f'.attempt{i}'))
    with log.open('w') as output:
        try:
            process=subprocess.Popen(command,cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
            code=process.wait(timeout=timeout)
        finally:
            if process is not None:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait()
    if not negative:require(code==0,f'Command exited {code}: {log}')
    return code


def contains(path,text):
    with path.open() as stream:return any(text in line for line in stream)


def load_owners(path):
    """No whole-file text decoding; owner cap + explicit graph budget.

    This graph contains only ~20k cells. Large RAM arrays remain mem_v2 cells.
    Bound total signal entries before transition deepcopy, rather than allowing
    a production memory_map graph to consume an unbounded Python heap.
    """
    result={'modules':{}};signals=0;owners=0
    with path.open() as stream:
        p=Owners(stream,limit=4*1024*1024);top=set()
        for field in p.object():
            require(field not in top,'Duplicate JSON root');top.add(field)
            if field=='creator':result[field]=p.value();continue
            require(field=='modules','Unexpected root field')
            for side in p.object():
                require(side in ('gold','gate') and side not in result['modules'],'Unexpected module')
                m={};result['modules'][side]=m
                for section in p.object():
                    require(section not in m,'Duplicate section')
                    require(section in ('attributes','parameter_default_values','ports','cells','netnames'), 'Unsupported module section')
                    if section in ('attributes','parameter_default_values'):
                        m[section]=p.value()
                        require(section!='parameter_default_values' or not m[section],'Module defaults unsupported')
                        continue
                    m[section]={}
                    for name in p.object():
                        require(name not in m[section],'Duplicate owner')
                        value=p.value();owners+=1
                        if section in ('ports','netnames'):signals+=len(value['bits'])
                        else:signals+=sum(len(v) for v in value['connections'].values())
                        require(owners<=100000 and signals<=4000000,'Local graph exceeds bounded representation budget')
                        m[section][name]=value
        p.whitespace();require(p.eof and p.pos==len(p.buf),'Trailing JSON data')
    require(set(result['modules'])=={'gold','gate'},'Missing side')
    return result


def initialization(module,states):
    known={}
    for name,net in module['netnames'].items():
        init=net.get('attributes',{}).get('init')
        if init is None:continue
        require(type(init) is str and len(init)==len(net['bits']) and set(init)<=set('01xz'),
                'Unsupported initial encoding: '+name)
        for bit,value in zip(net['bits'],reversed(init)):
            if type(bit) is str:
                require(bit in '01xz','Invalid constant alias')
                require(value not in '01' or bit==value,'Conflicting constant initialization')
                continue
            if bit not in states:
                require(value in 'xz','Defined initialization on non-state signal: '+name)
                continue
            if value in '01':
                require(bit not in known or known[bit]==value,'Conflicting initialization aliases')
                known[bit]=value
    return known


def checked_states(raw):
    states={side:qbits(m) for side,m in raw['modules'].items()}
    require(all(len(q)<=100000 for q in states.values()),'Unexpectedly large local-state inventory')
    # Reject non-flop drivers of retained Q bits as well as duplicate DFF drivers.
    for side,m in raw['modules'].items():
        require(not any(states[side]&set(p['bits']) for p in m['ports'].values() if p['direction']=='input'),
                'Retained state overlaps input')
        for cell in m['cells'].values():
            if cell['type']=='$dff':continue
            require(not any(states[side]&set(cell['connections'][p]) for p,d in cell['port_directions'].items() if d=='output'),
                    'Retained state has another driver')
    initial={side:initialization(m,states[side]) for side,m in raw['modules'].items()}
    require(not any(n.startswith('paired_') for m in raw['modules'].values() for n in m['netnames']),
            'State correspondence alias collision')
    mapping=state_pairs(raw,CONFIG)
    covered={side:set() for side in states};gold_to_native={}
    for name,width in mapping.items():
        for side,m in raw['modules'].items():
            bits=m['netnames'][name]['bits']
            require(len(bits)==width and len(set(bits))==width and set(bits)<=states[side] and not set(bits)&covered[side],
                    'Non-bijective state correspondence')
            covered[side].update(bits)
        gold_to_native.update(zip(raw['modules']['gold']['netnames'][name]['bits'],raw['modules']['gate']['netnames'][name]['bits']))
    require(covered==states,'Incomplete full state correspondence')
    for gb,value in initial['gold'].items():
        require(initial['gate'].get(gold_to_native[gb])==value,'Defined gold initialization differs')
    return mapping,{'bits':sum(mapping.values()),'gold_initial_bits':len(initial['gold']),
                    'native_initial_bits':len(initial['gate']),'pruned_bits':0}


def cut(raw,inventory):
    records=[]
    for index,row in enumerate(inventory['architectural_memories']):
        pair=[]
        for side,name in [('gold',row['reference']),('gate',row['native'])]:
            m=raw['modules'][side]
            require(m['cells'][name]==row['sides'][side]['cell'],'RAM inventory does not bind collected circuit')
            cell=canonical_memory(m['cells'][name],row['sides'][side]['canonical_read_order'])
            pair.append(cell)
            for port,direction in RAM_PORTS.items():
                bits=cell['connections'][port];alias=f'ram{index}_{port}'
                require(alias not in m['ports'] and alias not in m['netnames'],'RAM boundary collision')
                if direction=='output':
                    require(all(type(b) is int for b in bits) and len(set(bits))==len(bits),'RAM output alias/constant')
                    require(not any(set(bits)&set(p['bits']) for p in m['ports'].values() if p['direction']=='input'),'RAM output overlaps input')
                    for other_name,other in m['cells'].items():
                        if other_name==name:continue
                        require(not any(set(bits)&set(other['connections'][p]) for p,d in other['port_directions'].items() if d=='output'),
                                'Multiple driver RAM output')
                m['ports'][alias]={'direction':'input' if direction=='output' else 'output','bits':list(bits)}
                m['netnames'][alias]={'hide_name':0,'attributes':{},'bits':list(bits)}
            del m['cells'][name]
        parameters=[{k:v for k,v in c['parameters'].items() if k!='MEMID'} for c in pair]
        require(parameters[0]==parameters[1],'Concrete RAM semantic metadata mismatch')
        require(pair[0]['port_directions']==pair[1]['port_directions']==RAM_PORTS,'RAM port direction mismatch')
        require({p:len(v) for p,v in pair[0]['connections'].items()}=={p:len(v) for p,v in pair[1]['connections'].items()},'RAM interface shape differs')
        records.append({'index':index,'reference':row['reference'],'native':row['native'],
                        'state_bits':row['ram_state_bits'],'cells':pair})
    require(len(records)==36 and sum(r['state_bits'] for r in records)==314304,'RAM coverage mismatch')
    return records


def ram_signature(cells):
    params=[{k:v for k,v in c['parameters'].items() if k!='MEMID'} for c in cells]
    fixed=[{p:list(bits) for p,bits in c['connections'].items()
            if c['port_directions'][p]=='input' and all(type(b) is str for b in bits)} for c in cells]
    require(params[0]==params[1] and fixed[0]==fixed[1],'RAM metadata/fixed pin mismatch')
    return {'parameters':params[0],'fixed_pins':fixed[0]}


def ram_key(cells):
    return hashlib.sha256(json.dumps(ram_signature(cells),sort_keys=True).encode()).hexdigest()


def primitive(work,record,yosys,z3,timeout):
    work.mkdir()
    state={'status':'incomplete','phase':'concrete_ram_induction'};save(work/'summary.json',state)
    try:
        signature=ram_signature(record['cells'])
        net={'modules':{}}
        for side,original in zip(('gold','gate'),record['cells']):
            c=copy.deepcopy(original);c['parameters']['MEMID']='\\mem'
            ports={};nets={};bit=2
            # Keep exact constant pins: async read enable/reset/clock forms
            # required by the actual SMT memory semantics. The parent compares
            # EVERY pin, including constants. Promote other pins to arbitrary
            # equal inputs; fixed pins participate in the leaf cache identity.
            for pin,old in c['connections'].items():
                if pin in signature['fixed_pins']:continue
                bits=list(range(bit,bit+len(old)));bit+=len(old)
                c['connections'][pin]=bits
                ports[pin]={'direction':c['port_directions'][pin],'bits':bits}
                nets[pin]={'hide_name':0,'bits':bits,'attributes':{}}
            net['modules'][side]={'attributes':{},'ports':ports,'netnames':nets,'cells':{'mem':c}}
        require(net['modules']['gold']['ports']==net['modules']['gate']['ports'],'Primitive port shape mismatch')
        p=net['modules']['gold']['cells']['mem']['parameters']
        require(set(p['INIT'])=={'x'} and int(p['RD_CLK_ENABLE'],2)==0 and int(p['WR_CLK_ENABLE'],2)==1,
                'Unsupported RAM base or clocks')
        require(int(p['WR_PORTS'],2)==1 and int(p['RD_PORTS'],2) in (1,2),'Unsupported memory port count')
        save(work/'memory.json',net)
        (work/'memory.ys').write_text(f'read_json {work}/memory.json\nwrite_smt2 -wires {work}/memory.smt2\n')
        state['inputs']=snapshot([work/'memory.json',work/'memory.ys',yosys,z3]);save(work/'summary.json',state)
        run([str(yosys),'-Q','-T','-s',str(work/'memory.ys')],work/'yosys.log',timeout)
        query=''.join(f'(declare-fun {s}{t} () |{s}_s|)\n' for s in ('gold','gate') for t in ('0','1'))
        query+='(assert (= (|gold_m mem| gold0) (|gate_m mem| gate0)))\n'
        for port,v in net['modules']['gold']['ports'].items():
            if v['direction']=='input':query+=f'(assert (= (|gold_n {port}| gold0) (|gate_n {port}| gate0)))\n'
        query+='(assert (|gold_t| gold0 gold1))\n(assert (|gate_t| gate0 gate1))\n(check-sat)\n'
        query+='(push 1)\n(assert (not (and (= (|gold_m mem| gold1) (|gate_m mem| gate1)) (= (|gold_n RD_DATA| gold0) (|gate_n RD_DATA| gate0)))))\n(check-sat)\n(pop 1)\n'
        query+='(push 1)\n(assert (not (and (|gold_i| gold0) (|gate_i| gate0))))\n(check-sat)\n(pop 1)\n'
        width=int(p['WIDTH'],2)*int(p['RD_PORTS'],2)
        query+=f'(assert (not (= (|gold_n RD_DATA| gold0) (bvxor (|gate_n RD_DATA| gate0) (_ bv1 {width})))))\n(check-sat)\n'
        with (work/'query.smt2').open('w') as dest:
            with (work/'memory.smt2').open() as source:shutil.copyfileobj(source,dest,1024*1024)
            dest.write(query)
        state['smt_inputs']=snapshot([work/'memory.smt2',work/'query.smt2']);save(work/'summary.json',state)
        run([str(z3),str(work/'query.smt2')],work/'z3.log',timeout)
        answers=(work/'z3.log').read_text().split()
        require(answers==['sat','unsat','unsat','sat'],'Array induction/base/negative failed')
        verify(state['inputs']);verify(state['smt_inputs'])
        state.update(status='passed',answers=answers,outputs=snapshot([work/'yosys.log',work/'z3.log']))
    except BaseException as e:state['error']=repr(e);raise
    finally:save(work/'summary.json',state)
    state['summary_sha256']=snapshot([work/'summary.json'])
    return state


def verify_leaf(leaf, expected_key=None):
    require(leaf['status']=='passed' and leaf['answers']==['sat','unsat','unsat','sat'], 'Invalid leaf verdict')
    for key in ('inputs','smt_inputs','outputs','summary_sha256'):verify(leaf[key])
    require(len(leaf['summary_sha256'])==1,'Ambiguous leaf summary')
    saved=json.loads(Path(next(iter(leaf['summary_sha256']))).read_text())
    require(saved=={k:v for k,v in leaf.items() if k!='summary_sha256'},'Leaf summary differs')
    require({Path(p).name for p in leaf['outputs']}=={'yosys.log','z3.log'},'Missing leaf solver transcripts')
    logs=[Path(p) for p in leaf['outputs'] if Path(p).name=='z3.log']
    require(len(logs)==1 and logs[0].read_text().split()==leaf['answers'],'Z3 transcript differs from verdict')
    paths=[Path(p) for p in leaf['inputs'] if Path(p).name=='memory.json']
    require(len(paths)==1,'Missing actual primitive netlist')
    memory=json.loads(paths[0].read_text())
    require(set(memory['modules'])=={'gold','gate'},'Unexpected primitive modules')
    cells=[]
    for side in ('gold','gate'):
        module=memory['modules'][side];require(set(module['cells'])=={'mem'},'Unexpected primitive cell')
        cell=module['cells']['mem'];require(cell['type']=='$mem_v2','Wrong primitive type');cells.append(cell)
        require(cell['port_directions']==RAM_PORTS,'Primitive pin inventory differs')
        fixed={pin for pin,bs in cell['connections'].items()
               if RAM_PORTS[pin]=='input' and all(type(b) is str for b in bs)}
        require(set(module['ports'])==set(RAM_PORTS)-fixed,'Primitive variable pin inventory differs')
        for pin,port in module['ports'].items():
            require(port['direction']==RAM_PORTS[pin] and port['bits']==cell['connections'][pin],
                    'Primitive pin binding differs')
    require(expected_key is None or ram_key(cells)==expected_key,'Cached primitive semantic/fixed-pin key mismatch')



def verify_bindings(work,summary):
    verify(summary['ram_bindings'])
    records=json.loads((work/'ram_instances.json').read_text())
    bindings=json.loads((work/'ram_bindings.json').read_text())
    expected=[]
    for r in records:
        key=ram_key(r['cells'])
        expected.append({'index':r['index'],'key':key,'state_bits':r['state_bits']})
    require(bindings==expected and len(bindings)==36 and len({b['index'] for b in bindings})==36
            and sum(b['state_bits'] for b in bindings)==314304,'Incomplete/mismatched RAM binding')
    require(set(summary['leaves'])=={b['key'] for b in bindings},'Leaf key coverage differs')
    for key,leaf in summary['leaves'].items():verify_leaf(leaf,key)


def adopt_prepared(source,work,summary):
    old=json.loads((source/'summary.json').read_text())
    require(old['config']==list(CONFIG) and 'prepared' in old and 'state' in old,'Invalid prepared continuation')
    for field in ('prepared','mapping_inputs','mapped_artifacts'):verify(old[field])
    # Only THIS driver is allowed to change across this continuation. Every
    # native source, linked object and imported helper remains exactly bound.
    current_driver=str(Path(__file__).resolve())
    previous_driver={current_driver:old['inputs'][current_driver]}
    historical=resolve_archived(previous_driver)
    verify({p:h for p,h in old['inputs'].items() if p!=current_driver})
    require(previous_driver[current_driver]!=sha256(Path(current_driver)),
            'Continuation expects an explicit driver revision')
    summary['continuation']={'source_summary':snapshot([source/'summary.json']),
                            'old_driver_sha256':previous_driver,'old_driver_resolved':historical,
                            'old_prepared':old['prepared']}
    summary['inputs']={p:h for p,h in old['inputs'].items() if p!=current_driver}
    summary['inputs'].update(snapshot([Path(__file__).resolve(),source/'summary.json']))
    for p,h in historical.items():
        historical_path=ROOT/h
        summary['inputs'].update(snapshot([historical_path]))
    for name in ['ram_instances.json','cut.json','mapped.json','state_mapping.json','steps.json','miter.sv']:
        shutil.copyfile(source/name,work/name)
        require(sha256(work/name)==old['prepared'][str(source/name)],'Continuation copy differs')
    for name in ['proof.ys','map.ys']:
        text=(source/name).read_text()
        # Only absolute artifact directory changes; actual pass sequence and
        # every retained obligation in steps.json are byte-identical.
        (work/name).write_text(text.replace(str(source),str(work)))
    summary['prepared']=snapshot([work/n for n in ['ram_instances.json','cut.json','mapped.json',
                                'state_mapping.json','steps.json','miter.sv','proof.ys','map.ys']])
    for key in ('state','executables','checked_internal_aliases','before_mapping_state','mapping_inputs','mapped_artifacts'):
        summary[key]=old[key]
    summary['phase']='prepared'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('work',type=Path);ap.add_argument('--phase',choices=['prepare','leaves','parent','negative'],required=True)
    ap.add_argument('--inventory',type=Path,default=ROOT/'build/sparkle/native_dram_production_inventory_stream_3')
    ap.add_argument('--extraction',type=Path,default=ROOT/'build/sparkle/native_dram_production_inventory_1')
    ap.add_argument('--timeout',type=int,default=1200)
    ap.add_argument('--prepared-from',type=Path)
    a=ap.parse_args();bounded_context();work=a.work.resolve()
    def interrupted(signum,frame):raise RuntimeError('Interrupted: '+str(signum))
    signal.signal(signal.SIGTERM,interrupted)
    if a.phase=='prepare':
        require(not work.exists(),'Fresh production proof directory required');work.mkdir(parents=True)
        summary={'status':'incomplete','config':CONFIG,'phase':'prepare','leaves':{}}
    else:
        summary=json.loads((work/'summary.json').read_text())
        prerequisites={'leaves':{'prepared','leaves_active'},'parent':{'leaves_passed','parent_active'},
                       'negative':{'parent_passed','negative_active'}}
        require(summary['phase'] in prerequisites[a.phase],'Invalid phase prerequisite')
        summary['status']='incomplete';summary['phase']=a.phase+'_active'
        summary.pop('error',None)
    save(work/'summary.json',summary)
    try:
        if a.phase=='prepare' and a.prepared_from:
            adopt_prepared(a.prepared_from.resolve(),work,summary)
        elif a.phase=='prepare':
            extraction=json.loads((a.extraction/'summary.json').read_text())
            invrecord=json.loads((a.inventory/'summary.json').read_text())
            resolve_archived(extraction['input_sha256']);verify(extraction['generation_sha256'])
            verify(extraction['collected_sha256']);verify(invrecord['inventory_sha256'])
            verify(extraction['extraction_input_sha256']);verify(extraction['frontend_plugins'])
            runner=json.loads((a.extraction/'Emit.runner.json').read_text())
            verify(runner['source_sha256']);verify(runner['linked_sha256'])
            executables={n:Path(shutil.which(n) or '').resolve() for n in ['yosys','z3']}
            require(all(p.is_file() for p in executables.values()),'Required executable unavailable')
            # Actual imported Python closure, not unrelated tools/*.py.
            python=[Path(m.__file__).resolve() for m in list(sys.modules.values())
                    if getattr(m,'__file__',None) and Path(m.__file__).resolve().parent==ROOT/'tools']
            summary['inputs']=snapshot(python+[Path(__file__).resolve(),a.extraction/'collected.json',
                a.extraction/'summary.json',a.inventory/'inventory.json',a.inventory/'summary.json',
                *map(Path,runner['source_sha256']),*map(Path,runner['linked_sha256']),*executables.values()])
            summary['executables']={k:str(v) for k,v in executables.items()}
            save(work/'summary.json',summary)
            for name,exe in executables.items():run([str(exe),'-V' if name=='yosys' else '--version'],work/(name+'-version.log'),30)
            inventory=json.loads((a.inventory/'inventory.json').read_text())
            raw=load_owners(a.extraction/'collected.json')
            records=cut(raw,inventory);save(work/'ram_instances.json',records)
            expected_local={}
            for side,module in raw['modules'].items():
                flop_bits=sum(len(c['connections']['Q']) for c in module['cells'].values() if c['type']=='$dff')
                array_bits=sum(int(c['parameters']['SIZE'],2)*int(c['parameters']['WIDTH'],2)
                               for c in module['cells'].values() if c['type']=='$mem_v2')
                expected_local[side]={'flop_bits':flop_bits,'array_bits':array_bits,'total':flop_bits+array_bits}
            summary['before_mapping_state']=expected_local
            save(work/'cut.json',raw);del raw,inventory;gc.collect()
            script=work/'map.ys';script.write_text(f'read_json {work}/cut.json\nopt_reduce -fine\nopt_expr -fine -noclkinv\nopt_mem_priority\nmemory_map\nopt_expr -fine -noclkinv\nopt_merge t:$mux t:$eq t:$and t:$or t:$not t:$logic_and t:$logic_or t:$logic_not\nopt_clean\nwrite_json {work}/mapped.json\n')
            summary['mapping_inputs']=snapshot([work/'cut.json',script,executables['yosys']])
            save(work/'summary.json',summary)
            run([str(executables['yosys']),'-Q','-T','-s',str(script)],work/'map.log',a.timeout)
            verify(summary['mapping_inputs'])
            summary['mapped_artifacts']=snapshot([work/'mapped.json',work/'map.log'])
            save(work/'summary.json',summary)
            raw=load_owners(work/'mapped.json');mapping,state=checked_states(raw)
            require(all(len(qbits(raw['modules'][side]))==value['total'] for side,value in expected_local.items()),
                    'Memory lowering changed full retained-state count')
            save(work/'state_mapping.json',{k:{s:m['netnames'][k]['bits'] for s,m in raw['modules'].items()} for k in mapping})
            steps=expose_steps(raw,mapping);del raw;gc.collect()
            crosses=combinational_pairs(steps)
            (work/'miter.sv').write_text(step_miter(steps)) # Independent exact interface check.
            save(work/'steps.json',steps);del steps;gc.collect()
            (work/'proof.ys').write_text(f'read_json {work}/steps.json\n'+COMMANDS)
            summary['state']=state;summary['checked_internal_aliases']=crosses
            summary['prepared']=snapshot([work/n for n in ['ram_instances.json','cut.json','map.ys','mapped.json','state_mapping.json','steps.json','proof.ys','miter.sv']])
            summary['phase']='prepared'
        else:
            verify(summary['inputs']);verify(summary['prepared'])
            yosys=Path(summary['executables']['yosys']);z3=Path(summary['executables']['z3'])
            if a.phase=='leaves':
                records=json.loads((work/'ram_instances.json').read_text());bindings=[]
                for record in records:
                    key=ram_key(record['cells'])
                    bindings.append({'index':record['index'],'key':key,'state_bits':record['state_bits']})
                    if key not in summary['leaves']:
                        target=work/('ram_'+key[:16]);attempt=1
                        while target.exists():
                            target=work/('ram_'+key[:16]+f'_attempt{attempt}');attempt+=1
                        summary['leaves'][key]=primitive(target,record,yosys,z3,a.timeout)
                        save(work/'summary.json',summary)
                    else:
                        verify_leaf(summary['leaves'][key],key)
                require(len(bindings)==36 and sum(b['state_bits'] for b in bindings)==314304,'Memory coverage differs')
                save(work/'ram_bindings.json',bindings)
                summary['ram_bindings']=snapshot([work/'ram_bindings.json']);verify_bindings(work,summary)
                summary['phase']='leaves_passed'
            elif a.phase=='parent':
                require('ram_bindings' in summary,'RAM induction must precede parent qualification')
                verify_bindings(work,summary)
                run([str(yosys),'-Q','-T','-s',str(work/'proof.ys')],work/'proof.log',a.timeout)
                require(contains(work/'proof.log','Equivalence successfully proven!'),'No positive equivalence verdict')
                summary['parent']=snapshot([work/'proof.log']);summary['phase']='parent_passed'
            else:
                require('parent' in summary,'Positive parent proof required first');verify(summary['parent'])
                steps=load_owners(work/'steps.json');inject_write_address_fault(steps,'ram0_WR_ADDR')
                save(work/'mutation.json',steps);del steps;gc.collect()
                (work/'mutation.ys').write_text(f'read_json {work}/mutation.json\n'+COMMANDS)
                summary['negative_inputs']=snapshot([work/'mutation.json',work/'mutation.ys']);save(work/'summary.json',summary)
                code=run([str(yosys),'-Q','-T','-s',str(work/'mutation.ys')],work/'mutation.log',a.timeout,negative=True)
                require(code==1 and contains(work/'mutation.log','unproven $equiv cells'),'Actual circuit mutation not rejected')
                verify(summary['negative_inputs']);verify_bindings(work,summary)
                summary['negative_outputs']=snapshot([work/'mutation.log'])
                summary['status']='passed';summary['phase']='complete';summary['negative_exit_code']=code
        verify(summary['inputs'])
        if 'prepared' in summary:verify(summary['prepared'])
    except BaseException as error:
        summary['status']='incomplete';summary['error']=repr(error);raise
    finally:save(work/'summary.json',summary)
    if summary['status']=='passed':save(work/'qualification.json',{'status':'passed','summary_sha256':snapshot([work/'summary.json'])})
    print(json.dumps({k:summary[k] for k in ['status','phase','state'] if k in summary}),flush=True)

if __name__=='__main__':main()
