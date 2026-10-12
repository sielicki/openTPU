import OpenTPU.MxuControlState
import OpenTPU.MxuControlDatapath
import OpenTPU.MxuDot
import OpenTPU.MxuEpilogue

/-! Complete native configurable MXU. The outer controller is independently
    exposed at the integer/FP pipeline boundary for exhaustive transition checks. -/
namespace OpenTPU.Mxu
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

/-- The full reference's column slices and lane casts require nonzero widths.
    Dot/epilogue components separately support one-column configurations. -/
def Config.validateWhole (c : Config) : Except String Unit := do
  c.validate
  if c.columns < 2 || c.lanes < 2 then
    throw "mxu: complete reference requires MCOLS >= 2 and LANES >= 2"

def inputPorts (c : Config) : List (String × Nat) :=
  [("start",1),("go",1),("cmd",240),("act_data",c.columns*c.d*8),("act_scale",c.columns*32),
   ("a_gnt",1),("a_rvalid",1),("a_rdata",32),("a_rdata2",32),("b_gnt",1),
   ("b_rvalid",1),("b_rdata",c.d*8),("t_rdata",c.lanes*32),("t_gnt",1)]

def outputPorts (c : Config) : List (String × Nat) :=
  [("rdy",1),("done",1),("computing",1),("pf_level",clog2 c.depth+1),("pf_starve",1),
   ("pf_block",1),("pf_u",1),("pf_uv",128),("act_blk",16),("act_blk2",16),
   ("act_hi",c.columns),("act_grp",8),("act_ren",1),("a_req",1),("a_addr",32),
   ("b_req",1),("b_addr",32),("t_ren",c.lanes),("t_raddr",c.lanes*32),
   ("t_wen",c.lanes),("t_waddr",c.lanes*32),("t_wdata",c.lanes*32)]

def pipelinePorts (c : Config) : List (String × Nat) :=
  [("en_c",1),("w0",c.d*8),("m0",7),("ws0",32),("ws0h",32),
   ("mb0",16),("mb0h",16),("hi0",c.columns),("c_hi",c.columns),("wf0",2),("pr0",1),("p_M",8)]

def control (c : Config) : Module := runModule "otpu_mxu_control_sparkle" do
  clocks
  for (name,w) in inputPorts c ++ [("rowr",c.columns*32),("lv2",1)] do
    let _ ← input name w
  MxuControlLogic.build c
  MxuControlDatapath.build c
  MxuControlState.build c
  -- These names already denote state or combinational wires. Expose the wire
  -- directly instead of adding a self-assignment to an output register.
  for (name,w) in outputPorts c ++ pipelinePorts c do addOutput name (.bitVector w)

private def declare (name : String) (bits : Nat) : CircuitM Unit := do
  let m ← getModule
  setModule <| m.addWire {name,ty := .bitVector bits}

def build (c : Config) : Module := runModule "otpu_mxu_sparkle" do
  clocks
  for (name,w) in inputPorts c do
    let _ ← input name w
  for (name,w) in outputPorts c do
    addOutput name (.bitVector w)
    declare name w
  for (name,w) in pipelinePorts c ++ [("rowr",c.columns*32),("lv2",1),
      ("s4",c.columns*c.sumWidth),("m4",7),("ws4",32),("ws4h",32)] do declare name w
  let controlPorts : List (String × Nat) := [("clk",1),("rst",1)] ++ inputPorts c ++ outputPorts c ++ pipelinePorts c ++
    [("rowr",c.columns*32),("lv2",1)]
  emitInstance "otpu_mxu_control_sparkle" "control"
    (controlPorts.map fun (name,_) => (name,ref name))
  emitInstance "otpu_mxu_dot_sparkle" "dot"
    ([("a0",ref "act_data")] ++ (["clk","en_c","w0","m0","ws0","ws0h","mb0","mb0h",
      "hi0","c_hi","wf0","pr0","s4","m4","ws4","ws4h"].map fun name => (name,ref name)))
  emitInstance "otpu_mxu_epilogue_sparkle" "epilogue"
    (["clk","rst","en_c","s4","m4","ws4","ws4h","hi0","pr0","act_scale","p_M","rowr","lv2"].map fun name => (name,ref name))

def controlModules (c : Config) : List Module := MxuControlDatapath.fifoModules c ++ [control c]

def modules (c : Config) : List Module :=
  [MxuEpilogue.multiply,MxuEpilogue.addition,MxuDot.build c,MxuEpilogue.build c] ++ controlModules c ++ [build c]

end OpenTPU.Mxu
