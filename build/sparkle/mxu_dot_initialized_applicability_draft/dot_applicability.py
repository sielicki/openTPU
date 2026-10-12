"""Source-only contracts; callers must authenticate every supplied receipt first."""
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import require
from check_sparkle_mxu_dsp_initial_consumers import COUNTS,MODULE_BY_CASE
from check_sparkle_mxu_cascade import expected_cuts
DOT='otpu_mxu_dot_sparkle'
ORDER=['a0','clk','en_c','w0','m0','ws0','ws0h','mb0','mb0h','hi0','c_hi','wf0','pr0','s4','m4','ws4','ws4h']
INPUTS={'clk':1,'pr0':1,'wf0':2,'c_hi':4,'hi0':4,'mb0h':16,'mb0':16,'ws0h':32,'ws0':32,'m0':7,'w0':1024,'a0':4096,'en_c':1}
OUTPUTS={'ws4h':32,'ws4':32,'m4':7,'s4':92}
ABI={**{k:{'direction':'input','width':v} for k,v in INPUTS.items()},**{k:{'direction':'output','width':v} for k,v in OUTPUTS.items()}}

def certificate_contract(record):
    require(record['status']=='initialized_physical_dot_trace_refinement_certified' and record['initialized_dot_proven'] is True,
            'Completed initialized dot certificate required; prefixes do not qualify')
    require(record['config']==[128,4,2,16] and record['production_parent_applicability'] is False and record['whole_mxu_proven'] is False,
            'Exact local initialized theorem scope differs')
    r=record['global_relation']
    require(r['parent_state_bits']==61323 and r['helper_state_bits']==102516 and r['mapped_state_bits']==163839 and
            r['reference_only_state_bits']==2048 and r['reference_physical_state_bits']==165887,'Complete physical state scope differs')
    counts={c:n for c,n in r['helper_counts'].items() if n}
    require(counts==COUNTS and sum(counts.values())==516,'Complete helper occurrence scope differs')
    require(record['parent_interface']['observed_and_D_bits']==100726 and record['cascade_induction']['nodes']==1028,
            'Complete parent equality/cascade scope differs')

def enclosing_dot_edge(tokens):
    tokens=list(tokens);hits=[i for i,t in enumerate(tokens) if t==DOT]
    require(len(hits)==1,'Exactly one enclosing native dot instance required');start=hits[0]
    expected=[DOT,'dot','(']
    for i,p in enumerate(ORDER):
        if i:expected.append(',')
        expected+=['.',p,'(','act_data' if p=='a0' else p,')']
    expected+=[')', ';']
    require(tokens[start:start+len(expected)]==expected,'Actual full dot wiring/order/override differs')
    return {'instance':'dot','ordered_ports':ORDER,'connections':{p:('act_data' if p=='a0' else p) for p in ORDER},'reset_port_present':False}

def reached_dot(hierarchy,binding,module_sha,proven_context,current_context,leaf_coverage,cuts):
    """Augment, never replace, production_occurrences' full528 DSP audits."""
    paths={}
    for row in hierarchy['paths']:
        require(row['path'] not in paths,'Duplicate reached path');paths[row['path']]=row['specialization']
    dotpaths=[p for p,s in paths.items() if hierarchy['nodes'][s]['module']==DOT]
    require(len(dotpaths)==1,'Exact one reached physical dot required per production assembly')
    dotpath=dotpaths[0];sid=paths[dotpath];node=hierarchy['nodes'][sid];bound=binding['nodes'][sid]
    require(bound['module']==DOT and node['effective_parameters']==node['overrides']==bound['effective_parameters']=={},
            'Monomorphic dot specialization differs')
    require(node['ports']==ABI and bound['module_sha256']==module_sha,'Complete dot ABI/body identity differs')
    # Incoming directive identity is checked against current/proved source by
    # caller; bound identity fields are schema-dependent and never invented here.
    require(proven_context==current_context,'Proven/current dot directive context differs')
    parentpath,instance=dotpath.rsplit('/',1);require(instance=='dot' and parentpath in paths,'Dot enclosing occurrence missing')
    parent=hierarchy['nodes'][paths[parentpath]]
    require(parent['module']=='otpu_mxu_sparkle','Wrong actual enclosing MXU')
    edges=[c for c in parent['children'] if c['instance']=='dot']
    require(len(edges)==1 and edges[0]['module']==DOT and edges[0]['overrides']=={} and
            edges[0]['ports']==ABI and edges[0]['unconnected_output_ports']=={},'Complete enclosing edge ABI differs')
    require(cuts==expected_cuts(),'Exact parent reference/native cuts or parameters differ')
    expected={}
    for cut in cuts:
        cfg=cut['parameters'];case=('pe_'+''.join(str(cfg[k]) for k in ('FIRST','LAST','WREG')) if 'FIRST' in cfg else 'colend_23')
        name=cut['native'];require(name not in expected and '/' not in name and '.' not in name,'Duplicate/nonlocal helper path')
        expected[name]=MODULE_BY_CASE[case]
    require(len(expected)==516 and len(node['children'])==516,'Dot complete direct child inventory differs')
    children={}
    for c in node['children']:
        require(c['instance'] not in children,'Duplicate child occurrence');children[c['instance']]=c['module']
        require(c['overrides']=={} and c['unconnected_output_ports']=={},'Helper overrides/omitted pins differ')
    require(children==expected,'Actual dot helper path/configuration differs from initialized parent')
    actual=set()
    for case,rows in leaf_coverage['helper_paths'].items():
        for path in rows:
            require(path.startswith(dotpath+'/') and path[len(dotpath)+1:] in expected and
                    expected[path[len(dotpath)+1:]]==MODULE_BY_CASE[case],'Leaf occurrence outside proved dot or wrong case')
            require(path not in actual,'Duplicated helper occurrence');actual.add(path)
    require(actual=={dotpath+'/'+p for p in expected},'Full initialized parent/helper occurrence join incomplete')
    dsp=leaf_coverage['dsp_primitive_paths'];require(len(dsp)==len(set(dsp))==528 and all(p.startswith(dotpath+'/') for p in dsp),'DSP terminal scope differs')
    return {'path':dotpath,'specialization':sid,'helper_paths':sorted(actual),'dsp_paths':dsp,'ports':ABI}
