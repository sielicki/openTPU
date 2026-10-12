"""Authenticate exact whole-MXU behavioral composition coverage.

This is a wiring/token/provenance audit, not a new solver proof. A configuration
is covered only when its actual controller, dot, epilogue and concrete FP leaf
emissions match authenticated successful proofs. Missing component configurations
are reported explicitly. DSP48E1 physical replacement is outside this audit.
"""
import hashlib
import json
import re
import subprocess
from pathlib import Path
from check_sparkle_physical import functional_tokens
from sparkle_provenance import archive, verify
from mxu_control_reference import reference as control_reference, pipeline_ports
from prove_sparkle_mxu_dot import reference as dot_reference
from prove_sparkle_mxu_epilogue import reference as epilogue_reference

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'build/sparkle/mxu_composition'


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def modules(text):
    parts=re.findall(r'\bmodule\s+(\w+)\b.*?\bendmodule\b',text,re.S)
    bodies=re.findall(r'\bmodule\s+\w+\b.*?\bendmodule\b',text,re.S)
    assert len(set(parts))==len(parts),'duplicate emitted module'
    return dict(zip(parts,map(functional_tokens,bodies)))


def connections(text):
    result={}
    for module,instance,ports in re.findall(r'^\s*(otpu_mxu_\w+)\s+(\w+)\s*\((.*?)\);',text,re.S|re.M):
        pairs=re.findall(r'\.(\w+)\((\w+)\)',ports)
        assert len(pairs)==len(dict(pairs))
        assert re.sub(r'\s','',ports)==','.join(f'.{p}({n})' for p,n in pairs)
        result[instance]={'module':module,'ports':dict(pairs)}
    return result


def check_wiring(text,cfg):
    d,cols,_,depth,lanes,_,_=cfg
    inputs=['start','go','cmd','act_data','act_scale','a_gnt','a_rvalid','a_rdata','a_rdata2',
            'b_gnt','b_rvalid','b_rdata','t_rdata','t_gnt']
    outputs=['rdy','done','computing','pf_level','pf_starve','pf_block','pf_u','pf_uv','act_blk','act_blk2',
             'act_hi','act_grp','act_ren','a_req','a_addr','b_req','b_addr','t_ren','t_raddr','t_wen','t_waddr','t_wdata']
    control=['clk','rst']+inputs+outputs+[n for n,_ in pipeline_ports(d,cols)]+['rowr','lv2']
    dot=['clk','en_c','w0','m0','ws0','ws0h','mb0','mb0h','hi0','c_hi','wf0','pr0','s4','m4','ws4','ws4h']
    epi=['clk','rst','en_c','s4','m4','ws4','ws4h','hi0','pr0','act_scale','p_M','rowr','lv2']
    expected={name:{'module':f'otpu_mxu_{name}_sparkle','ports':dict((p,p) for p in ports)}
              for name,ports in [('control',control),('dot',dot),('epilogue',epi)]}
    expected['dot']['ports']['a0']='act_data'
    actual=connections(text)
    assert actual==expected,'whole MXU component wiring changed'
    # Native top is a pure three-instance composition; no extra logic or state.
    residual=re.sub(r'//[^\n]*','',text)
    residual=residual.split(');',1)[1]
    residual=re.sub(r'otpu_mxu_\w+\s+\w+\s*\(.*?\);','',residual,flags=re.S)
    residual=re.sub(r'\blogic(?:\s+\[\d+:\d+\])?\s+\w+;','',residual)
    residual=residual.replace("assign no_reset = 1'd0;",'').replace('endmodule','')
    assert not residual.strip(),'whole top includes unqualified logic'
    return actual


def main():
    WORK.mkdir(parents=True,exist_ok=True)
    old=WORK/'summary.json'
    if old.exists():
        previous=json.loads(old.read_text())
        for record in previous.get('covered',[]):
            for path in verify(record['artifact_sha256']).values():archive(ROOT/path)
        archive(old)
    report={'status':'running','scope':'behavioral composition audit; no physical DSP qualification',
            'covered':[],'missing_components':[]}
    def save(): (WORK/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    report['audit_tool_sha256']=sha(Path(__file__).resolve())
    report['compiled_runner_sha256']=sha(ROOT/'tools/sparkle_compiled_lean.py')
    save()
    try:
        summaries={}
        for kind in ['control','dot','epilogue']:
            path=ROOT/f'build/sparkle/formal_mxu_{kind}/summary.json'
            doc=json.loads(path.read_text());assert doc['status']=='passed'
            archive(path)
            summaries[kind]=doc
        report['proof_summary_sha256']={k:sha(ROOT/f'build/sparkle/formal_mxu_{k}/summary.json') for k in summaries}
        dots={tuple(p['config']):p for p in summaries['dot']['proofs']}
        epis={tuple(p['config']):p for p in summaries['epilogue']['proofs']}
        from prove_sparkle_slice import source_closure
        sources=sorted(set(source_closure(ROOT/'OpenTPU/MxuABI.lean')) | set(source_closure(ROOT/'OpenTPU/MxuStoragePhysical.lean')))
        before={str(p.relative_to(ROOT)):sha(p) for p in sources}
        with (WORK/'build.log').open('w') as out:
            subprocess.run(['lake','build','opentpu-gen','OpenTPU.MxuABI','OpenTPU.MxuStoragePhysical'],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True)
        for cp in summaries['control']['results']:
            cfg=cp['configuration'];d,cols,rows,depth,lanes,impl,cl=cfg;key=(d,cols,impl,cl)
            absent=[name for name,index in [('dot',dots),('epilogue',epis)] if key not in index]
            if absent:
                report['missing_components'].append({'configuration':cfg,'missing':absent})
                continue
            proofs={'control':cp,'dot':dots[key],'epilogue':epis[key]}
            resolved={}
            proof_logs={}
            for kind,p in proofs.items():
                assert p['status']=='passed'
                resolved[kind]=verify(p['input_sha256'])
                assert p['input_sha256']['rtl/mxu/otpu_mxu.sv']==sha(ROOT/'rtl/mxu/otpu_mxu.sv')
                if 'leaves' in p:verify(p['leaves']['input_sha256'])
                proofkey=cfg if kind=='control' else key
                directory=p.get("proof_directory",f"build/sparkle/formal_mxu_{kind}/{'_'.join(map(str,proofkey))}")
                log=ROOT/directory/"proof.log"
                for index,ram in enumerate(p.get("ram_primitives",[])):
                    verify(ram["input_sha256"])
                    ramlog=ROOT/directory/f"ram{index}.z3.log"
                    assert ramlog.read_text().split()==["sat","unsat","unsat","sat"]
                    proof_logs[str(ramlog.relative_to(ROOT))]=archive(ramlog)
                assert 'Equivalence successfully proven!' in log.read_text(),kind+' solver did not pass'
                proof_logs[str(log.relative_to(ROOT))]=archive(log)
            name='_'.join(map(str,cfg));work=WORK/name;work.mkdir(exist_ok=True)
            gen=work/'Generate.lean'
            body='import OpenTPU.MxuABI\nimport OpenTPU.MxuStoragePhysical\ndef main : IO Unit := do\n'
            body+=f'  let c : OpenTPU.Mxu.Config := {{d:={d},columns:={cols},rows:={rows},depth:={depth},lanes:={lanes},implementation:={impl},chainLength:={cl}}}\n'
            body+='  let _ ← IO.ofExcept c.validateWhole\n'
            expressions={'control':'String.join ((OpenTPU.Mxu.controlModules c).map Sparkle.Backend.Verilog.toVerilog)',
                'dot':'Sparkle.Backend.Verilog.toVerilog (OpenTPU.MxuDot.build c)',
                'epilogue':'Sparkle.Backend.Verilog.toVerilog (OpenTPU.MxuEpilogue.build c)',
                'leaves':'Sparkle.Backend.Verilog.toVerilog OpenTPU.MxuEpilogue.multiply ++ Sparkle.Backend.Verilog.toVerilog OpenTPU.MxuEpilogue.addition',
                'top':'Sparkle.Backend.Verilog.toVerilog (OpenTPU.Mxu.build c)',
                'whole':'String.join ((OpenTPU.Mxu.modules c).map Sparkle.Backend.Verilog.toVerilog)',
                'abi':'OpenTPU.Mxu.wrapper c','physical_control':'← IO.ofExcept (OpenTPU.MxuStoragePhysical.emit c)'}
            for part,expr in expressions.items():body+=f'  IO.FS.writeFile "{work/part}.sv" ({expr})\n'
            gen.write_text(body)
            from sparkle_compiled_lean import run_generator
            run_generator(gen)
            assert before=={str(p.relative_to(ROOT)):sha(p) for p in sources},'generator sources changed during emission'
            for p in sources:archive(p)
            for kind,p in proofs.items():
                proofkey=cfg if kind=='control' else key
                directory=p.get("proof_directory",f"build/sparkle/formal_mxu_{kind}/{'_'.join(map(str,proofkey))}")
                old=directory+"/native.sv"
                assert functional_tokens((work/f'{kind}.sv').read_text())==functional_tokens((ROOT/resolved[kind][old]).read_text()),kind
                refpath=old.replace('/native.sv','/reference.sv')
                currentref=control_reference(cfg,True) if kind=='control' else (dot_reference(*key) if kind=='dot' else epilogue_reference(*key))
                assert functional_tokens(currentref)==functional_tokens((ROOT/resolved[kind][refpath]).read_text()),kind+' reference extraction changed'
            leaf=proofs['epilogue']['leaves'];leafpaths=verify(leaf['input_sha256'])
            candidates=[p for p in leafpaths if p.endswith('/float.sv')];assert len(candidates)==1
            leaflog=Path(leaf['log'])
            assert 'Induction step proven: SUCCESS!' in leaflog.read_text()
            proof_logs[str(leaflog.relative_to(ROOT))]=archive(leaflog)
            current=(work/'leaves.sv').read_text().replace('otpu_mxu_fmul','otpu_fmul_sparkle_2').replace('otpu_mxu_fadd','otpu_fadd_sparkle_4')
            assert functional_tokens(current)==functional_tokens((ROOT/leafpaths[candidates[0]]).read_text())
            assert functional_tokens((work/'physical_control.sv').read_text())==functional_tokens((work/'control.sv').read_text())
            expected={}
            for part in ['control','dot','epilogue','leaves','top']:
                addition=modules((work/f'{part}.sv').read_text());assert not(expected.keys() & addition.keys());expected.update(addition)
            assert modules((work/'whole.sv').read_text())==expected
            toptext=(work/'top.sv').read_text()
            wiring=check_wiring(toptext,cfg)
            def widths(text):
                return {n:(int(hi)-int(lo)+1 if hi else 1) for hi,lo,n in re.findall(r'\blogic(?:\s+\[(\d+):(\d+)\])?\s+(\w+)',text)}
            topwidths=widths(toptext)
            for kind,instance in wiring.items():
                component=(work/f'{kind}.sv').read_text().split('module '+instance['module'],1)[1].split(');',1)[0]
                portwidths=widths(component)
                assert portwidths.keys()==instance['ports'].keys()
                assert all(topwidths[net]==portwidths[port] for port,net in instance['ports'].items()),kind+' width mismatch'
            for corrupted in [toptext.replace('.a0(act_data)','.a0(w0)',1),toptext.replace('endmodule',"assign rdy = 1'b0;\nendmodule",1)]:
                try:check_wiring(corrupted,cfg)
                except AssertionError:pass
                else:raise AssertionError('composition mutation was accepted')
            record={'configuration':cfg,'component_state_bits':{k:p['state_bits'] for k,p in proofs.items()},
                    'proof_input_sha256':{k:p['input_sha256'] for k,p in proofs.items()},
                    'fp_leaf_input_sha256':leaf['input_sha256'],'solver_log_sha256':proof_logs,'wiring':wiring,
                    'generating_source_sha256':before,'artifact_sha256':{str(p.relative_to(ROOT)):sha(p) for p in work.glob('*.sv')}}
            (work/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
            report['covered'].append(record);save()
        assert report['covered'],'no whole configuration has matching component proofs'
        assert sha(Path(__file__).resolve())==report['audit_tool_sha256']
        assert sha(ROOT/'tools/sparkle_compiled_lean.py')==report['compiled_runner_sha256']
        report['status']='passed';save()
        print(f"PASS MXU composition audit: {len(report['covered'])} fully matched configurations; {len(report['missing_components'])} controller configurations explicitly lack component coverage")
    except BaseException as error:
        report['status']='failed';report['error']=str(error);save();raise


if __name__=='__main__':main()
