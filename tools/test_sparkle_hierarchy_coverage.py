import pytest
from audit_sparkle_hierarchy_coverage import inventory, add_coverage

def test_inventory_preserves_unknown_and_parameters(tmp_path):
    p=tmp_path/'x.sv';p.write_text('module top(input logic clk);\n leaf u0(.clk(clk));\n UNKNOWN #(.W(4)) ext(.x({clk,clk}));\nendmodule\nmodule leaf(input clk); endmodule\n')
    modules,instances=inventory(p)
    assert modules==['top','leaf']
    assert [(i['parent'],i['type'],i['name']) for i in instances]==[('top','leaf','u0'),('top','UNKNOWN','ext')]
    assert instances[1]['parameters']==['.','W','(','4',')']

@pytest.mark.parametrize('text',['module top; leaf u(.x(x))','module top; module leaf; endmodule','module top; leaf u(.x(x)),v(.x(y)); endmodule'])
def test_invalid_inventory_fails_closed(tmp_path,text):
    p=tmp_path/'x.sv';p.write_text(text)
    with pytest.raises(Exception):inventory(p)

def test_claimed_module_must_match():
    with pytest.raises(Exception):add_coverage({}, {'leaf':'wrong'},'proof',{'leaf':'actual'})

def test_preprocessor_followed_by_conditional_not_instance(tmp_path):
    p=tmp_path/'x.sv';p.write_text('module top;\n`ifdef SYNTHESIS\nif (1) begin\nleaf u();\nend\n`endif\nendmodule\n')
    assert [i['name'] for i in inventory(p)[1]]==['u']

def test_function_header_not_external_instance(tmp_path):
    p=tmp_path/'x.sv';p.write_text('module top;\nfunction automatic bit conflict(input bit a); return a; endfunction\nleaf u();\nendmodule\n')
    assert [i['type'] for i in inventory(p)[1]]==['leaf']
