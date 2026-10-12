import OpenTPU.MemChannel

namespace OpenTPU.MemChannel

private def portType (name : String) (width : Nat) : String :=
  if ["x_awid","x_bid","x_arid","x_rid"].contains name then "[XIDW-1:0] "
  else if name == "c_cmd_addr" then "[1:0][24:0] "
  else if ["c_wdata_data","c_rdata_data"].contains name then "[1:0][511:0] "
  else if name == "c_wdata_we" then "[1:0][63:0] "
  else if width == 1 then "" else s!"[{width-1}:0] "

/-- Original packed-port ABI with original diagnostics and bench observation aliases.
    Hardware is the closed native AST. CDC constraints must target impl and its
    native component/FIFO hierarchy; observation aliases are simulation-only. -/
def wrapper (c : Config) : String := Id.run do
  let ports := (inputPorts c).map (fun (n,w) => s!"  input logic {portType n w}{n}") ++
    (outputPorts c).map (fun (n,w) => s!"  output logic {portType n w}{n}")
  let mut s := "module otpu_mem_ch #(parameter int XIDW=4, ARD=64, XRD=16, RUN=32, OQ=32, OD=32)(\n" ++
    String.intercalate ",\n" ports ++ "\n);\n"
  s := s ++ s!"  initial if (XIDW!={c.idWidth} || ARD!={c.acceleratorDepth} || XRD!={c.xdmaDepth} || RUN!={c.runLength} || OQ!={c.commandDepth} || OD!={c.dataDepth})\n    $fatal(1, \"otpu_mem_ch: configuration differs from native elaboration\");\n"
  s := s ++ "  otpu_mem_channel_sparkle impl (" ++
    String.intercalate "," (((inputPorts c) ++ (outputPorts c)).map fun (n,_) => s!".{n}") ++ ");\n"
  s := s ++ "`ifndef SYNTHESIS\n  localparam int AOW=$clog2(ARD)+1, XOW=$clog2(XRD)+1;\n"
  for (n,w,path) in [
      ("urq",1,"urq"),("a_hold",1,"a_hold"),("x_hold",1,"x_hold"),("a_oc",1,"a_oc"),("x_oc",1,"x_oc"),
      ("x_crst",1,"x_crst"),("a_crst",1,"a_crst"),("xwi_wr",1,"xwi_wr"),("xbq_wr",1,"xbq_wr"),
      ("xai_wr",1,"xai_wr"),("xrq_wr",1,"xrq_wr"),("ar_used",MemChannelSupport.aow c,"ar_used"),
      ("xr_used",MemChannelSupport.xow c,"xr_used"),
      ("go",1,"u_controller.go"),("rm_ok",1,"u_controller.rm_ok"),("rm_busy",1,"rm_busy"),
      ("pick_x",1,"u_controller.pick_x"),("x_ok",1,"u_controller.x_ok"),("a_ok",1,"u_controller.a_ok"),
      ("oq_wr",2,"oq_wr"),("of_wr",2,"of_wr"),("tg_wr",2,"tg_wr"),("tg_rv",2,"tg_rv"),
      ("oq_wv",2,"u_controller.oq_wv"),("of_wv",2,"of_wv"),("tp",1,"u_controller.tp"),
      ("we",1,"u_controller.we"),("rmw",1,"u_controller.rmw"),("rm_ret",1,"u_controller.rm_ret"),
      ("a_rgo",1,"u_controller.a_rgo"),("x_rgo",1,"u_controller.x_rgo"),
      ("a_pend",MemChannelSupport.aow c,"u_controller.a_pend"),("x_pend",MemChannelSupport.xow c,"u_controller.x_pend")] do
    s := s ++ s!"  wire [{w-1}:0] {n} = impl.{path};\n"
  for (n,d) in [("xai",4),("xwi",4),("xrq",16),("xbq",16)] do
    let aw := Circuit.clog2 d
    s := s ++ s!"  if (1) begin : u_{n}\n    wire [{aw}:0] wp=impl.u_{n}.wp, rp=impl.u_{n}.rp;\n    wire rvalid=impl.u_{n}.rvalid, wready=impl.u_{n}.wready;\n  end\n"
  for p in ["ar","xr"] do
    s := s ++ s!"  always @(posedge uclk) if (!impl.{if p == "ar" then "a_hold" else "x_hold"} && impl.{p}_wv && impl.u_{p}.wvld[impl.{p}_slot])\n    $error(\"otpu_afifo: slot %0d written twice\", impl.{p}_slot);\n"
  s := s ++ "
  always_ff @(posedge uclk)
    if (urq && !urst && (go || rm_ok || |oq_wv || |of_wv || |c_rdata_valid))
      $fatal(1, \"otpu_mem_ch: a queue write or read data in the bridge's last reset cycle\");
  always_ff @(posedge uclk) if (!urq) begin
    if (&c_rdata_valid) $error(\"otpu_mem_ch: read data from both ports in one cycle\");
    if (go != (!rm_busy && (pick_x ? x_ok : a_ok) && oq_wr[tp] && (!we || of_wr[tp])))
      $error(\"otpu_mem_ch: go is not the chosen head's\");
    if (a_rgo != (go && !we && !pick_x) || x_rgo != (go && !we && pick_x))
      $error(\"otpu_mem_ch: a read's issue is not go's\");
    if (c_rdata_valid[1] && c_rdata_data[1] != c_rdata_data[0])
      $error(\"otpu_mem_ch: port 1's read data is not on port 0's bus\");
    for (int p=0; p<2; p++)
      if (c_rdata_valid[p] && !tg_rv[p]) $error(\"otpu_mem_ch: port %0d read data without a tag\", p);
    if (rm_ret && !rm_busy) $error(\"otpu_mem_ch: read-modify-write data without its read\");
    if (rm_ok && (!oq_wr[tp] || !of_wr[tp])) $error(\"otpu_mem_ch: no room for the merged write\");
    if (go && (!we || rmw) && !tg_wr[tp]) $error(\"otpu_mem_ch: tag FIFO full\");
    if (a_pend + ar_used > AOW'(ARD)) $error(\"otpu_mem_ch: accelerator read slots overrun\");
    if (x_pend + xr_used > XOW'(XRD)) $error(\"otpu_mem_ch: XDMA read slots overrun\");
  end
  logic a_hold_q, x_hold_q;
  always_ff @(posedge uclk) begin
    a_hold_q <= a_hold; x_hold_q <= x_hold;
    if (a_hold_q && !a_hold && a_oc) $error(\"otpu_mem_ch: accelerator hold over, command pending\");
    if (x_hold_q && !x_hold && x_oc) $error(\"otpu_mem_ch: XDMA hold over, command pending\");
  end
`endif
endmodule
"
  return s

def abiVerilog (c : Config) : Except String String := do
  return (← toVerilog c) ++ wrapper c

end OpenTPU.MemChannel
