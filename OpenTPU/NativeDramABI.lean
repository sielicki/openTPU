import OpenTPU.NativeDram
namespace OpenTPU.NativeDram
/-- Existing board ABI, with simulation counters retained at the wrapper scope.
All functional state and datapaths belong to the native circuit. -/
def wrapper (p : Config) : String :=
  let monitors := String.intercalate "\n" <| (List.range 2).map fun c =>
    s!"
  always @(posedge clk) begin
    if (!rst) begin
      if (n_rvalid[{c}] && impl.tg_n{c}==0) $fatal(1,\"native DRAM: data without tag\");
      if (n_rvalid[{c}] && impl.tg_n{c}!=0 && impl.tgh{c}[WW+:2]==0 && impl.rb_n{c}==RD)
        $fatal(1,\"native DRAM: B FIFO overflow\");
      if (n_rvalid[{c}] && impl.tg_n{c}!=0 && impl.tgh{c}[WW+:2]==1 && impl.ra_n{c}==AD)
        $fatal(1,\"native DRAM: A FIFO overflow\");
      if (n_rvalid[{c}] && impl.tg_n{c}!=0 && impl.tgh{c}[WW+:2]==2 && impl.wgot{c}[impl.tgh{c}[0+:WW]])
        $fatal(1,\"native DRAM: duplicate SW fill\");
      if (impl.rtk{c} && impl.tg_n{c}==TD && !n_rvalid[{c}]) $fatal(1,\"native DRAM: tag FIFO overflow\");
      if (impl.h_dec{c} && !impl.wnz{c}[impl.wh_f{c}]) $fatal(1,\"native DRAM: write from dead bucket\");
    end
    if (impl.rtk{c} && impl.src{c}==0) begin
      st_ard[{c}] <= st_ard[{c}]+1;
      if(impl.a_iss{c}==0) st_arun[{c}] <= st_arun[{c}]+1;
    end
    if (impl.rtk{c} && impl.src{c}==3) st_brd[{c}] <= st_brd[{c}]+1;
    if (impl.rtk{c} && impl.src{c}==1) st_srd[{c}] <= st_srd[{c}]+1;
    if (impl.wiss{c}) begin
      case(impl.src{c})
        0: begin st_awr[{c}] <= st_awr[{c}]+1; if(n_wmask[{c}]!='1) st_pa[{c}] <= st_pa[{c}]+1; end
        2: begin st_swr[{c}] <= st_swr[{c}]+1; if(n_wmask[{c}]!='1) st_ps[{c}] <= st_ps[{c}]+1; end
        default: begin st_bwr[{c}] <= st_bwr[{c}]+1; if(n_wmask[{c}]!='1) st_pb[{c}] <= st_pb[{c}]+1; end
      endcase
    end
  end"
  s!"
module otpu_native_dram #(parameter int D={p.depth}, QD={p.queueDepth}, WQD={p.writeQueueDepth},
  parameter bit CHASH={if p.channelHash then 1 else 0}, parameter int WGATHER={p.gather},
  RD={p.readDepth}, AD={p.aDepth}, APF={p.prefetch})(
  input logic clk,rst,a_flush,
  output wire a_rdy_x,
  input logic a_req_x,a_we_x,
  input logic [31:0] a_addr_x,a_wdata_x,
  input logic [3:0] a_be_x,
  output wire a_rvalid,
  output wire [31:0] a_rdata,a_rdata2,
  output wire sw_rdy,
  input logic sw_req,
  input logic [31:0] sw_addr,sw_wdata,
  input logic [3:0] sw_be,
  output wire b_rdy,
  input logic b_req,b_tag,b_we,
  input logic [D/4-1:0] b_wmask,
  input logic [D*8-1:0] b_wdata,
  input logic [31:0] b_addr,
  input logic b_par,
  output wire b_rvalid,b_rtag,
  output wire [D*8-1:0] b_rdata,
  output wire wr_idle,
  output wire [1:0] n_cvalid,
  input logic [1:0] n_cready,
  output wire [1:0] n_cwe,
  output wire [1:0][24:0] n_caddr,
  output wire [1:0] n_wvalid,
  input logic [1:0] n_wready,
  output wire [1:0][511:0] n_wdata,
  output wire [1:0][63:0] n_wmask,
  input logic [1:0] n_rvalid,
  input logic [1:0][511:0] n_rdata,
  input logic [1:0][15:0] n_wdone
);
  initial if(D!={p.depth} || QD!={p.queueDepth} || WQD!={p.writeQueueDepth} || CHASH!={if p.channelHash then 1 else 0} ||
    WGATHER!={p.gather} || RD!={p.readDepth} || AD!={p.aDepth} || APF!={p.prefetch})
    $fatal(1,\"Sparkle native DRAM configuration mismatch; regenerate\");
  otpu_native_dram_sparkle impl(.*);
`ifndef SYNTHESIS
  localparam int WW=$clog2(WQD), TD=2**$clog2(RD+AD+WQD);
  longint st_arun[2],st_ard[2],st_brd[2],st_srd[2];
  longint st_bwr[2],st_awr[2],st_swr[2],st_pb[2],st_pa[2],st_ps[2];
  initial for(int c=0;c<2;c++) begin
    st_arun[c]=0; st_ard[c]=0; st_brd[c]=0; st_srd[c]=0; st_bwr[c]=0;
    st_awr[c]=0; st_swr[c]=0; st_pb[c]=0; st_pa[c]=0; st_ps[c]=0;
  end
  always @(posedge clk) if(!rst && b_req && b_par!=^b_addr[31:5])
    $fatal(1,\"native DRAM: incorrect B address parity\");
{monitors}
`endif
endmodule
"
end OpenTPU.NativeDram
