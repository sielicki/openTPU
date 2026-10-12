"""VPU datapath assembly transition proof with explicit qualified component contracts.

All alignment, OUTER RAM, reduction feedback/metadata, and row-buffer bits are
concrete. Lane/max/tree/tail outputs are shared only while every component input
is compared; their separate complete transition proofs discharge these contracts.
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
from check_sparkle_vpu_datapath import reference,ports
from prove_sparkle_vpu_datapath_lanes import reference as lanes_reference
from prove_sparkle_vpu_datapath_max import reference as max_reference
WORK=ROOT/'build/sparkle/formal_vpu_datapath'

def abstract_reference(cfg,ps):
    l,cl,se=cfg;s=reference(cfg,ps)
    # Fixed eight-lane stream buses are unused when LANES differs from eight.
    for name in ['s_fd','s_in_d']:
        s=s.replace(f'assign {name}[k]=i_{name}[32*k+:32];',f'if(k<8) assign {name}[k]=i_{name}[32*k+:32];else assign {name}[k]=0;')
    # Encapsulate the exact lane and maximum sections at their already-proved boundaries.
    lane=lanes_reference(l,cl,se).split(');',1)[0].replace('module gold ','(* blackbox *) module gold_lanes ',1)+');endmodule\n'
    maxi=max_reference(l).split(');',1)[0].replace('module gold ','(* blackbox *) module gold_max ',1)+');endmodule\n'
    body='localparam RMA=(RL>=2+LM+LA),DF=RL-(1+LM+LA);mt_t mo;f32_t lres [LANES],lmv [LANES],pacc [LANES],rsa [LANES],rsb [LANES],rfb [LANES];logic [LANES-1:0] lmm;\n'
    vecs=['xa','xb','xc','xd','rsa','rsb','rfb','c_uy','c_qy','lres','lmv','pacc']
    for n in vecs:
        w=256 if n in ['c_uy','c_qy'] else 32*l
        body+=f'wire [{w-1}:0] flat_{n};\n'
        for k in range(min(l,8) if n in ['c_uy','c_qy'] else l):
            body+=f'assign '+(f'{n}[{k}]=flat_{n}[{32*k}+:32];' if n in ['lres','lmv','pacc'] else f'flat_{n}[{32*k}+:32]={n}[{k}];')+'\n'
        if l<8 and n in ['c_uy','c_qy']:body+=f'assign flat_{n}[255:{32*l}]=0;\n'
    for n in ['c_sa','c_sb','c_sc','c_se']:
        body+=f'wire [{96*l-1}:0] flat_{n};\n'
        for st in range(3):
            for k in range(l):body+=f'assign {n}[{st}][{k}]=flat_{n}[{32*(st*l+k)}+:32];\n'
    ins=['.clk(clk)','.rst(rst)','.i_en(en)','.i_m0(m0)','.i_m0d(m0d)']+[f'.i_{n}(flat_{n})' for n in vecs[:9]]
    outs=['.o_mo(mo)','.o_lmm(lmm)','.o_o_c_hold(c_hold)','.o_o_c_sel(c_sel)']+[f'.o_{n}(flat_{n})' for n in vecs[9:]]+[f'.o_o_{n}(flat_{n})' for n in ['c_sa','c_sb','c_sc','c_se']]
    body+='gold_lanes u_lanes('+','.join(ins+outs)+');\n'
    a='  // ------------------------------------------------------------------ elementwise lanes\n';b='  // ------------------------------------------------------------------ RMAX\n'
    assert s.count(a)==1 and s.count(b)==1;s=s.split(a)[0]+body+b+s.split(b)[1]
    maxbody='rm_t mxm_q;f32_t mx_new,am4_m,am4_i;logic [16:0] mx_ni;logic am4_v,am4_l;logic [19:0] am4_a;\n'
    maxbody+='gold_max u_max('+','.join(['.clk(clk)','.rst(rst)','.en(en)','.xa(flat_xa)','.mask(m0.mask)','.m0r(m0r)','.col(m0.col)']+[f'.{n}({n})' for n in ['mx_have','mx_run','mx_ri','red_act','func','tag','imm','mx_new','mx_ni']]+['.mxm(mxm_q)']+[f'.o_{n}({n})' for n in ['am4_v','am4_l','am4_a','am4_m','am4_i']])+');\n'
    a=b;b='  // ------------------------------------------------------------------ RSUM / RSSQ\n';assert s.count(a)==1 and s.count(b)==1
    s=s.split(a)[0]+maxbody+b+s.split(b)[1]
    return s+'\n'+lane+maxi

def state_ref(name,cfg,gold):
    lanes,cl,se=cfg;aw=(256//lanes-1).bit_length()
    if name in ['m0','m0d','xa','xb']:return gold['netnames'][name]['bits']
    if m:=re.fullmatch(r'(cbuf|dbuf|rbuf)(\d+)\[(\d+)\]',name):
        t,l,i=m[1],int(m[2]),int(m[3]);n=f'g_cbuf[{l}].{t}[{i}]' if t!='rbuf' else f'g_rbuf[{l}].rb[{i}]'
        return gold['netnames'][n]['bits']
    if m:=re.fullmatch(r'(xc|xd)(\d+)',name):
        return gold['netnames'][f'{m[1]}[{m[2]}]']['bits']
    if m:=re.fullmatch(r'(mtq|mt|s_mt)_(\d+)',name):
        t,i=m[1],int(m[2]);n=7 if t=='s_mt' else 4 if t=='mt' else 3 if lanes<=8 else 2
        name=delay_name('u_smt' if t=='s_mt' else 'u_'+t,i,n)
        if name not in gold['netnames']:
            matches=[key for key in gold['netnames'] if key.endswith('.'+name)];assert len(matches)==1,(name,matches);name=matches[0]
        return gold['netnames'][name]['bits']
    if m:=re.fullmatch(r'red_fb(\d+)_(\d+)',name):
        return gold['netnames'][delay_name(f'g_red[{m[1]}].g_ma.u_fb',int(m[2]),64//lanes-8)]['bits']
    if m:=re.fullmatch(r'red_fbq(\d+)',name):return gold['netnames'][f'g_red[{m[1]}].g_ma.fbq']['bits']
    raise RuntimeError('unmapped state '+name)

def prove(cfg,mutation=False):
    l,cl,se=cfg;work=WORK/f'{l}_{cl}_{int(se)}'/('mutation' if mutation else 'proof');work.mkdir(parents=True,exist_ok=True)
    source=work/'native.sv';gen=work/'Generate.lean';ref=work/'reference.sv';hier=work/'hierarchy.json'
    gen.write_text('import OpenTPU.VpuDatapath\ndef main : IO Unit := do\n'+f'  IO.FS.writeFile "{source}" (← IO.ofExcept (OpenTPU.VpuDatapath.toVerilog ⟨{l},{cl},{str(bool(se)).lower()}⟩))\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    if mutation:source.write_text(source.read_text().replace('assign o_cap =',"assign o_cap = 1'b1 ^",1))
    ps=ports(source.read_text());ref.write_text(abstract_reference(cfg,ps))
    contracts=[]
    lanes_summary=ROOT/'build/sparkle/formal_vpu_datapath_lanes'/f'{l}_{cl}{"_streams" if se else ""}_summary.json'
    max_summary=ROOT/'build/sparkle/formal_vpu_datapath_max/summary.json'
    for path,selector in [(lanes_summary,lambda d:d['proof']),(max_summary,lambda d:next(p for p in d['proofs'] if p['lanes']==l and not p['mutation']))]:
        d=json.loads(path.read_text());assert d['status']=='passed',path;entry=selector(d);verify(entry['input_sha256']);contracts.append((path,entry))
    tree_summary=ROOT/'build/sparkle/formal_vtree/summary.json';d=json.loads(tree_summary.read_text());assert d['status']=='passed'
    entry=next(p for p in d['proofs'] if p['lanes']==l and p['latency']==4)
    verify(entry['input_sha256']);contracts.append((tree_summary,entry))
    if se:
        tail_summary=ROOT/'build/sparkle/formal_se_tail/summary.json';d=json.loads(tail_summary.read_text());assert d['status']=='passed'
        entry=next(p for p in d['proofs'] if p['configuration']==[8,7,1]);verify(entry['input_sha256']);contracts.append((tail_summary,entry))
    actual=module_tokens(source.read_text())
    for (_,entry),module_name in zip(contracts,['otpu_vpu_lanes_sparkle','otpu_vpu_max_sparkle','otpu_vtree_sparkle']+(['otpu_se_tail_sparkle'] if se else [])):
        candidates=[]
        for original,resolved_path in verify(entry['input_sha256']).items():
            if original.endswith('.sv'):
                tokens=module_tokens((ROOT/resolved_path).read_text())
                if module_name in tokens:candidates.append(tokens[module_name])
        assert candidates and actual[module_name] in candidates,('contract module changed',module_name)
    deps=[ROOT/'rtl/top/otpu_pkg.sv' ,*[ROOT/'rtl/vpu'/n for n in ['otpu_fp.sv','otpu_fpipe.sv','otpu_vtree.sv','otpu_se_comp.sv','otpu_se_tail.sv']]]
    extract,_=yosys(work,'extract',f'''read_slang --allow-use-before-declare --keep-hierarchy --top gold {' '.join(str(p.relative_to(ROOT)) for p in deps)} {ref.relative_to(ROOT)}
read_slang --keep-hierarchy --top otpu_vpu_datapath_sparkle {source.relative_to(ROOT)}
rename otpu_vpu_datapath_sparkle gate
proc
write_json {hier.relative_to(ROOT)}
''')
    raw=json.loads(hier.read_text());box_names={'gold_lanes','gold_max','otpu_vpu_lanes_sparkle','otpu_vpu_max_sparkle','otpu_vtree','otpu_vtree_sparkle','otpu_se_tail','otpu_se_tail_sparkle','otpu_fmul','otpu_fadd','otpu_vpu_datapath_mul','otpu_vpu_datapath_add'}
    for n,m in raw['modules'].items():
        if n.split('$')[0] in box_names:m['cells']={};m['netnames']={};m['attributes']['blackbox']='1'
    boxes=work/'boxes.json';boxes.write_text(json.dumps(raw));flat=work/'flat.json'
    flatten,_=yosys(work,'flatten',f'''read_json {boxes.relative_to(ROOT)}
flatten -noscopeinfo gold gate
memory_share
memory_map
opt_expr
opt_clean
write_json {flat.relative_to(ROOT)}
''')
    mods=json.loads(flat.read_text())['modules'];raw={'modules':{k:mods[k] for k in ['gold','gate']}}
    gold,gate=raw['modules'].values();gold['ports']={n.removeprefix('i_'):v for n,v in gold['ports'].items()}
    for n,v in gold['ports'].items():gold['netnames'][n]={'bits':v['bits'],'hide_name':0,'attributes':{}}
    pairs=[('u_lanes','u_lanes'),('u_max','u_max'),('u_tree','u_vt')]+([('u_tail','genblk1.u_tail')] if se else [])
    if l==16:pairs += [(f'red_{a}{k}',f'g_red[{k}].g_acc.{b}') for k in range(l) for a,b in [('mul','u_sq'),('add','u_acc')]]
    for native,reference_name in pairs:
        for kind,m in raw['modules'].items():
            name=reference_name if kind=='gold' else native
            if name not in m['cells'] and native=='u_tail':
                names=[n for n in m['cells'] if n.endswith('.u_tail')];assert len(names)==1;name=names[0]
            cell=m['cells'].pop(name)
            for p,b in cell['connections'].items():
                pn=p
                if kind=='gold' and native=='u_lanes':pn=p[2:] if p.startswith(('i_','o_')) else p
                if native=='u_max' and p.startswith('o_'):pn=p.removeprefix('o_')
                if native=='u_tree' and p=='schedule_collision':continue
                if p=='clk':assert b==m['ports']['clk']['bits'];continue
                if kind=='gold' and ((native=='u_tree' and p=='pacc') or (native=='u_tail' and p in ['fd','in_d','xd','xa','y_d','qp_d','u_a','u_b','u_c','u_e','u_y','q_a','q_b','q_c','q_y'])):
                    b=[x for i in reversed(range(len(b)//32)) for x in b[i*32:i*32+32]]
                n=f'contract_{native}_{pn}';direction='input' if cell['port_directions'][p]=='output' else 'output'
                m['ports'][n]={'direction':direction,'bits':b};m['netnames'][n]={'bits':b,'hide_name':0,'attributes':{}}
    pruned=prune_unobserved_register_bits(raw)
    gq={b for cell in gold['cells'].values() if cell['type']=='$dff' for b in cell['connections']['Q']};nq={b for cell in gate['cells'].values() if cell['type']=='$dff' for b in cell['connections']['Q']}
    mapping={};covered=set()
    for n,net in sorted(gate['netnames'].items(),key=lambda i:-len(i[1]['bits'])):
        nb=net['bits']
        if n.startswith(('$','_','contract_','o_')) or not any(b in nq for b in nb) or set(nb)&covered:continue
        gb=state_ref(n,cfg,gold);assert len(gb)==len(nb),(n,len(gb),len(nb))
        ix=[i for i,b in enumerate(nb) if b in nq];nb=[nb[i] for i in ix];gb=[gb[i] for i in ix];assert set(gb)<=gq,n
        gold['netnames'][n]={'bits':gb,'hide_name':0,'attributes':{}};gate['netnames'][n]={'bits':nb,'hide_name':0,'attributes':{}};mapping[n]=len(nb);covered.update(nb)
    transformed=expose_steps(raw,mapping)
    for m in transformed['modules'].values():
        for n in list(m['ports']):
            clean=n.replace('[','_').replace(']','')
            if clean!=n:m['ports'][clean]=m['ports'].pop(n);m['netnames'][clean]=m['netnames'].pop(n)
    steps=work/'steps.json';steps.write_text(json.dumps(transformed));miter=work/'miter.sv';miter.write_text(step_miter(transformed))
    proof=work/'proof.ys';proof.write_text(f'''read_json {steps.relative_to(ROOT)}
equiv_make gold gate equiv
hierarchy -top equiv
opt -full
simplemap t:$logic_and t:$logic_or t:$logic_not t:$and t:$or t:$not
opt -full
equiv_simple -short -undef
equiv_status -assert
''')
    files=[source,gen,ref,hier,extract,boxes,flat,flatten,steps,miter,proof,Path(__file__).resolve(),*deps,ROOT/'rtl/vpu/otpu_vpu.sv',*sorted((ROOT/'OpenTPU').glob('VpuDatapath*.lean')),ROOT/'OpenTPU/VpuLanes.lean',*[ROOT/'tools'/n for n in ['check_sparkle_vpu_datapath.py','prove_sparkle_vpu_datapath_lanes.py','prove_sparkle_vpu_datapath_max.py','sparkle_transition.py','sparkle_mxu_transition.py']]]
    for path,entry in contracts:files += [path,*[ROOT/p for p in verify(entry['input_sha256']).values()]]
    before=hashes(files);(work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n');log=work/'proof.log'
    with log.open('w') as out:r=subprocess.run(['yosys','-Q','-T','-s',str(proof)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=900)
    assert hashes(files)==before
    assert (r.returncode!=0 and 'unproven $equiv' in log.read_text()) if mutation else r.returncode==0,str(log)
    print('PASS datapath composition',cfg,'mutation' if mutation else sum(mapping.values()),flush=True)
    return {'config':cfg,'mutation':mutation,'state_bits':sum(mapping.values()),'pruned_unobserved_bits':pruned,'contracts':[e for p,e in contracts],'input_sha256':before,'log':str(log.relative_to(ROOT))}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--config',nargs=3,type=int,default=[8,8,1]);ap.add_argument('--mutation',action='store_true');a=ap.parse_args();WORK.mkdir(parents=True,exist_ok=True);summary=WORK/('_'.join(map(str,a.config))+('_mutation' if a.mutation else '')+'_summary.json')
    try:summary.write_text(json.dumps({'status':'passed','proof':prove(tuple(a.config),a.mutation)},indent=2)+'\n')
    except BaseException as e:summary.write_text(json.dumps({'status':'failed','error':str(e)},indent=2)+'\n');raise
