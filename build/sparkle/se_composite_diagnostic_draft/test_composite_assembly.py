"""Complete-token and strict diagnostic-normalization guards; draft unexecuted."""
import pytest
from composite_assembly import guarded_block,normalize,exact_whole_assembly

CORE='''`ifndef SYNTHESIS
  wire finite=(count>=limit);
  always @(posedge clk)
    if (!rst && en && in_v && ret_r)
      $fatal(1,"collision");
`endif
'''
WRAPPER='''`ifndef SYNTHESIS
  always @(posedge clk)
    if (!rst && impl.ret_r != (impl.vpos[24] && !out_v))
      $fatal(1,"return");
`endif
'''

def design(current=False,wrapper=False):
    text='''`default_nettype none
(* keep="true" *) module parent(input clk);
 otpu_se_comp_sparkle child(.clk(clk));
endmodule
module otpu_se_comp_sparkle(input clk);
 wire same;
'''+(CORE if current else '')+'endmodule\nmodule support();\nendmodule\n'
    if wrapper:text+='module otpu_se_comp();\n wire packed_data;\n'+('' if current else WRAPPER)+'endmodule\n'
    return text

def compare(tmp_path,old,new):
    a=tmp_path/'old.sv';b=tmp_path/'new.sv';an=tmp_path/'an.sv';bn=tmp_path/'bn.sv';a.write_text(old);b.write_text(new)
    left=normalize(a,an,False,CORE,WRAPPER);right=normalize(b,bn,True,CORE,WRAPPER)
    return left,right,exact_whole_assembly(an,bn)

@pytest.mark.parametrize('wrapper',[False,True])
def test_complete_valid_correspondence(tmp_path,wrapper):
    left,right,proof=compare(tmp_path,design(False,wrapper),design(True,wrapper))
    assert left['removed_blocks']==int(wrapper) and right['removed_blocks']==1
    assert proof['global_directives_and_contexts_equal']

def test_literal_line_wrapping_only_is_accepted(tmp_path):
    compare(tmp_path,design(),design(True).replace('count>=limit','count >=\n limit'))

@pytest.mark.parametrize('old,new',[('!rst && en','!rst'),('count>=limit','count>limit'),('"collision"','"other"'),
 ('`ifndef SYNTHESIS','`ifdef SYNTHESIS'),('`endif','wire extra;\n`endif'),('`endif\nendmodule','`endif\nwire extra;\nendmodule')])
def test_diagnostic_semantic_or_placement_changes_rejected(tmp_path,old,new):
    with pytest.raises(RuntimeError):compare(tmp_path,design(),design(True).replace(old,new))

@pytest.mark.parametrize('old,new',[('keep="true"','keep="false"'),('child(.clk(clk))','child(.clk(1\'b0))'),
 ('wire same','wire altered'),('module support();','module support(); wire extra;'),
 ('`default_nettype none','`default_nettype wire'),('wire packed_data','wire changed')])
def test_every_untouched_token_attribute_directive_support_module_bound(tmp_path,old,new):
    with pytest.raises(RuntimeError):compare(tmp_path,design(False,True),design(True,True).replace(old,new))

@pytest.mark.parametrize('fault',['missing','duplicate','wrong_module','module_added','module_removed'])
def test_complete_module_and_block_inventory(tmp_path,fault):
    new=design(True)
    if fault=='missing':new=new.replace(CORE,'')
    if fault=='duplicate':new=new.replace(CORE,CORE+CORE)
    if fault=='wrong_module':new=new.replace(CORE,'').replace('module support();\n','module support();\n'+CORE)
    if fault=='module_added':new+='module extra();\nendmodule\n'
    if fault=='module_removed':new=new.replace('module support();\nendmodule\n','')
    with pytest.raises(RuntimeError):compare(tmp_path,design(),new)

def test_qualified_guard_extraction_exact():
    assert guarded_block('module example;\n'+CORE+'endmodule\n')==CORE
    for text in ['module example;\n'+CORE+'wire extra;\nendmodule\n',CORE+CORE+'endmodule\n']:
        with pytest.raises(RuntimeError):guarded_block(text)
