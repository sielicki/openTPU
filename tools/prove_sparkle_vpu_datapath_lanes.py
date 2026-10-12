"""Complete local lane-state and native FP-interface transition equivalence.

Corresponding FP result ports are shared arbitrary inputs; all operand/enable
ports are checked. The arithmetic obligation is discharged by the authenticated
native Float pipeline proof. No lane register or metadata stage is abstracted.

The proof-only harness removes `unique` from case statements, preserving
SystemVerilog first-match simulation values while strengthening synthesized
undefined multi-hot states. Production equivalence uses the reset/enable invariant
m0d=fdec(m0.func); the all-256-function decoder proof is recorded separately in
build/sparkle/formal_vpu_decode/summary.json. See scope.json for the full argument.
"""
import argparse,json,re,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from sparkle_transition import expose_steps,step_miter
from sparkle_mxu_transition import prune_unobserved_register_bits
from sparkle_provenance import verify
from check_sparkle_physical import module_tokens
from prove_sparkle_se_tail import delay_name
WORK=ROOT/'build/sparkle/formal_vpu_datapath_lanes'

def reference(lanes,cl,se=False):
    rtl=(ROOT/'rtl/vpu/otpu_vpu.sv').read_text();cbw=(256//lanes-1).bit_length();mw=102+lanes+cbw
    def section(a,b):return rtl.split(a,1)[1].split(b,1)[0]
    meta=section('  // meta of a chunk;','  // mi:');meta=meta[meta.index('  typedef'):]
    dec='  localparam int NVF = 20;\n'+section('  localparam int NVF = 20;', '  fdec_t m0d;');dec=dec[dec.index('  typedef'):]
    types=section('  // the parts of the meta the later stages read: along the lane taps, and for the reductions\n','  rm_t m0r;')
    body=section('  // ------------------------------------------------------------------ elementwise lanes\n','  // ------------------------------------------------------------------ RMAX\n')
    # unique only grants synthesis don't-cares for simultaneous hits. Ordinary
    # case preserves original simulation priority for all arbitrary decoder states.
    body=body.replace('unique case','case')
    body=body.replace('  f32_t  rsa [LANES], rsb [LANES];','').replace('  f32_t  rfb [LANES];','')
    composite='  localparam int CNS = 3;'+section('  localparam int CNS = 3;','  wire              iss_ok')
    functions=[]
    for n in ['n_slots','comp_f','f_cls','cls_f','red_f']:
        functions+=re.findall(r'  function automatic [^\n]*\b'+n+r'\(.*?endfunction',rtl,re.S)
    ps=[('en',1),('m0',mw),('m0d',28),*[(n,32*lanes) for n in ['xa','xb','xc','xd','rsa','rsb','rfb']],('c_uy',256),('c_qy',256)]
    outs=[('mo',25+lanes),('lres',32*lanes),('lmm',lanes),('lmv',32*lanes),('pacc',32*lanes),('o_c_hold',1),('o_c_sel',3),*[(f'o_c_s{a}',96*lanes) for a in ['a','b','c','e']]]
    header='module gold import otpu_pkg::*; import otpu_fp::*;(input clk,rst,'+','.join(f'input [{w-1}:0] i_{n}' for n,w in ps)+','+','.join(f'output [{w-1}:0] o_{n}' for n,w in outs)+');\n'
    aliases=['wire en=i_en;','meta_t m0;assign m0=i_m0;','fdec_t m0d;assign m0d=i_m0d;']
    for n in ['xa','xb','xc','xd','rsa','rsb','rfb']:
        aliases += [f'f32_t {n} [LANES];',f'for(genvar l=0;l<LANES;l++) assign {n}[l]=i_{n}[32*l+:32];']
    for n in ['c_uy','c_qy']:aliases += [f'for(genvar l=0;l<LANES;l++) if(l<8) assign {n}[l]=i_{n}[32*l+:32];else assign {n}[l]=0;']
    assign=['assign o_mo=mo;assign o_lmm=lmm;assign o_o_c_hold=c_hold;assign o_o_c_sel=c_sel;']
    for n in ['lres','lmv','pacc']:
        assign += [f'for(genvar l=0;l<LANES;l++) assign o_{n}[32*l+:32]={n}[l];']
    for n in ['a','b','c','e']:assign += [f'for(genvar s=0;s<3;s++) for(genvar l=0;l<LANES;l++) assign o_o_c_s{n}[32*(s*LANES+l)+:32]=c_s{n}[s][l];']
    if lanes==16:
        body=body.replace('if (s == 0 && RMA) begin : g_pacc','if (s == 0) begin : g_pacc').replace('if (RMA) begin : g_pacc','if (1) begin : g_pacc')
    return header+f'''localparam LANES={lanes},CL={cl},AW=20,CBW={cbw},LM=2,LA=4,SL=7,NVF=20,RL=64/LANES,NSLOT=10,NSX={1 if se else 10},NCL={lanes if se else cl},NLL={0 if se else cl},C8={int(se)};
localparam logic [2:0] C_OTH=0,C_ONE=1,C_EXP=2,C_RCP=3,C_RSQ=4,C_LOG=5;
localparam f32_t F_NZ=32'h80000000;
'''+meta+dec+types+'\n'.join(functions)+composite+'\n'.join(aliases)+body+'\n'.join(assign)+'\nendmodule\n'

def state_ref(name):
    if m:=re.fullmatch(r'meta_(pre|slot\d+)_(\d+)',name):
        typ,i=m[1],int(m[2]);s=1 if typ=='pre' else int(typ[4:]);cycles=3 if typ=='pre' else 7
        return delay_name(f'g_mdel[{s}].'+('g_pre.u_p' if typ=='pre' else 'g_d0.u_d' if s==0 else 'g_dn.u_d'),i,cycles),None
    if m:=re.fullmatch(r'lane(\d+)_slot(\d+)_(.*)',name):
        l,s,field=int(m[1]),int(m[2]),m[3];long=l<CURRENT_CL and not CURRENT_SE
        p=f'g_lane[{l}].g_slot[{s}]' if long else f'g_slane[{l}]'
        if field in ['ra','rb','rc']:return p+'.'+field,None
        if field=='re':return p+('.g_mma.re' if long else '.re'),None
        if field=='sr':return p+'.sr',None
        if field=='dst':return p+'.dr', 'dst'
        if field in ['p0','p1','p2','e1','e2','g1','g2']:return p+'.g_pre.'+field,None
        if d:=re.fullmatch(r'(k1|k2|ii|f|dst_delay|c)_(\d+)',field):
            f,i=d[1],int(d[2]);unit='g_ma.u_ma.u_c' if f=='c' else 'u_dst' if f=='dst_delay' else 'g_'+f+'.u_'+f if f in ['k1','k2','ii'] else 'u_f'
            return delay_name(p+'.'+unit,i,2 if f=='c' else 6),None
    raise RuntimeError('unmapped native state '+name)

CURRENT_CL=0
CURRENT_SE=False

def prove(cfg,mutation=False,se=False):
    global CURRENT_CL,CURRENT_SE
    lanes,cl=cfg;CURRENT_CL=cl;CURRENT_SE=se;work=WORK/f'{lanes}_{cl}_{int(se)}'/('mutation' if mutation else 'proof');work.mkdir(parents=True,exist_ok=True)
    source=work/'native.sv';gen=work/'Generate.lean';ref=work/'reference.sv';hier=work/'hierarchy.json'
    gen.write_text('import OpenTPU.VpuLanes\ndef main : IO Unit := do\n'
        f'  let m ← IO.ofExcept (OpenTPU.VpuLanes.build ⟨{lanes},{cl},{str(se).lower()}⟩)\n'
        f'  IO.FS.writeFile "{source}" (Sparkle.Backend.Verilog.toVerilog m ++ Sparkle.Backend.Verilog.toVerilog {{OpenTPU.Float.multiply 2 with name := "otpu_vpu_datapath_mul"}} ++ Sparkle.Backend.Verilog.toVerilog {{OpenTPU.Float.addition 4 with name := "otpu_vpu_datapath_add"}})\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    if mutation:source.write_text(source.read_text().replace('assign lres =',"assign lres = 1'b1 ^",1))
    if se:
        compgen=work/'Composite.lean';compgen.write_text('import OpenTPU.SeComposite\ndef main : IO Unit := do\n  IO.print (← IO.ofExcept (OpenTPU.SeComposite.toVerilog ⟨8,21,3,2,true⟩))\n')
        with source.open('a') as out:subprocess.run(['lake','env','lean','--run',str(compgen)],cwd=ROOT,stdout=out,check=True)
        record=json.loads((ROOT/'build/sparkle/formal_se_composite/vpu_mw21_summary.json').read_text());assert record['status']=='passed'
        verify(record['proof']['input_sha256'])
        comp_tokens=module_tokens((ROOT/'build/sparkle/formal_se_composite/8_21_3_2/native.sv').read_text())
        assert module_tokens(source.read_text())['otpu_se_comp_sparkle']==comp_tokens['otpu_se_comp_sparkle']
    ref.write_text(reference(lanes,cl,se))
    fp_summary=ROOT/'build/sparkle/formal/summary.json';entry=json.loads(fp_summary.read_text())['fp'];resolved=verify(entry['input_sha256'])
    assert 'Induction step proven: SUCCESS!' in Path(entry['log']).read_text()
    old=next(p for p in resolved if p.endswith('/float.sv'));expected=module_tokens((ROOT/resolved[old]).read_text());actual=module_tokens(source.read_text())
    for k,lat in [('mul',2),('add',4)]:
        new=f'otpu_vpu_datapath_{k}';old=f'otpu_f{k}_sparkle_{lat}'
        assert actual[new].replace('module'+new+'(','module'+old+'(',1)==expected[old]
    extract,_=yosys(work,'extract',f'''read_slang --keep-hierarchy --top gold rtl/top/otpu_pkg.sv rtl/vpu/otpu_fp.sv rtl/vpu/otpu_fpipe.sv rtl/vpu/otpu_se_comp.sv {ref.relative_to(ROOT)}
read_slang --keep-hierarchy --top otpu_vpu_lanes_sparkle {source.relative_to(ROOT)}
rename otpu_vpu_lanes_sparkle gate
proc
write_json {hier.relative_to(ROOT)}
''')
    raw=json.loads(hier.read_text())
    for n,m in raw['modules'].items():
        if n.split('$')[0] in {'otpu_fmul','otpu_fadd','otpu_vpu_datapath_mul','otpu_vpu_datapath_add','otpu_se_comp','otpu_se_comp_sparkle'}:
            m['cells']={};m['netnames']={};m['attributes']['blackbox']='1'
    boxes=work/'boxes.json';boxes.write_text(json.dumps(raw));flat=work/'flat.json'
    flatten,_=yosys(work,'flatten',f'''read_json {boxes.relative_to(ROOT)}
flatten -noscopeinfo gold gate
memory_map
opt_expr
opt_clean
write_json {flat.relative_to(ROOT)}
''')
    mods=json.loads(flat.read_text())['modules'];raw={'modules':{k:mods[k] for k in ['gold','gate']}}
    gold,gate=raw['modules'].values()
    gold['ports']={(n[2:] if n.startswith(('i_','o_')) else n):v for n,v in gold['ports'].items()}
    for n,v in gold['ports'].items():gold['netnames'][n]={'bits':v['bits'],'hide_name':0,'attributes':{}}
    for l in range(lanes):
        for s in range(10 if l<cl and not se else 1):
            native=f'lane{l}_slot{s}'
            refp=f'g_lane[{l}].g_slot[{s}].'+('g_mma' if s==0 else 'g_ma')+'.u_ma' if l<cl and not se else f'g_slane[{l}].u_ma'
            for suffix,unit,mul in [('ab','u_m',True),('sum','u_a',False)]+([('ce','u_c',True)] if s==0 else []):
                key=native+'_'+suffix
                for kind,m in raw['modules'].items():
                    cell=m['cells'].pop(refp+'.'+unit if kind=='gold' else key)
                    assert cell['type'].split('$')[0]==(('otpu_f' if kind=='gold' else 'otpu_vpu_datapath_')+('mul' if mul else 'add'))
                    for p,b in cell['connections'].items():
                        if p=='clk':assert b==m['ports']['clk']['bits'];continue
                        n=f'pipe_{key}_{p}';m['ports'][n]={'direction':'input' if p=='y' else 'output','bits':b};m['netnames'][n]={'bits':b,'hide_name':0,'attributes':{}}
    if se:
        for kind,m in raw['modules'].items():
            cell=m['cells'].pop('g_comp.u_comp' if kind=='gold' else 'u_comp')
            for p,b in cell['connections'].items():
                if p=='clk':assert b==m['ports']['clk']['bits'];continue
                if kind=='gold' and p in ['in_a','in_b','out_d','st_a','st_b','st_c','st_e','st_y']:
                    b=[v for i in reversed(range(len(b)//32)) for v in b[32*i:32*(i+1)]]
                n='composite_'+p
                direction='input' if cell['port_directions'][p]=='output' else 'output'
                m['ports'][n]={'direction':direction,'bits':b};m['netnames'][n]={'bits':b,'hide_name':0,'attributes':{}}
    pruned=prune_unobserved_register_bits(raw)
    gq={b for c in gold['cells'].values() if c['type']=='$dff' for b in c['connections']['Q']}
    nq={b for c in gate['cells'].values() if c['type']=='$dff' for b in c['connections']['Q']}
    mapping={};covered=set()
    for name,net in sorted(gate['netnames'].items(),key=lambda x:-len(x[1]['bits'])):
        nb=net['bits']
        if name.startswith(('_','$')) or not any(b in nq for b in nb) or set(nb)&covered:continue
        indices=[i for i,b in enumerate(nb) if b in nq]
        rn,special=state_ref(name)
        if special=='dst':gb=gold['netnames'][rn.removesuffix('.dr')+'.nr']['bits']+gold['netnames'][rn]['bits']
        else:gb=gold['netnames'][rn]['bits']
        # Native sr includes dead v; opt_clean retains only the live portions.
        if len(gb)!=len(nb):raise RuntimeError((name,rn,len(nb),len(gb)))
        gb=[gb[i] for i in indices];nb=[nb[i] for i in indices]
        if not set(gb)<=gq:raise RuntimeError(('not state',name,rn))
        gate['netnames'][name]={'bits':nb,'hide_name':0,'attributes':{}}
        gold['netnames'][name]={'bits':gb,'hide_name':0,'attributes':{}};mapping[name]=len(nb);covered.update(nb)
    covered_gold={b for n in mapping for b in gold['netnames'][n]['bits']}
    missing=gq-covered_gold
    if missing:print('MISSING',[(n,len(set(v['bits'])&missing)) for n,v in gold['netnames'].items() if not n.startswith('$') and set(v['bits'])&missing],flush=True)
    transformed=expose_steps(raw,mapping);steps=work/'steps.json';steps.write_text(json.dumps(transformed));miter=work/'miter.sv';miter.write_text(step_miter(transformed))
    proof=work/'proof.ys';proof.write_text(f'''read_json {steps.relative_to(ROOT)}
equiv_make gold gate equiv
hierarchy -top equiv
opt -full
simplemap t:$logic_and t:$logic_or t:$logic_not t:$and t:$or t:$not
opt -full
equiv_simple -short -undef
equiv_status -assert
''')
    files=[source,gen,ref,hier,extract,boxes,flat,flatten,steps,miter,proof,fp_summary,*[ROOT/p for p in resolved.values()],Path(__file__).resolve(),*[ROOT/'tools'/n for n in ['sparkle_transition.py','sparkle_mxu_transition.py','sparkle_provenance.py','prove_sparkle_se_tail.py']],*[ROOT/'OpenTPU'/f'{n}.lean' for n in ['VpuLanes','VpuDatapathSupport','Float','FloatConvert','SeHelpers','Circuit','VpuDecode']],ROOT/'rtl/vpu/otpu_vpu.sv',ROOT/'rtl/vpu/otpu_fp.sv',ROOT/'rtl/vpu/otpu_fpipe.sv']
    if se:files += [compgen,ROOT/'build/sparkle/formal_se_composite/vpu_mw21_summary.json',*[ROOT/p for p in verify(record['proof']['input_sha256']).values()]]
    before=hashes(files);(work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n');log=work/'proof.log'
    with log.open('w') as out:r=subprocess.run(['yosys','-Q','-T','-s',str(proof)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=900)
    assert hashes(files)==before
    assert (r.returncode!=0 and 'unproven $equiv' in log.read_text()) if mutation else r.returncode==0,str(log)
    print('PASS lanes',cfg,'mutation' if mutation else sum(mapping.values()),flush=True)
    return {'config':(*cfg,se),'mutation':mutation,'state_bits':sum(mapping.values()),'unobserved_pruned_bits':pruned,'arithmetic':entry,'input_sha256':before,'log':str(log.relative_to(ROOT))}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--config',nargs=2,type=int,default=[2,1]);ap.add_argument('--mutation',action='store_true');ap.add_argument('--streams',action='store_true');a=ap.parse_args()
    WORK.mkdir(parents=True,exist_ok=True);summary=WORK/('_'.join(map(str,a.config))+('_mutation' if a.mutation else '')+('_streams' if a.streams else '')+'_summary.json')
    try:summary.write_text(json.dumps({'status':'passed','proof':prove(tuple(a.config),a.mutation,a.streams)},indent=2)+'\n')
    except BaseException as e:summary.write_text(json.dumps({'status':'failed','error':str(e)},indent=2)+'\n');raise
