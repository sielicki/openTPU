"""Additive initialized DSP-leaf refinement using authenticated transition proofs.

Nine exact primitive-model configurations only. Undefined native state remains
arbitrary; every such initial state must admit an equal reference witness.
No whole-MXU, cascade composition, device power-up or independent-init claim.
Initialization means parameter-elaborated formal constraints; it is not an
event-region/time-zero four-state SystemVerilog simulation equivalence claim.
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

from check_sparkle_fpga_top_complete import bounded_context, require
from qualify_sparkle_specialization_binding import Evidence, normalized_hashes, save
from sparkle_provenance import ROOT, archive
from sparkle_transition import expose_steps, step_miter
from prove_sparkle_trace_ports import frontend_plugins
import prove_sparkle_mxu_physical as physical

CASES=[f'pe_{a}{b}{c}' for a in range(2) for b in range(2) for c in range(2)]+['colend_23']
PARENT=ROOT/'build/sparkle/formal_mxu_physical_composition/128_4_16-folded/summary.json'

CARRY_RESET_BRANCHES='''    generate
        if (USE_SIMD == "FOUR12") begin
            assign maj_xyz_simd_gated = {
                    maj_xyz_gated[47:36],
                    1'b0, maj_xyz_gated[34:24],
                    1'b0, maj_xyz_gated[22:12],
                    1'b0, maj_xyz_gated[10:0],
                    alu_cin
                };
            assign int_carry_in[3:1] = 3'b000;
            assign ext_carry_out = {
                    int_carry_out[3],
                    maj_xyz_gated[35] ^ int_carry_out[2],
                    maj_xyz_gated[23] ^ int_carry_out[1],
                    maj_xyz_gated[11] ^ int_carry_out[0]
                };
            assign carryout_reset = 4'b0000;
        end else if (USE_SIMD == "TWO24") begin
            assign maj_xyz_simd_gated = {
                    maj_xyz_gated[47:24],
                    1'b0, maj_xyz_gated[22:0],
                    alu_cin
                };
            assign int_carry_in[3:1] = {int_carry_out[2], 1'b0, int_carry_out[0]};
            assign ext_carry_out = {
                    int_carry_out[3],
                    1'bx,
                    maj_xyz_gated[23] ^ int_carry_out[1],
                    1'bx
                };
            assign carryout_reset = 4'b0x0x;
        end else begin
            assign maj_xyz_simd_gated = {maj_xyz_gated, alu_cin};
            assign int_carry_in[3:1] = int_carry_out[2:0];
            assign ext_carry_out = {
                    int_carry_out[3],
                    3'bxxx
                };
            assign carryout_reset = 4'b0xxx;
        end
'''
CARRY_INITIAL_OLD='initial CARRYOUT = carryout_reset;'
CARRY_INITIAL_NEW='initial CARRYOUT = (USE_SIMD == "FOUR12") ? 4\'b0000 : ((USE_SIMD == "TWO24") ? 4\'b0x0x : 4\'b0xxx);'


def expand_parameter_initializer(text):
    """Expose a statically parameter-selected formal initializer to Slang.

    This is constant propagation through the authenticated generate equation,
    not a claim about event-region races between a continuous assignment and
    an initial procedural read. All x bits retain their original constraints.
    """
    require(text.count(CARRY_RESET_BRANCHES)==1,'Authenticated carry-reset generate structure differs')
    for anchor in ['wire [3:0] carryout_reset;', 'parameter USE_SIMD = "ONE48";',
                   CARRY_INITIAL_OLD,'CARRYOUT <= carryout_reset;']:
        require(text.count(anchor)==1,'Carry-reset initializer structural anchor differs')
    require(len(re.findall(r'\bcarryout_reset\b',text))==6,'Unexpected carry-reset use or driver')
    require(len(re.findall(r'\binitial\s+CARRYOUT\s*=',text))==1,'Ambiguous CARRYOUT initializer')
    expanded=text.replace(CARRY_INITIAL_OLD,CARRY_INITIAL_NEW,1)
    require(expanded.replace(CARRY_INITIAL_NEW,CARRY_INITIAL_OLD,1)==text,'Initializer expansion changed unrelated source')
    return expanded,{'kind':'parameter_generate_constant_expansion',
        'original_initializer':CARRY_INITIAL_OLD,'expanded_initializer':CARRY_INITIAL_NEW,
        'parameter':'USE_SIMD','branch_values':{'FOUR12':'0000','TWO24':'0x0x','otherwise':'0xxx'},
        'dependency_certificate':{'leaves':['elaboration parameter USE_SIMD','literal 0000','literal 0x0x','literal 0xxx'],
            'current_inputs':[],'register_state':[],'unresolved_aliases':[],
            'justification':'Exact full generate branch block and unique net declaration/three assignments/initial read/synchronous reset read are checked against authenticated source; only the initial read is replaced'},
        'undefined_bits':'x remains unconstrained; never coerced to zero',
        'scope':'Parameter-elaborated formal initial predicates, not event-region/time-zero four-state SystemVerilog simulation equivalence'}


class InitialImplicationError(RuntimeError):
    def __init__(self,details):
        super().__init__('Native initial predicate does not imply equal reference initial predicate')
        self.details=details


def mutate_native_initializer(text):
    # All nine production leaf configurations use BREG=1. This is the
    # corresponding actual primitive initializer, not a relation mutation.
    target="initial Br2 = 18'b0;"
    require(text.count(target)==1,'Expected exactly one BREG1 Br2 initializer mutation target')
    changed=text.replace(target,"initial Br2 = 18'b1;",1)
    require(changed!=text,'Initializer mutation did not change source')
    return changed


def functional_model(text):
    require(text.count('module DSP48E1 (')==1,'DSP model module marker differs')
    body=text.split('module DSP48E1 (',1)[1].split('endmodule',1)[0]
    require(body.count('`ifdef YOSYS')==1,'DSP timing boundary differs')
    prefix,timing=body.split('`ifdef YOSYS',1)
    timing,suffix=timing.split('`endif',1)
    require('`' not in timing and not re.search(r'\b(always|always_ff|always_comb|assign|initial|reg|wire)\b',timing),'Timing removal would remove functional semantics')
    return 'module DSP48E1 ('+prefix+suffix+'endmodule\n'


def defined_initialization(module):
    """Collect all concrete bit constraints, rejecting non-state constraints."""
    q={b for cell in module['cells'].values() if cell['type']=='$dff' for b in cell['connections']['Q']}
    result={};constant_constraints=0
    for net in module['netnames'].values():
        init=net.get('attributes',{}).get('init')
        if init is None:continue
        require(type(init)is str and len(init)==len(net['bits']),'Malformed initialization width')
        for bit,value in zip(net['bits'],reversed(init)):
            require(value in '01x','Unsupported initialization value')
            if value=='x':continue
            if type(bit)is str:
                require(bit in '01' and bit==value,'Conflicting or unknown constant initializer')
                constant_constraints+=1
                continue
            require(type(bit)is int and bit in q,'Defined initializer outside retained register state')
            require(bit not in result or result[bit]==value,'Conflicting initialization aliases')
            result[bit]=value
    return result,constant_constraints


def initial_witness(raw,mapping):
    initials={s:defined_initialization(m)[0] for s,m in raw['modules'].items()}
    covered={s:set() for s in raw['modules']};witness={}
    for name,width in mapping.items():
        bits={s:m['netnames'][name]['bits'] for s,m in raw['modules'].items()}
        require(all(len(v)==width for v in bits.values()),'State correspondence width differs')
        values=[]
        for index,(g,n) in enumerate(zip(bits['gold'],bits['gate'])):
            require(g not in covered['gold'] and n not in covered['gate'],'Repeated initialization correspondence')
            covered['gold'].add(g);covered['gate'].add(n)
            gv=initials['gold'].get(g);nv=initials['gate'].get(n)
            # Equality relation requires this implication for EVERY native
            # initial value. Choosing zero for a native undefined bit is invalid.
            if gv is not None and (nv is None or gv!=nv):
                raise InitialImplicationError({'state':name,'bit_index_lsb':index,
                    'gold_bit':g,'gate_bit':n,'reference_constraint':gv,
                    'native_constraint':nv if nv is not None else '?'})
            values.append(nv if nv is not None else '?')
        witness[name]=''.join(reversed(values))
    for side,module in raw['modules'].items():
        q={b for cell in module['cells'].values() if cell['type']=='$dff' for b in cell['connections']['Q']}
        require(covered[side]==q,'Initial witness omits actual state')
    return {'native_and_reference_witness':witness,
        'defined_bits':{s:len(v) for s,v in initials.items()},
        'arbitrary_native_bits':sum(v.count('?') for v in witness.values()),
        'constant_initializer_constraints':{s:defined_initialization(m)[1] for s,m in raw['modules'].items()}}


def checked_matching_state(raw,rename):
    # The historical helper creates dsp_state_N aliases by assignment. A
    # pre-existing initializer-bearing alias must never be overwritten.
    require(all(not re.fullmatch(r'dsp_state_\d+',name)
        for module in raw['modules'].values() for name in module['netnames']),
        'Reserved DSP state alias already exists before correspondence mapping')
    before={side:defined_initialization(module) for side,module in raw['modules'].items()}
    mapping=physical.matching_state(raw,rename)
    require(before=={side:defined_initialization(module) for side,module in raw['modules'].items()},
        'State correspondence changed original initialization constraints')
    return mapping


def bridge_module(old,new):
    """Exact graph identity under a bijective integer-net renaming.

    Only source-location annotations are ignored. Initializers are separately
    audited before expose_steps removes them. All cells, parameters, port
    directions, net aliases, constants and non-source attributes must match.
    No optimization/constant-folding equivalence is inferred here.
    """
    require(set(old)==set(new),'Module schema differs')
    require(set(old['ports'])==set(new['ports']) and set(old['netnames'])==set(new['netnames']) and set(old['cells'])==set(new['cells']),'Graph inventory differs')
    forward={};reverse={}
    def bind(a,b):
        require(len(a)==len(b),'Graph bit-vector width differs')
        for x,y in zip(a,b):
            if type(x)is str or type(y)is str:
                require(type(x)is type(y) and x==y,'Graph constant differs')
            else:
                require(type(x)is int and type(y)is int,'Unsupported graph bit')
                require(x not in forward or forward[x]==y,'Inconsistent graph alias')
                require(y not in reverse or reverse[y]==x,'Nonbijective graph alias')
                forward[x]=y;reverse[y]=x
    for group in ['ports','netnames']:
        for name in old[group]:bind(old[group][name]['bits'],new[group][name]['bits'])
    def clean_attrs(attrs):return {k:v for k,v in attrs.items() if k!='src'}
    def normalized(module,translate):
        out=copy.deepcopy(module)
        out['attributes']=clean_attrs(out.get('attributes',{}))
        def bits(values):
            require(all(type(b)is str or b in translate for b in values),'Unnamed graph bit is not explicitly mapped')
            return [b if type(b)is str else translate[b] for b in values]
        for group in ['ports','netnames']:
            for item in out[group].values():
                item['bits']=bits(item['bits'])
                if 'attributes' in item:item['attributes']=clean_attrs(item['attributes'])
        for cell in out['cells'].values():
            cell['attributes']=clean_attrs(cell.get('attributes',{}))
            cell['connections']={p:bits(v) for p,v in cell['connections'].items()}
        return out
    require(normalized(old,forward)==normalized(new,{b:b for b in reverse}),'Authenticated transition graph differs')
    return len(forward)


def case_description(case):
    require(case in CASES,'Unsupported DSP configuration')
    if case.startswith('pe_'):
        a,b,c=map(int,case[3:])
        return 'otpu_pe','otpu_mxu_pe_dsp_'+case[3:],f'-G FIRST={a} -G LAST={b} -G WREG={c}',lambda n:n
    return 'otpu_colend','otpu_mxu_colend_dsp_23','-G SW=23',lambda n:re.sub(r'g_d\[(\d+)\]\.u_dsp',r'u_dsp\1',n)


def extraction_script(side,top,params,source,model,destination,ignore_initial):
    flag=' --ignore-initial' if ignore_initial else ''
    return f'read_slang --top {top}{flag} -D SYNTHESIS -D YOSYS {params} {source} {model}\nrename {top} {side}\nproc\nflatten\nhierarchy -top {side}\nopt_expr\nmemory_share -nosat -nowiden\nmemory_map\nopt_clean\nwrite_json {destination}\n'


def main(output):
    bounded_context();output=output.resolve();require(not output.exists(),'Fresh output required');output.mkdir(parents=True)
    ev=Evidence();summary=output/'summary.json';report={'status':'incomplete','scope':__doc__,'cases':[],
        'whole_mxu_initialized_equivalence':False,'independent_initial_state_equivalence':False}
    def checkpoint():report['input_sha256']=ev.observed;save(summary,report)
    def freeze(path):ev.direct(Path(path));archive(Path(path));checkpoint()
    def interrupted(signum,frame):raise RuntimeError('Interrupted '+str(signum))
    signal.signal(signal.SIGTERM,interrupted);checkpoint()
    try:
        for module in list(sys.modules.values()):
            path=getattr(module,'__file__',None)
            if path and Path(path).resolve().parent==ROOT/'tools':ev.direct(Path(path))
        ev.direct(Path(__file__))
        yosys=Path(shutil.which('yosys')).resolve();ev.direct(yosys)
        frontend=output/'frontend.log'
        with frontend.open('w') as stream:subprocess.run([str(yosys),'-Q','-T','-p','plugin -l; help read_slang'],stdout=stream,check=True)
        freeze(frontend)
        for plugin in frontend_plugins(frontend.read_text()):ev.direct(plugin)
        parent,parent_digest=ev.record(PARENT)
        require(parent['status']=='passed' and parent['config']==[128,4,16] and parent['mutation'] is None,'Physical production transition composition missing')
        parent_hashes=normalized_hashes(parent['input_sha256'])
        for path,h in parent['generation_sha256'].items():ev.direct(Path(path),h)
        report['historical_composition']={'summary':str(PARENT),'sha256':parent_digest}
        for case in CASES:
            work=output/case;work.mkdir();old=physical.WORK/case
            proof_path=old/'summary.json'
            require(str(proof_path) in parent_hashes,'Unanchored historical leaf summary')
            proof,digest=ev.record(proof_path,parent_hashes[str(proof_path)])
            require(proof['status']=='passed' and proof['case']==case,'Historical leaf failed')
            hashes=normalized_hashes(proof['input_sha256'])
            # Consumed extraction paths stay original, immutable and direct.
            for filename in ['native.sv','reference.sv','DSP48E1.sv','gold_extract.ys','gate_extract.ys','steps.json','registers.json','proof.ys']:
                path=old/filename;ev.direct(path,hashes[str(path)])
            for path,h in hashes.items():
                if Path(path).is_relative_to(ROOT/'tools') or Path(path).is_relative_to(ROOT/'OpenTPU') or Path(path).is_relative_to(ROOT/'rtl'):ev.direct(Path(path),h)
            model=Path(proof['dsp_model']);ev.direct(model,proof['dsp_model_sha256'])
            require(model.resolve()==physical.dsp_model().resolve(),'Current actual DSP primitive library differs')
            require(functional_model(model.read_text())==(old/'DSP48E1.sv').read_text(),'Exact functional DSP model extraction differs')
            normalized_model=work/'DSP48E1-parameter-initial.sv'
            normalized_text,initial_expansion=expand_parameter_initializer((old/'DSP48E1.sv').read_text())
            normalized_model.write_text(normalized_text);freeze(normalized_model)
            expansion_path=work/'parameter-initial-expansion.json'
            save(expansion_path,{**initial_expansion,'original_model':str(old/'DSP48E1.sv'),'expanded_model':str(normalized_model)});freeze(expansion_path)
            log=old/'proof.log';require(str(log) in parent_hashes,'Historical terminal proof log unanchored');ev.direct(log,parent_hashes[str(log)])
            require('Equivalence successfully proven!' in log.read_text(),'Historical leaf transition theorem incomplete')
            expected=f'read_json {old}/steps.json\nequiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\nsimplemap t:$mux\nopt -full\nequiv_simple -short\nequiv_status -assert\n'
            require((old/'proof.ys').read_text()==expected,'Historical complete transition command differs')
            gt,nt,params,rename=case_description(case)
            fresh={'modules':{}}
            for side,top,options,source in [('gold',gt,params,old/'reference.sv'),('gate',nt,'',old/'native.sv')]:
                require((old/(side+'_extract.ys')).read_text()==extraction_script(side,top,options,source,old/'DSP48E1.sv',old/(side+'.json'),True),'Historical extraction source/parameters differ')
                script=work/(side+'_extract.ys');artifact=work/(side+'.json');log=work/(side+'_extract.log')
                script.write_text(extraction_script(side,top,options,source,normalized_model,artifact,False));freeze(script)
                try:
                    with log.open('w') as stream:result=subprocess.run([str(yosys),'-Q','-T','-s',str(script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=300)
                finally:freeze(log)
                require(result.returncode==0,'Init-preserving extraction failed');freeze(artifact)
                with artifact.open() as stream:raw=json.load(stream)
                require(set(raw['modules'])=={side},'Unexpected fresh module hierarchy')
                fresh['modules'][side]=raw['modules'][side];del raw
            mapping=checked_matching_state(fresh,rename)
            require(sum(mapping.values())==proof['state_bits'],'Actual complete retained state count changed')
            witness=initial_witness(fresh,mapping)
            steps=expose_steps(fresh,mapping);del fresh
            with (old/'steps.json').open() as stream:previous=json.load(stream)
            require(set(previous['modules'])=={'gold','gate'},'Historical step module inventory differs')
            bridge={side:bridge_module(previous['modules'][side],steps['modules'][side]) for side in ['gold','gate']}
            # Exact complete correspondence is included in the graph: all named
            # state inputs and every next-state/output port must match.
            step_miter(steps)
            del previous,steps
            # Real native-only primitive mutation. Extraction and exact
            # transition reuse must succeed before an initialization failure
            # can count as the required negative control.
            mutant_model=work/'DSP48E1-native-initializer-mutated.sv'
            mutant_model.write_text(mutate_native_initializer(normalized_text));freeze(mutant_model)
            mutant_json=work/'gate-initializer-mutated.json'
            mutant_script=work/'gate-initializer-mutated.ys';mutant_log=work/'gate-initializer-mutated.log'
            mutant_script.write_text(extraction_script('gate',nt,'',old/'native.sv',mutant_model,mutant_json,False));freeze(mutant_script)
            try:
                with mutant_log.open('w') as stream:result=subprocess.run([str(yosys),'-Q','-T','-s',str(mutant_script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=300)
            finally:freeze(mutant_log)
            require(result.returncode==0,'Initializer mutation failed to extract; not a valid negative control');freeze(mutant_json)
            with (work/'gold.json').open() as stream:gold=json.load(stream)
            with mutant_json.open() as stream:gate=json.load(stream)
            require(set(gold['modules'])=={'gold'} and set(gate['modules'])=={'gate'},'Initializer mutation extraction hierarchy differs')
            mutant={'modules':{'gold':gold['modules']['gold'],'gate':gate['modules']['gate']}};del gold,gate
            mutant_mapping=checked_matching_state(mutant,rename)
            require(mutant_mapping==mapping,'Initializer mutation changed complete state inventory')
            mutant_steps=expose_steps(mutant,mutant_mapping)
            with (old/'steps.json').open() as stream:previous=json.load(stream)
            mutant_bridge={side:bridge_module(previous['modules'][side],mutant_steps['modules'][side]) for side in ['gold','gate']}
            del previous,mutant_steps
            mutant_initials={side:defined_initialization(module)[0] for side,module in mutant['modules'].items()}
            constraints={side:{name:''.join(reversed([mutant_initials[side].get(bit,'?')
                for bit in module['netnames'][name]['bits']])) for name in mapping}
                for side,module in mutant['modules'].items()}
            try:
                initial_witness(mutant,mutant_mapping)
            except InitialImplicationError as error:
                failure=error.details
            else:raise RuntimeError('Actual native initializer mutation was accepted')
            require(failure['reference_constraint']=='0' and failure['native_constraint']=='1','Unexpected initialization failure; intended concrete Br2 mutation not demonstrated')
            del mutant
            negative={'status':'rejected_by_initial_predicate_implication','native_model':str(mutant_model),
                'extraction_script':str(mutant_script),'extraction_log':str(mutant_log),'extraction':str(mutant_json),
                'failure':failure,'state_initial_constraints_msb_first':constraints,'transition_bridge_net_bits':mutant_bridge}
            negative_path=work/'initializer-mutation-audit.json';save(negative_path,negative);freeze(negative_path)
            report['cases'].append({'case':case,'status':'initialized_refinement_proven',
                'historical_summary':str(proof_path),'historical_sha256':digest,'state_bits':sum(mapping.values()),
                'mapping':mapping,'initialization':witness,'transition_bridge_net_bits':bridge,
                'parameter_initializer_expansion':str(expansion_path),
                'actual_initializer_mutation':{'audit':str(negative_path),'status':negative['status'],'failure':failure},
                'relation':'All concrete retained model state equal; arbitrary shared current inputs; reference initialization chosen equal to each allowed native state'})
            checkpoint()
        require([c['case'] for c in report['cases']]==CASES,'Incomplete nine-configuration inventory')
        ev.finish();report['status']='nine_dsp_leaf_initialized_refinements_proven';checkpoint();archive(summary)
    except BaseException as error:
        report.update(status='incomplete',error=repr(error));checkpoint();archive(summary);raise
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(main(args.output)['status'])
