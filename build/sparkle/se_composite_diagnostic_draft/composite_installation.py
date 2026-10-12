"""Exact reviewed source edit and compiled ABI observer-removal contracts."""
from composite_observers import need,function

OLD_CORE_SHA='76435a92565e4d4d831da252e6ce03e41283d4c95bbd0181f82b011397b64b32'
OLD_ABI_SHA='101c245c0673b199af5b8049ccec3dae5a2b0535f2241bb54079dc07e5bd184b'
HELPER_SHA='18064d570f3b9f4c8e46a1ea2822b1b1ede6da227675a2f1007034ada39359d2'
OLD_DOC='/-- ABI packing and simulation assertions. All functional hardware is native. -/'
NEW_DOC='/-- ABI packing; functional hardware and simulation checks are in the native core. -/'
SOURCE_ABI_BLOCK=r'''`ifndef SYNTHESIS
  always @(posedge clk) begin
    if(!rst && en && in_v && impl.ret_r)
      $fatal(1, \"otpu_se_comp: entry while a chunk returns\");
    if(!rst && impl.ret_r != (impl.vpos[{c.period-1}] && !out_v))
      $fatal(1, \"otpu_se_comp: ret out of step\");
  end
{String.intercalate "\n" ((List.range c.stages).map (controlCheck c))}
`endif
'''


def expected_installation(core,abi,helper):
    """Only use authenticated old sources and reviewed helper; never apply here."""
    anchor='def toVerilog (c : Config) : Except String String := do\n'
    need(core.count(anchor)==1 and 'def withDiagnostics' not in core,'Old core injection point differs')
    old='  let core ← Backend.withRegisterHints core (registerHints c)\n  return core ++'
    new='  let core ← Backend.withRegisterHints core (registerHints c)\n  let core ← withDiagnostics c core\n  return core ++'
    need(core.count(old)==1,'Core placement is not immediately after register hints')
    changed=core.replace(anchor,helper.rstrip()+'\n\n'+anchor,1).replace(old,new,1)
    start='private def controlCheck (c : Config) (stage : Nat) : String :=\n'
    need(abi.count(start)==abi.count(OLD_DOC)==abi.count(SOURCE_ABI_BLOCK)==1,
         'Original exact ABI helper/doc/observer template differs')
    prefix,rest=abi.split(start);_,after=rest.split(OLD_DOC)
    changed_abi=(prefix+NEW_DOC+after).replace(SOURCE_ABI_BLOCK,'',1)
    return changed,changed_abi


def strip_compiled_old_abi(text,candidate):
    """Strip only the compiled exact8/21/3/2/EXT1 legacy observer block."""
    marker='\n`ifndef SYNTHESIS\n'
    need(text.count(marker)==1 and text.endswith('`endif\nendmodule\n'),
         'Old ABI diagnostic guard/placement differs')
    prefix,tail=text.split(marker);block=tail[:-len('`endif\nendmodule\n')]
    initial='''  always @(posedge clk) begin
    if(!rst && en && in_v && impl.ret_r)
      $fatal(1, "otpu_se_comp: entry while a chunk returns");
    if(!rst && impl.ret_r != (impl.vpos[24] && !out_v))
      $fatal(1, "otpu_se_comp: ret out of step");
  end'''
    need(block.count(initial)==1,'Exact old collision/return ABI process changed')
    rest=block.replace(initial,'',1)
    for stage,offset in enumerate([6,16,23]):
        actual=function(rest,'expected_uc'+str(stage))
        expected=function(candidate,'diagnostic_uc'+str(stage)).replace('diagnostic_uc','expected_uc')
        need(actual==expected,'Legacy ABI ROM table differs from qualified actual candidate')
        rest=rest.replace(actual,'',1)
        extra=(' || impl.rr_e != (impl.md0_6[MW+LANES+:4]==0 && '
               '(impl.md0_6[MW+LANES+4+:3]==1 || impl.md0_6[MW+LANES+4+:3]==2))') if stage==0 else ''
        control=f'''  always @(posedge clk)
    if(!rst && impl.vpos[{offset}] &&
      (impl.uco{stage} != expected_uc{stage}(impl.md{stage}_6[MW+LANES+:7]){extra}))
      $fatal(1, "otpu_se_comp: output control out of step");'''
        need(rest.count(control)==1,'Exact old ABI control predicate differs')
        rest=rest.replace(control,'',1)
    need(not rest.strip(),'Additional legacy ABI statements would be removed')
    return prefix+'\nendmodule\n'


def production_source_contract(issue,datapath,lanes):
    """Bind the actual production config derivation, without extrapolating proofs."""
    enable='def Config.comp8 (c : Config) := c.streams && c.lanes == 8'
    emission='''  let streams ← if c.comp8 then do
    let composite ← SeComposite.toVerilog ⟨c.lanes,21,3,2,true⟩'''
    reached='''    if c.comp8 then
      emitInstance "otpu_se_comp_sparkle" "u_comp"'''
    need(issue.count(enable)==datapath.count(emission)==lanes.count(reached)==1,
         'Production composite presence/config derivation changed')
    return {'present_when':'streams && lanes == 8','composite_config':[8,21,3,2,True],
            'other_valid_vpu_lane_counts':[2,4,16],
            'standalone_other_configs_qualified':False}
