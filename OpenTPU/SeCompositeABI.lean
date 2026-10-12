import OpenTPU.SeComposite

namespace OpenTPU.SeComposite

/-- ABI packing; functional hardware and simulation checks are in the native core. -/
def wrapper (c : Config) : String := s!"
module otpu_se_comp #(
  parameter int LANES={c.lanes}, MW={c.metadata}, NS={c.stages}, HA={c.lookAhead},
  parameter bit EXT={if c.external then 1 else 0}
)(
  input logic clk,rst,en,in_v,
  input logic [2:0] in_c,
  input logic [31:0] in_a[LANES],in_b[LANES],
  input logic [LANES-1:0] in_m,
  input logic [MW-1:0] in_meta,
  output logic hold,
  output logic [NS-1:0] st_sel,
  output logic [31:0] st_a[NS][LANES],st_b[NS][LANES],st_c[NS][LANES],st_e[NS][LANES],
  input logic [31:0] st_y[NS][LANES],
  output logic out_v,
  output logic [31:0] out_d[LANES],
  output logic [LANES-1:0] out_m,
  output logic [MW-1:0] out_meta
);
  initial if(LANES!={c.lanes} || MW!={c.metadata} || NS!={c.stages} || HA!={c.lookAhead} || EXT!={if c.external then 1 else 0})
    $fatal(1, \"Sparkle SE composite configuration mismatch; regenerate\");
  wire [LANES*32-1:0] pa,pb,pd;
  wire [NS*LANES*32-1:0] sa,sb,sc,se,sy;
  for(genvar l=0;l<LANES;l++) begin
    assign pa[32*l+:32]=in_a[l];
    assign pb[32*l+:32]=in_b[l];
    assign out_d[l]=pd[32*l+:32];
    for(genvar s=0;s<NS;s++) begin
      assign st_a[s][l]=sa[32*(s*LANES+l)+:32];
      assign st_b[s][l]=sb[32*(s*LANES+l)+:32];
      assign st_c[s][l]=sc[32*(s*LANES+l)+:32];
      assign st_e[s][l]=se[32*(s*LANES+l)+:32];
      assign sy[32*(s*LANES+l)+:32]=st_y[s][l];
    end
  end
  otpu_se_comp_sparkle impl(.clk,.rst,.en,.in_v,.in_c,.in_a(pa),.in_b(pb),.in_m,.in_meta,
    .hold,.st_sel,.st_a(sa),.st_b(sb),.st_c(sc),.st_e(se),.st_y(sy),.out_v,.out_d(pd),.out_m,.out_meta);
endmodule
"

end OpenTPU.SeComposite
