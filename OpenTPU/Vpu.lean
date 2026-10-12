import OpenTPU.VpuControl
import OpenTPU.VpuDatapath

namespace OpenTPU.Vpu
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit
abbrev Config := VpuControl.Config

def inputPorts (c : Config) : List (String × Nat) :=
  [("clk",1),("rst",1),("start",1),("cmd",240),("gnt",1),
   ("ta_data",32*c.lanes),("tb_data",32*c.lanes),("ss_req",1),("ss_cfg",23),("ss_pe",1),
   ("ss_in_v",1),("ss_in_d",32*c.lanes),("ss_fk",3),("ss_fi",5),("ss_fd",32*c.lanes)]

def outputPorts (c : Config) : List (String × Nat) :=
  [("rdy",1),("done",1),("ren",1),("ta_en",c.lanes),("ta_addr",32*c.lanes),
   ("tb_en",c.lanes),("tb_addr",32*c.lanes),("tw_en",c.lanes),("tw_addr",32*c.lanes),
   ("tw_data",32*c.lanes),("pf_u",1),("pf_frz",32),("ss_gnt",1),
   ("ss_y_v",1),("ss_y_d",32*c.lanes),("ss_o_v",1),("ss_o_d",32)]

private def signalName (name : String) := if name.startsWith "o_" then (name.drop 2).toString else name

/-- Full native VPU, with an explicit closed boundary between control/datapath.
    No inferred external ports: any missing internal signal is an elaboration error. -/
def build (c : Config) : Except String Module := do
  let controlDesign ← VpuControl.build c
  let some control := controlDesign.modules.find? (·.name == controlDesign.topModule)
    | throw "VPU control top missing"
  let datapath ← VpuDatapath.build c.toConfig
  let units := [("control",control),("datapath",datapath)]
  let inputs := inputPorts c
  let mut providers : List (String × Nat) := []
  for (_,m) in units do
    for p in m.outputs do
      let n := signalName p.name
      if providers.any (fun (name,_) => name == n) then throw s!"VPU duplicate driver: {n}"
      providers := providers ++ [(n,p.ty.bitWidth)]
  let disabled := ["s_first","s_init","s_cfg","s_fk","s_fi","s_fd","s_in_v","s_in_d",
    "vt_q","q_cap","q_rl","q_sub","q_pd"]
  for (unit,m) in units do
    for p in m.inputs do
      if let some (_,w) := providers.find? (fun (n,_) => n == p.name) then
        if w != p.ty.bitWidth then throw s!"VPU {unit}.{p.name}: driver width {w}, input {p.ty.bitWidth}"
      else if let some (_,w) := inputs.find? (fun (n,_) => n == p.name) then
        if w != p.ty.bitWidth then throw s!"VPU {unit}.{p.name}: external width {w}, input {p.ty.bitWidth}"
      else if c.toConfig.comp8 || !disabled.contains p.name then
        throw s!"VPU missing internal signal {unit}.{p.name}"
  for (n,w) in outputPorts c do
    if !["ren","tw_addr"].contains n && !(n == "ss_y_d" && !c.toConfig.comp8) then
      let some (_,pw) := providers.find? (fun (name,_) => name == n) | throw s!"VPU missing output {n}"
      if pw != w then throw s!"VPU output width mismatch {n}: {pw}, expected {w}"
  return runModule "otpu_vpu_sparkle" do
    for (n,w) in inputs do let _ ← input n w
    for (n,w) in providers do
      let m ← getModule
      setModule (m.addWire {name := s!"vpu_{n}",ty := .bitVector w})
    for (unit,m) in units do
      let inp := m.inputs.map fun p => (p.name,
        if providers.any (fun (n,_) => n == p.name) then ref s!"vpu_{p.name}"
        else if inputs.any (fun (n,_) => n == p.name) then ref p.name
        else lit 0 p.ty.bitWidth)
      let out := m.outputs.map fun p => (p.name,ref s!"vpu_{signalName p.name}")
      emitInstance m.name s!"u_{unit}" (inp ++ out)
    for (n,w) in outputPorts c do
      let value := if n == "ren" then ref "vpu_en"
        else if n == "tw_addr" then pack ((List.range c.lanes).map fun l =>
          Expr.concat [lit 0 12,slice (ref "vpu_tw_a") (20*l) 20])
        else if n == "ss_y_d" && !c.toConfig.comp8 then lit 0 w
        else ref s!"vpu_{n}"
      output n w value

def toVerilog (c : Config) : Except String String := do
  let top ← build c
  return (← VpuControl.toVerilog c) ++ (← VpuDatapath.toVerilog c.toConfig) ++
    Sparkle.Backend.Verilog.toVerilog top

end OpenTPU.Vpu
