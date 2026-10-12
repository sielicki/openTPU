import OpenTPU.VpuCommand
import OpenTPU.VpuSequence
import OpenTPU.VpuWriteBuffer
import OpenTPU.VpuWriteSelect
import OpenTPU.VpuStream
import OpenTPU.Backend

namespace OpenTPU.VpuControl
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

structure Config extends VpuIssue.Config where
  buffered : Bool := true
  deriving Repr

/-- Output aliases describe the real inter-component control nets. The command
    setup's minimum fill count is distinct from the sequencer's retained nfill. -/
def signalName (unit port : String) : String :=
  if unit == "command" && port == "nfill" then "head_nfill"
  else if port.startsWith "o_" then (port.drop 2).toString else port

private def noStream : Module := runModule "otpu_vpu_no_stream_sparkle" do
  for n in ["o_ss_rq","o_ss_act","ss_act_d","o_sen","ss_gnt","ss_y_v","ss_o_v"] do
    output n 1 (lit 0 1)

def components (c : Config) : Except String (List (String × Module)) := do
  let base := c.toConfig
  return [("command",← VpuCommand.build base),("issue",← VpuIssue.build base),
    ("sequence",← VpuSequence.build base),
    ("write_select",← VpuWriteSelect.build c.lanes),
    ("write_buffer",← VpuWriteBuffer.build ⟨c.lanes,c.buffered,c.streams⟩),
    ("stream",if base.comp8 then VpuStream.build else noStream)]

/-- Assemble the verified control components. Unprovided inputs are explicit
    datapath/external boundary ports; every internal use is width checked. -/
def build (c : Config) : Except String Design := do
  let units ← components c
  let mut providers : List (String × Nat) := []
  for (unit,m) in units do
    for p in m.outputs do
      let name := signalName unit p.name
      if providers.any (fun (n,_) => n == name) then throw s!"VPU control: duplicate driver {name}"
      providers := providers ++ [(name,p.ty.bitWidth)]
  let mut inputs : List (String × Nat) := []
  for (unit,m) in units do
    for p in m.inputs do
      let width := p.ty.bitWidth
      if let some (_,w) := providers.find? (fun (n,_) => n == p.name) then
        if w != width then throw s!"VPU control: {unit}.{p.name} needs {width} bits, driver has {w}"
      else if let some (_,w) := inputs.find? (fun (n,_) => n == p.name) then
        if w != width then throw s!"VPU control: conflicting boundary width for {p.name}"
      else inputs := inputs ++ [(p.name,width)]
  let top := runModule "otpu_vpu_control_sparkle" do
    for (n,w) in inputs do
      let _ ← input n w
    for (n,w) in providers do
      let m ← getModule
      setModule (m.addWire {name := s!"control_{n}",ty := .bitVector w})
    for (unit,m) in units do
      let inPorts := m.inputs.map fun p => (p.name,
        ref (if providers.any (fun (n,_) => n == p.name) then s!"control_{p.name}" else p.name))
      let outPorts := m.outputs.map fun p => (p.name,ref s!"control_{signalName unit p.name}")
      emitInstance m.name s!"u_{unit}" (inPorts ++ outPorts)
    for (n,w) in providers do output n w (ref s!"control_{n}")
  return {topModule := top.name,modules := units.map Prod.snd ++ [top]}

/-- Production emission preserves the original high-fanout register hints. -/
def toVerilog (c : Config) : Except String String := do
  let design ← build c
  let mut result := ""
  for m in design.modules do
    let hints : Backend.RegisterHints :=
      if m.name == "otpu_vpu_write_buffer_sparkle" && c.buffered then
        [("en_r",[.maxFanout 64])] ++ if c.toConfig.comp8 then [("en_q",[.maxFanout 32])] else []
      else if m.name == "otpu_vpu_stream_sparkle" then
        [("ss_act",[.maxFanout 64]),("sen",[.maxFanout 64]),("sen_q",[.maxFanout 32])]
      else []
    result := result ++ (← Backend.withRegisterHints m hints)
  return result

end OpenTPU.VpuControl
