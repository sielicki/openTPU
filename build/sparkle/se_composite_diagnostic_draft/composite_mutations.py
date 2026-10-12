"""Actual Lean-helper mutations and exact emitted fault/CEX classification."""
import re
from composite_observers import need,WIDTHS

CASES=('collision_enable','return_fin_boundary','rom_entry')
ROM_SOURCE='(SeMicrocode.operation (ci+1) (p*c.stages+stage)).encode'
ROM_CHANGED='((SeMicrocode.operation (ci+1) (p*c.stages+stage)).encode + (if stage == 0 && ci == 0 && p == 0 then 1 else 0))'


def replace_once(source,old,new):
    need(source.count(old)==1,'Missing/ambiguous actual mutation source anchor')
    return source.replace(old,new,1)


def mutate_helper(source,case):
    need(case in CASES,'Unknown actual source fault')
    if case=='collision_enable':
        return replace_once(source,'if (!rst && en && in_v && ret_r)','if (!rst && in_v && ret_r)')
    if case=='return_fin_boundary':
        return replace_once(source,"+ 4'd1 >= diagnostic_n_pass", "+ 4'd1 > diagnostic_n_pass")
    return replace_once(source,ROM_SOURCE,ROM_CHANGED)


def emitted_fault(baseline,actual,case):
    need(case in CASES,'Unknown emitted fault')
    if case=='collision_enable':
        expected=replace_once(baseline,'if (!rst && en && in_v && ret_r)','if (!rst && in_v && ret_r)')
        detail={'changed_trigger_bit':0,'fault':'collision no longer gated by en'}
    elif case=='return_fin_boundary':
        expected=replace_once(baseline,"+ 4'd1 >= diagnostic_n_pass", "+ 4'd1 > diagnostic_n_pass")
        detail={'changed_trigger_bit':1,'fault':'fin threshold excludes equality'}
    else:
        matches=re.findall(r"      7'd16: diagnostic_uc0=105'd([0-9]+);",baseline)
        need(len(matches)==1,'Exact stage0/class1/pass0 emitted table entry missing')
        value=int(matches[0]);need(value%2==0 and value+1<2**105,'ROM low-bit fault requires zero LSB')
        old=f"      7'd16: diagnostic_uc0=105'd{value};"
        new=f"      7'd16: diagnostic_uc0=105'd{value+1};"
        expected=replace_once(baseline,old,new)
        detail={'rom_stage':0,'class':1,'pass':0,'changed_rom_bit':0,
                'before':value,'after':value+1,'fault':'actual table constant low bit flipped'}
    need(actual==expected and actual!=baseline,'Actual compiled core differs beyond exact intended fault')
    return detail


def model_values(record):
    need(type(record) is dict and type(record.get('signal')) is list,'Actual SAT JSON model required')
    widths={'rst':1,'en':1,'in_v':1,'rom_cp':7,'ok':1,'impossible':1,'observed':648,
            **{'mapped_'+n:w for n,w in WIDTHS.items()}}
    values={};seen=set()
    for item in record['signal']:
        name=item.get('name');need(type(name) is str and name not in seen,'Duplicate/invalid model signal');seen.add(name)
        if name not in widths:continue
        width=widths[name];wave=item.get('wave','')
        if width==1 and wave[:1] in ['0','1']:bits=wave[0]
        else:
            data=item.get('data',[])
            need(wave.startswith('=') and type(data) is list and data and type(data[0]) is str,
                 'Missing actual vector value '+name)
            bits=data[0]
        need(len(bits)==width and set(bits)<=set('01'),'Undefined/truncated actual model '+name)
        values[name]=int(bits,2)
    need(set(values)==set(widths) and values['ok']==0 and values['impossible']==0,
         'Full defined input/output counterexample with false equality required')
    return values


def classify_counterexample(record,case):
    value=model_values(record);v=value['observed']
    gate_p=v&15;gate_rom=(v>>4)&((1<<315)-1);gate_t=(v>>319)&31
    gold_p=(v>>324)&15;gold_rom=(v>>328)&((1<<315)-1);gold_t=(v>>643)&31
    need(gold_p==gate_p,'Fault unexpectedly changes n_pass output')
    td=gold_t^gate_t;rd=gold_rom^gate_rom
    if case=='collision_enable':
        need(td==1 and rd==0 and value['rst']==0 and value['en']==0 and
             value['in_v']==1 and value['mapped_ret_r']==1 and gold_t&1==0 and gate_t&1==1,
             'Counterexample is not actual collision enable loss')
    elif case=='return_fin_boundary':
        need(td==2 and rd==0 and value['rst']==0 and (value['mapped_vpos']>>24)&1==1,
             'Counterexample is not actual return-fin boundary fault')
        packed=value['mapped_lp_m'];cls=(packed>>33)&7;pas=(packed>>29)&15
        count={1:3,2:3,3:2,4:4,5:4}.get(cls,1)
        need(((pas+1)&15)==count,'Counterexample misses exact original finite threshold')
    elif case=='rom_entry':
        need(value['rom_cp']==16 and rd==1 and td&~4==0,
             'Counterexample is not exact emitted stage0 ROM low-bit fault')
    else:raise ValueError('Unknown counterexample case')
    return {'gold_triggers':gold_t,'mutant_triggers':gate_t,'trigger_difference':td,
            'rom_difference':rd,'all_648_observed_bits_defined':True,
            'all_arbitrary_model_inputs_defined':True,'inputs':{n:v for n,v in value.items()
                if n not in {'observed','ok','impossible'}}}


def failing_sat(log):
    need(log.count('SAT proof finished - model found: FAIL!')==1 and
         'SUCCESS!' not in log and 'ERROR:' not in log and 'TIMEOUT' not in log,
         'Missing unique actual equality counterexample terminal')
