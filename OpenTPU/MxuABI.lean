import OpenTPU.Mxu

/-! Original typed MXU interface. The hardware is entirely native; simulation
    assertions below retain the reference checks using explicit hierarchy aliases.
    These aliases and assertions are excluded from synthesis.
    This adapter is for the qualified behavioral dot path. -/
namespace OpenTPU.Mxu
open Sparkle.Backend.Verilog

private def diagnosticAliases (c : Config) : String := Id.run do
  let m := control c
  let names : List String := ["c_G","c_M","c_Mn","c_fin","c_left","c_rch","c_run","c_unit","ck","ckc","cl_ld","cmd_pair","cmd_total","cmd_tz","d_fin","d_last","dg","dg1","dj","dln","drain_go","f_head","f_rd","f_tail","i_pair","last_g","more","mx_go","mx_i","mxm","ncnt","pn","pop","q_n","rf_hs","rf_n","rf_nz","rf_q","rfh","rl_nz","rows_live","s_head","s_rd","scale_addr","c_w4"]
  let mut result := ""
  for name in names do
    if let some p := (m.wires ++ m.outputs).find? (·.name == name) then
      result := result ++ s!"  wire {emitType p.ty} {name} = impl.control.{name};\n"
    else panic! s!"missing MXU diagnostic signal {name}"
  let fields := String.intercalate "\n" ((MxuControlFields.queueFields c).reverse.map fun (name,w) =>
    s!"    logic [{w-1}:0] {name};")
  result := result ++ "  typedef struct packed {\n" ++ fields ++ "\n  } check_qent_t;\n"
  for name in ["h","n","pop_q"] do
    result := result ++ s!"  wire check_qent_t {name} = impl.control.{name};\n"
  result := result ++ "  wire [31:0] dad[MCOLS];\n  wire [NL-1:0][31:0] dal;\n  wire [LANES-1:0][31:0] mxl;\n  wire [PW-1:0] f_tl[FG],f_rdl[FG];\n  wire [NL-1:0][MCOLS-1:0] rxh=impl.control.rxh,rwh=impl.control.rwh;\n"
  for j in [:c.columns] do result := result ++ s!"  assign dad[{j}]=impl.control.dad{j};\n"
  for k in [:MxuControlFields.nl c] do result := result ++ s!"  assign dal[{k}]=impl.control.dal{k};\n"
  for k in [:c.lanes] do result := result ++ s!"  assign mxl[{k}]=impl.control.mxl{k};\n"
  for g in [:MxuControlFields.fg c] do
    result := result ++ s!"  assign f_tl[{g}]=impl.control.f_tl{g};\n  assign f_rdl[{g}]=impl.control.f_rdl{g};\n"
  return result

private def diagnostics (c : Config) (dspModel : Bool) : String := Id.run do
  let mut result := s!"
`ifndef SYNTHESIS
  localparam int PW=$clog2(DEPTH),SPW=PW+1,MW=$clog2(MCOLS)+1,
    BW=$clog2(LANES),NL={MxuControlFields.nl c},FG={MxuControlFields.fg c},
    RFW={MxuControlFields.rfw c};
  localparam bit OVL=(IMPL==2);
  localparam logic [1:0] WF_W8=0;
  function automatic logic [NL-1:0] dlanes(input logic [MW-1:0] cnt);
    for(int k=0;k<NL;k++) dlanes[k]=32'(k)<32'(cnt);
  endfunction
  function automatic logic [NL-1:0][31:0] dlane_a(input logic [31:0] a[MCOLS],input logic [MW-1:0] j);
    for(int k=0;k<NL;k++) dlane_a[k]=(32'(j)+32'(k)<MCOLS)?a[MW'(j)+MW'(k)]:'0;
  endfunction
" ++ diagnosticAliases c
  let memories := (control c).body.filterMap fun s => match s with
    | .memory name _ _ _ _ _ _ _ _ _ _ _ => if name.startsWith "_tmp_result_fifo0_" then some name else none
    | _ => none
  let checks := "  // a replayed row (M > MCOLS) must fit the FIFO: its chunks (4-bit: two blocks each)
  always @(posedge clk) if (!rst && start) begin
    if (int'(cmd.w6[23:16]) > ROWS) $fatal(1, \"otpu_mxu: M %0d > ROWS %0d\", cmd.w6[23:16], ROWS);
    if (int'(cmd.w6[23:16]) > MCOLS && ((cmd.flags[5:4] != WF_W8) ?
        (int'(cmd.w4[31:16]) + 1) / 2 : int'(cmd.w4[31:16])) > DEPTH)
      $fatal(1, \"otpu_mxu: a replayed row (M > MCOLS) must fit the FIFO: KB %0d, DEPTH %0d\",
             cmd.w4[31:16], DEPTH);
    if (int'(cmd.w6[23:16]) > MCOLS && cmd.flags[6])
      $fatal(1, \"otpu_mxu: PAIR needs 2*M <= MCOLS\");
  end
  always @(posedge clk)
    if (!rst && start && cmd_tz != (cmd_total == 0))
      $fatal(1, \"otpu_mxu: cmd_tz %0d but total %0d\", cmd_tz, cmd_total);
  always @(posedge clk) if (!rst && IMPL == 2) begin
    if (more && ck != 0 && !pop) $fatal(1, \"otpu_mxu: IMPL 2 row stalled at advance %0d\", ck);
    if (more && 32'(c_rch) > DEPTH) $fatal(1, \"otpu_mxu: IMPL 2 needs a row (%0d chunks) to fit the FIFO\", c_rch);
  end
  always @(posedge clk) if (!rst && more) begin
    if (f_rd != (last_g ? f_head : f_head + PW'(ckc)))
      $fatal(1, \"otpu_mxu: FIFO read address %0d, head %0d, k %0d\", f_rd, f_head, ck);
    if (!c_unit && s_rd != (last_g ? s_head : s_head + SPW'(ck)))
      $fatal(1, \"otpu_mxu: scale read address %0d, head %0d, k %0d\", s_rd, s_head, ck);
  end
  // the groups' address copies are f_tail and f_rd (all reset together)
  bit fd_rst;                                         // (registers start arbitrary)
  initial fd_rst = 1'b0;
  always @(posedge clk) begin
    if (rst) fd_rst <= 1'b1;
    for (int g = 0; g < FG; g++)
      if (!rst && fd_rst && (f_tl[g] != f_tail || f_rdl[g] != f_rd))
        $fatal(1, \"otpu_mxu: FIFO group %0d addresses %0d / %0d, not %0d / %0d\", g, f_tl[g],
               f_rdl[g], f_tail, f_rd);
  end
  always @(posedge clk) if (!rst && drain_go && dg1 != dg + 8'd1) $fatal(1, \"otpu_mxu: dg1 %0d, dg %0d\", dg1, dg);
  // the registered step is its definition from the head's entry, dg1, dj and the counts
  always @(posedge clk) if (!rst && q_n != 0) begin
    logic [MW-1:0] mn, lf;
    mn = (dg1 == c_G) ? h.Ml : MW'(MCOLS);
    lf = mn - dj;
    if (d_last != (dg1 == c_G) || ncnt != ((c_run < lf) ? c_run : lf) || dln != dlanes(ncnt) ||
        d_fin != (MW'(dj + ncnt) == mn))
      $fatal(1, \"otpu_mxu: drain step d_last %0d ncnt %0d d_fin %0d (dg1 %0d G %0d dj %0d M %0d run %0d)\",
             d_last, ncnt, d_fin, dg1, c_G, dj, mn, c_run);
  end
  always @(posedge clk) if (!rst && q_n != 0 && dal != dlane_a(dad, dj))
    $fatal(1, \"otpu_mxu: the drain lanes' addresses are not dad[dj + k] (dj %0d)\", dj);
  always @(posedge clk) if (!rst && (rf_nz != (rf_n != 0) || rl_nz != (rows_live != 0)))
    $fatal(1, \"otpu_mxu: rf_nz %0d (rf_n %0d), rl_nz %0d (rows_live %0d)\", rf_nz, rf_n, rl_nz, rows_live);
  // PAIR reads a block's scale word and its partner's as one 8-byte aligned pair
  always @(posedge clk) begin
    if (a_req && i_pair && scale_addr[2]) $fatal(1, \"otpu_mxu: PAIR scales must be 8-byte aligned\");
    if (start && cmd_pair && 2 * int'(cmd.w6[23:16]) > MCOLS)
      $fatal(1, \"otpu_mxu: PAIR needs 2 * M <= MCOLS\");
  end
  // the lane count is what a greedy pick that stops at the first bank conflict would take
  always @(posedge clk) if (drain_go) begin
    logic [LANES-1:0] used;
    int n;
    used = '0; n = 0;
    for (int k = 0; k < NL && 32'(dj) + 32'(k) < 32'(c_Mn); k++) begin
      if (used[dad[MW'(dj) + MW'(k)][BW-1:0]]) break;
      used[dad[MW'(dj) + MW'(k)][BW-1:0]] = 1'b1;
      n++;
    end
    if (n != 32'(ncnt)) $fatal(1, \"otpu_mxu: drain lanes %0d, greedy pick %0d\", ncnt, n);
  end
  always @(posedge clk) if (!rst && rf_n != 0 && rfh != @RESULT_MEMORY@[RFW'(rf_q + RFW'(rf_hs))])
    $fatal(1, \"otpu_mxu: registered head row is not row %0d\", rf_q + RFW'(rf_hs));
  always @(posedge clk) if (!rst && q_n != 0)
    for (int k = 0; k < LANES; k++)
      if (mxm[k] != (32'(mx_i) + 32'(k) < 32'(c_M)))
        $fatal(1, \"otpu_mxu: RMAX lane %0d: mxm %0d, mx_i %0d, M %0d\", k, mxm[k], mx_i, c_M);
  always @(posedge clk) if (!rst && mx_go)
    for (int k = 0; k < LANES; k++)
      if (mxl[k] != h.mxo + 32'(mx_i) + 32'(k))
        $fatal(1, \"otpu_mxu: RMAX lane %0d address %0h, mxo %0h, mx_i %0d\", k, mxl[k], h.mxo, mx_i);
  always_ff @(posedge clk)
    if (!rst && t_gnt)
      for (int j = 0; j < MCOLS; j++) begin
        int n;
        n = 0;
        for (int k = 0; k < NL; k++) n = n + int'(rxh[k][j]) + int'(rwh[k][j]);
        if (n > 1) $fatal(1, \"otpu_mxu: several RMAX updates of column %0d in one cycle\", j);
      end
  // the head / next mapping relies on the rdy contract (start only with a free entry), and a
  // command never completes while it pops (c_fin needs c_left == 0, pop c_left != 0)
  always @(posedge clk) if (!rst) begin
    if (start && q_n >= 2'd2) $fatal(1, \"otpu_mxu: start with %0d commands queued\", q_n);
    if (!OVL && c_fin && pop) $fatal(1, \"otpu_mxu: the head completes while it pops\");
    if (OVL && q_n != 0 && !cl_ld && pop_q != (pn ? n : h))
      $fatal(1, \"otpu_mxu: pop_q is not the pop head's entry\");
  end"
  result := result ++ checks.replace "@RESULT_MEMORY@" ("impl.control." ++ memories.head!)
  if c.implementation == 1 then
    -- The original check has no reset guard. Preserve it exactly here.
    result := result ++ "\n  always @(posedge clk) if(pop && c_w4) $fatal(1, \"otpu_mxu: 4-bit weights need IMPL = 0\");\n"
  if c.implementation == 2 then
    result := result ++ "\n  bit hi_v=0;\n  always @(posedge clk) if(impl.en_c) hi_v<=1;\n"
    for j in [:c.columns] do
      for i in [:c.d] do
        let sel := if dspModel then s!"impl.dot.physical_pe{j}_{i}.u_dsp.INMODEr[2]" else s!"impl.dot.pe{j}_{i}_selr"
        result := result ++ s!"  always @(posedge clk) if(hi_v && {sel} != impl.hi0[{j}]) $fatal(1, \"otpu_mxu: PE {j}.{i}'s select is not hi0\");\n"
        if j != 0 then
          let wh := if dspModel then s!"impl.dot.physical_pe{j}_{i}.u_dsp.Dr[7:0]" else s!"impl.dot.pe{j}_{i}_whr"
          let wl := if dspModel then s!"impl.dot.physical_pe{j}_{i}.u_dsp.Ar2[7:0]" else s!"impl.dot.pe{j}_{i}_wlr"
          result := result ++ s!"  always @(posedge clk) if(hi_v && ({wh} != impl.dot.wc{j}_{i}[15:8] || {wl} != impl.dot.wc{j}_{i}[7:0])) $fatal(1, \"otpu_mxu: PE {j}.{i}'s weights are not wc\");\n"
  return result ++ "`endif\n"

/-- Preserve original ports and parameters; reject overrides incompatible with
    the elaborated native circuit. SID is retained for ABI compatibility. -/
private def wrapperWithDiagnostics (c : Config) (dspModel : Bool) : String := Id.run do
  let header := "module otpu_mxu
  import otpu_pkg::*;
  import otpu_fp::*;
#(
  parameter int D     = @D@,
  parameter int MCOLS = @C@,
  parameter int ROWS  = @R@,   // ACT RAM rows: the most stationary rows of a command
  parameter int DEPTH = @DEPTH@,
  parameter int LANES = @L@,       // TMEM banks (MCOLS > LANES drains a row in several cycles)
  parameter int IMPL  = @IMPL@,       // integer dot product: 0 adder tree, 1 DSP cascade chains,
                                 // 2 systolic array (docs/mxu_systolic.md)
  parameter int CL    = @CL@,      // IMPL 1, 2: products per cascade chain (D / CL chains)
  parameter int SID   = 0
) (
  input  logic                  clk,
  input  logic                  rst,
  input  logic                  start,       // accept: the issuer may stream it
  input  logic                  go,          // release: the consumer may use it (in order)
  input  cmd_t                  cmd,
  output logic                  rdy,
  output logic                  done,
  output logic                  computing,   // a chunk is consumed this cycle (profiling)
  // profiling: this cycle's stream state (the FIFO level; work but no chunk / chunks but no
  // consumption) and, a cycle after a command ends, its counters {deny, frz, bp, starve}
  output logic [$clog2(DEPTH):0] pf_level,
  output logic                  pf_starve,
  output logic                  pf_block,
  output logic                  pf_u,
  output logic [3:0][31:0]      pf_uv,
  // ACT RAM read
  output logic [15:0]           act_blk,
  output logic [15:0]           act_blk2,    // PAIR: the odd block, read by the rows in act_hi
  output logic [MCOLS-1:0]      act_hi,
  output logic [7:0]            act_grp,
  output logic                  act_ren,     // the ACT RAM read register advances (with S0)
  input  logic [MCOLS*D*8-1:0]  act_data,
  input  logic [MCOLS*32-1:0]   act_scale,
  // DRAM port A (scales) and B (chunks)
  output logic                  a_req,
  output logic [31:0]           a_addr,
  input  logic                  a_gnt,
  input  logic                  a_rvalid,
  input  logic [31:0]           a_rdata,
  input  logic [31:0]           a_rdata2,    // the other word of a_rdata's 8-byte pair
  output logic                  b_req,
  output logic [31:0]           b_addr,
  input  logic                  b_gnt,
  input  logic                  b_rvalid,
  input  logic [D*8-1:0]        b_rdata,
  // TMEM (read port for ACC, write port)
  output logic [LANES-1:0]        t_ren,
  output logic [LANES-1:0][31:0]  t_raddr,
  input  logic [LANES-1:0][31:0]  t_rdata,
  output logic [LANES-1:0]        t_wen,
  output logic [LANES-1:0][31:0]  t_waddr,
  output logic [LANES-1:0][31:0]  t_wdata,
  input  logic                    t_gnt
);"
  let header := header.replace "@D@" (toString c.d) |>.replace "@C@" (toString c.columns)
    |>.replace "@R@" (toString c.rows) |>.replace "@DEPTH@" (toString c.depth)
    |>.replace "@L@" (toString c.lanes) |>.replace "@IMPL@" (toString c.implementation)
    |>.replace "@CL@" (toString c.chainLength)
  let ports := ["clk","rst"] ++ (inputPorts c ++ outputPorts c).map Prod.fst
  return header ++ s!"
  initial if(D!={c.d} || MCOLS!={c.columns} || ROWS!={c.rows} || DEPTH!={c.depth} ||
    LANES!={c.lanes} || IMPL!={c.implementation} || CL!={c.chainLength})
    $fatal(1, \"Sparkle MXU configuration mismatch; regenerate\");
  initial if(D%16!=0) $fatal(1, \"otpu_mxu: D must be a multiple of 16\");
  initial if(ROWS<MCOLS || ROWS>255) $fatal(1, \"otpu_mxu: MCOLS <= ROWS < 256\");
  initial if(IMPL==1 && (D%CL!=0 || D/CL>64)) $fatal(1, \"otpu_mxu: CL must divide D, D/CL <= 64\");
  initial if(IMPL==2 && (D/4)%((D/4<CL)?D/4:CL)!=0) $fatal(1, \"otpu_mxu: IMPL 2 needs CL to divide D/4\");
  initial if(IMPL==2 && 16+$clog2(D)>25) $fatal(1, \"otpu_colend: sum width exceeds 25\");
  otpu_mxu_sparkle impl(" ++ String.intercalate "," (ports.map ("." ++ ·)) ++ ");\n" ++ diagnostics c dspModel ++ "endmodule\n"

/-- Original ABI with the qualified behavioral dot's simulation diagnostics. -/
def wrapper (c : Config) : String := wrapperWithDiagnostics c false

/-- Original ABI for the native physical dot simulated with the authenticated
    Yosys DSP48E1 model. Check the model's actual select and weight registers;
    these hierarchy names are model-specific. All such checks are excluded
    from synthesis, and the default behavioral wrapper remains unchanged. -/
def wrapperDSPModel (c : Config) : String := wrapperWithDiagnostics c true

end OpenTPU.Mxu
