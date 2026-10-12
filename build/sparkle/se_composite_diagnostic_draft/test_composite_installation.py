"""Draft guards; execution requires the workspace bounded gate."""
from pathlib import Path
import pytest
from composite_installation import expected_installation,production_source_contract,strip_compiled_old_abi,SOURCE_ABI_BLOCK,OLD_DOC

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())

def sources():
    return [(ROOT/p).read_text() for p in ['OpenTPU/SeComposite.lean','OpenTPU/SeCompositeABI.lean']]+[(Path(__file__).parent/'core_helper.lean.txt').read_text()]

def test_exact_real_source_edit():
    core,abi=expected_installation(*sources())
    assert core.count('def withDiagnostics')==1
    assert 'let core ← withDiagnostics c core\n  return core ++' in core
    assert 'private def controlCheck' not in abi and SOURCE_ABI_BLOCK not in abi
    assert 'configuration mismatch; regenerate' in abi and 'otpu_se_comp_sparkle impl' in abi

@pytest.mark.parametrize('fault',['duplicate_core','duplicate_abi','return_predicate','guard','placement'])
def test_changed_source_anchor_rejected(fault):
    core,abi,helper=sources()
    if fault=='duplicate_core':core+='def toVerilog (c : Config) : Except String String := do\n'
    if fault=='duplicate_abi':abi+=SOURCE_ABI_BLOCK
    if fault=='return_predicate':abi=abi.replace('&& !out_v','&& out_v')
    if fault=='guard':abi=abi.replace('`ifndef SYNTHESIS','`ifdef SYNTHESIS')
    if fault=='placement':core=core.replace('  return core ++','  return "" ++')
    with pytest.raises(ValueError):expected_installation(core,abi,helper)

def production():return [(ROOT/p).read_text() for p in ['OpenTPU/VpuIssue.lean','OpenTPU/VpuDatapath.lean','OpenTPU/VpuLanes.lean']]

def test_production_specialization():assert production_source_contract(*production())['composite_config']==[8,21,3,2,True]

@pytest.mark.parametrize('index,old,new',[(0,'c.streams && c.lanes == 8','c.streams'),(1,'⟨c.lanes,21,3,2,true⟩','⟨c.lanes,22,3,2,true⟩'),(2,'"u_comp"','"u_other"')])
def test_changed_reached_specialization_rejected(index,old,new):
    values=production();values[index]=values[index].replace(old,new)
    with pytest.raises(ValueError):production_source_contract(*values)

def fixture():
    candidate='';block='''  always @(posedge clk) begin
    if(!rst && en && in_v && impl.ret_r)
      $fatal(1, "otpu_se_comp: entry while a chunk returns");
    if(!rst && impl.ret_r != (impl.vpos[24] && !out_v))
      $fatal(1, "otpu_se_comp: ret out of step");
  end'''
    for stage,offset in enumerate([6,16,23]):
        fn=f'  function automatic logic [104:0] diagnostic_uc{stage}(input logic [6:0] cp);\n    diagnostic_uc{stage}=0;\n  endfunction'
        candidate+=fn+'\n';block+='\n'+fn.replace('diagnostic_uc','expected_uc')+'\n'
        extra=(' || impl.rr_e != (impl.md0_6[MW+LANES+:4]==0 && (impl.md0_6[MW+LANES+4+:3]==1 || impl.md0_6[MW+LANES+4+:3]==2))') if stage==0 else ''
        block+=f'''  always @(posedge clk)
    if(!rst && impl.vpos[{offset}] &&
      (impl.uco{stage} != expected_uc{stage}(impl.md{stage}_6[MW+LANES+:7]){extra}))
      $fatal(1, "otpu_se_comp: output control out of step");
'''
    return 'module otpu_se_comp;\n`ifndef SYNTHESIS\n'+block+'`endif\nendmodule\n',candidate

def test_complete_compiled_legacy_observer_removal():
    wrapper,candidate=fixture();assert strip_compiled_old_abi(wrapper,candidate)=='module otpu_se_comp;\nendmodule\n'

@pytest.mark.parametrize('old,new',[('!out_v','out_v'),('!rst && en','!rst'),('posedge clk','negedge clk'),('expected_uc1=0','expected_uc1=1'),('`endif','wire unauthorized;\n`endif'),('`ifndef SYNTHESIS','`ifdef SYNTHESIS')])
def test_compiled_predicate_rom_guard_or_extra_statement_rejected(old,new):
    wrapper,candidate=fixture()
    with pytest.raises(ValueError):strip_compiled_old_abi(wrapper.replace(old,new),candidate)
