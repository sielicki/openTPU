import OpenTPU.SeTail

namespace OpenTPU.SeTail

/-- Only lane packing and simulation contracts; the hardware is the native core. -/
def wrapper (c : Config) : String := Id.run do
  let inputs := ["fd","in_d","u_a","u_b","u_c","u_e","q_a","q_b","q_c"]
  let outputs := ["xd","xa","y_d","qp_d","u_y","q_y"]
  let declarations := String.intercalate "\n" ((inputs++outputs).map fun n =>
    s!"  wire [LANES*32-1:0] p_{n};")
  let assignments := String.intercalate "\n" <|
    (inputs.map fun n => s!"    assign p_{n}[32*l+:32]={n}[l];") ++
    (outputs.map fun n => s!"    assign {n}[l]=p_{n}[32*l+:32];")
  let connections := String.intercalate "," ((inputs++outputs).map fun n => s!".{n}(p_{n})")
  return s!"
module otpu_se_tail import otpu_pkg::*; #(
  parameter int LANES={c.lanes}, TA={c.inputLatency}, QD={c.treeDelay}
)(
  input logic clk,rst,init,
  input ss_cfg_t cfg,
  input logic [2:0] fk,
  input logic [4:0] fi,
  input logic [31:0] fd[LANES],
  input logic pe,in_v,
  input logic [31:0] in_d[LANES],
  output logic [31:0] xd[LANES],xa[LANES],
  output ss_meta_t xm,
  input logic [31:0] kv,
  input logic kv_v,
  output logic y_v,
  output logic [31:0] y_d[LANES],
  output logic o_v,
  output logic [31:0] o_d,
  output logic qp_cap,qp_row_last,
  output logic [7:0] qp_sub,
  output logic [31:0] qp_d[LANES],
  input logic qo_v,
  input logic [31:0] qo_d,
  input logic cm,cen,u_sel,
  input logic [31:0] u_a[LANES],u_b[LANES],u_c[LANES],u_e[LANES],
  output logic [31:0] u_y[LANES],
  input logic q_sel,
  input logic [31:0] q_a[LANES],q_b[LANES],q_c[LANES],
  output logic [31:0] q_y[LANES]
);
  initial if(LANES!={c.lanes} || TA!={c.inputLatency} || QD!={c.treeDelay})
    $fatal(1, \"Sparkle SE tail configuration mismatch; regenerate\");
{declarations}
  for(genvar l=0;l<LANES;l++) begin
{assignments}
  end
  otpu_se_tail_sparkle impl(.clk,.rst,.init,.cfg,.fk,.fi,.pe,.in_v,.xm,.kv,.kv_v,
    .y_v,.o_v,.o_d,.qp_cap,.qp_row_last,.qp_sub,.qo_v,.qo_d,.cm,.cen,.u_sel,.q_sel,
    {connections});
endmodule
"

end OpenTPU.SeTail
