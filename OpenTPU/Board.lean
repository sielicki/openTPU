import OpenTPU.BoardPorts
import OpenTPU.BoardSignals

/-! Native single-slice board assembly. The slice remains an explicit external
    component. No behavioral implementation or assumption is hidden in its pin
    contract; BoardABI supplies only the original slice's structural adapter. -/
namespace OpenTPU.Board
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

private def declared (name : String) (w : Nat) : CircuitM Unit := do
  let m ← getModule
  if let some p := m.wires.find? (·.name == name) then
    let old := match p.ty with | .bit => 1 | .bitVector n => n | _ => 0
    if old != w then panic! s!"board: conflicting widths on {name}: {old} and {w}"
  else setModule <| m.addWire {name,ty:=.bitVector w}

private def signal (name : String) (w : Nat) (e : Expr) : CircuitM Unit := do
  declared name w
  emitAssign name e

/-- Native components surrounding the explicitly external slice. -/
def components (c : Config) : Except String (List Module) := do
  c.validate
  let trace ← if c.traceDepth == 0 then pure [] else do pure [← Trace.build c.trace]
  return [BoardSignals.build,Control.build c.control,Collective.build c.collective,
          NativeDram.build c.memory] ++ trace

private def named (m : Module) (instanceName : String) (rename : String → String) : CircuitM Unit := do
  let ps := (m.inputs ++ m.outputs).map fun p => (p.name,rename p.name,p.ty)
  for (_,name,ty) in ps do
    let w := match ty with | .bit => 1 | .bitVector n => n | _ => 0
    declared name w
  emitInstance m.name instanceName (ps.map fun (p,n,_) => (p,ref n))

def build (c : Config) : Except String Module := do
  let units ← components c
  return runModule "otpu_board_sparkle" do
    for (name,w) in inputs do let _ ← input name w
    for (name,w) in outputs do
      addOutput name (.bitVector w)
      declared name w
    -- Board-local combinational glue. All registered board behavior belongs to
    -- the independently qualified BoardSignals component.
    for (name,w) in [("run",1),("halted",1),("error",1),("a_req",1),("a_rdy",1),
        ("a_we",1),("b_req",1),("b_rdy",1),("b_we",1),("sw_req",1),("sw_rdy",1),
        ("core_rst",1),("ld_start",1),("a_inval",1),("tr_en",1),
        ("pf",Trace.width Trace.perfFields)] do declared name w
    signal "axi_err" 1 (bor (bit (ref "n_err") 0) (bit (ref "n_err") 1))
    for (name,value) in [
      ("b_rd",band (band (ref "b_req") (ref "b_rdy")) (bnot (ref "b_we"))),
      ("b_wr",band (band (ref "b_req") (ref "b_rdy")) (ref "b_we")),
      ("a_rd",band (band (ref "a_req") (ref "a_rdy")) (bnot (ref "a_we"))),
      ("a_wr",band (ref "sw_req") (ref "sw_rdy")),
      ("b_wait",band (ref "b_req") (bnot (ref "b_rdy"))),
      ("dram_wait",bor (band (ref "b_req") (bnot (ref "b_rdy")))
        (bor (band (ref "a_req") (bnot (ref "a_rdy"))) (band (ref "sw_req") (bnot (ref "sw_rdy"))))),
      ("trace_enable",band (ref "tr_en") (ref "run")),
      ("a_flush",bor (ref "core_rst") (bor (ref "ld_start") (ref "a_inval")))] do signal name 1 value
    let extend := fun x => pack [x,lit 0 1]
    signal "dram_rd" 2 (add (extend (bit (ref "n_rvalid") 0)) (extend (bit (ref "n_rvalid") 1)))
    signal "dram_wr" 2 (add
      (extend (band (bit (ref "n_wvalid") 0) (bit (ref "n_wready") 0)))
      (extend (band (bit (ref "n_wvalid") 1) (bit (ref "n_wready") 1))))
    let pf := Trace.field Trace.perfFields (ref "pf")
    for (name,index) in [("dma_busy",0),("mxu_busy",1),("qnt_busy",2),("vpu_busy",3)] do
      signal name 1 (bit (pf "busy") index)
    for (name,field,w) in [("mxu_mac","mac",1),("mxu_starve","starve",1),("tmem_deny","deny",1),("instr","ret",2)] do
      signal name w (pf field)
    for m in units do
      if m.name == "otpu_board_signals_sparkle" then
        named m "u_signals" fun n => if n.startsWith "o_" then (n.drop 2).toString else n
      else if m.name == "otpu_ctrl_sparkle" then
        named m "u_ctrl" fun n =>
          if n.startsWith "s_" then "s_ctl_" ++ (n.drop 2).toString
          else if n == "arg" then "arg_data"
          else if n == "calib" then "cal_s2"
          else if n == "temp" then "temp_q"
          else if n == "i2c_in" then "i2c_s2" else n
      else if m.name == "otpu_coll_sparkle" then
        named m "u_coll" fun n => match n with
          | "rst" => "coll_rst" | "req" => "coll_req" | "cmds" => "coll_cmd"
          | "gnt" => "coll_gl" | "ack" => "coll_ack"
          | "r_en" => "coll_ren" | "r_addr" => "coll_raddr" | "r_data" => "coll_rdata"
          | "w_en" => "coll_wen" | "w_addr" => "coll_waddr" | "w_data" => "coll_wdata"
          | n => n
      else if m.name == "otpu_native_dram_sparkle" then
        named m "u_mem" fun n => if n.endsWith "_x" then (n.dropEnd 2).toString else n
      else if m.name == "otpu_trace_sparkle" then
        named m "u_trace" fun n => match n with
          | "en" => "trace_enable" | "stop" => "tr_stop" | "clear" => "tr_clear"
          | "raddr" => "tr_addr" | "rdata" => "tr_rdata" | "count" => "tr_count"
          | "drop" => "tr_drop" | "busy" => "tr_busy" | n => n
    if c.traceDepth == 0 then
      for (name,w) in [("tr_rdata",64),("tr_count",32),("tr_drop",32),("tr_busy",1)] do
        signal name w (lit 0 w)
    let boundary := sliceContract c
    for p in boundary.inputs ++ boundary.outputs do
      let n := match p.name with
        | "sys_rst" => "rst" | "rst" => "core_rst" | "rinit" => "arg_data"
        | "coll_gnt_local" | "coll_gnt" => "coll_gl" | n => n
      if n != "dump" then
        declared n (match p.ty with | .bitVector w => w | _ => 1)
    emitInstance boundary.name "u_slice" ((boundary.inputs ++ boundary.outputs).map fun p =>
      (p.name, match p.name with
        | "dump" => lit 0 1 | "sys_rst" => ref "rst" | "rst" => ref "core_rst"
        | "rinit" => ref "arg_data" | "coll_gnt_local" | "coll_gnt" => ref "coll_gl"
        | n => ref n))

/-- Emit native hardware only. The external slice adapter is separate and must
    be supplied explicitly by the integrator. -/
def emit (c : Config) : Except String String := do
  let units ← components c
  let mut result := ""
  for m in units do
    let text ← if m.name == "otpu_board_signals_sparkle" then BoardSignals.toVerilog
      else if m.name == "otpu_trace_sparkle" then Trace.toVerilog c.trace
      else pure (Sparkle.Backend.Verilog.toVerilog m)
    result := result ++ text
  return result ++ Sparkle.Backend.Verilog.toVerilog (← build c)

end OpenTPU.Board
