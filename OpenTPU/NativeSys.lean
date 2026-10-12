import OpenTPU.NativeSysConfig
import OpenTPU.BoardPorts

namespace OpenTPU.NativeSys
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

/-- The child ABIs are purely structural wrappers around native hardware. Keeping
    them in the hierarchy retains their simulation monitors. Supply native ABI
    definitions explicitly; this module never reads or imports reference RTL. -/
def contracts (c : Config) : Except String (List Module) := do
  c.board.validate
  let split ← DmaSplit.build c.split
  let some st := split.modules.find? (·.name == split.topModule) | throw "NativeSys: DMA split top missing"
  let mk := fun (name : String) (ins outs : List (String × Nat)) =>
    ({ name := name
       inputs := ins.map (fun (n,w) => ({name := n, ty := .bitVector w} : Port))
       outputs := outs.map (fun (n,w) => ({name := n, ty := .bitVector w} : Port))
       wires := [], body := [], isPrimitive := true } : Module)
  return [mk "otpu_board" Board.inputs Board.outputs,
    {st with name:="otpu_dma_split",body:=[],wires:=[],isPrimitive:=true},
    mk "otpu_mem_ch" (MemChannel.inputPorts c.channel) (MemChannel.outputPorts c.channel)]

def ports (c : Config) : Except String (List (String × Nat) × List (String × Nat)) := do
  let cs ← contracts c
  let some split := cs[1]? | throw "NativeSys: split contract missing"
  let dma := fun (ps : List Port) => ps.filterMap fun p =>
    if p.name.startsWith "s_" then some ("x_" ++ (p.name.drop 2).toString,p.ty.bitWidth) else none
  let channel := fun ps => ps.filterMap fun (n,w) =>
    if n.startsWith "c_" || n == "uclk" || n == "urst" then some (n,2*w) else none
  return ((Board.inputs.filter fun (n,_) => !n.startsWith "n_") ++ [("xclk",1),("xrst",1)] ++
      dma split.inputs ++ channel (MemChannel.inputPorts c.channel),
    (Board.outputs.filter fun (n,_) => !n.startsWith "n_") ++
      dma split.outputs ++ channel (MemChannel.outputPorts c.channel))

private def declared (name : String) (w : Nat) : CircuitM Unit := do
  let m ← getModule
  if !(m.inputs.any (·.name == name)) && !(m.wires.any (·.name == name)) then
    setModule (m.addWire {name,ty:=.bitVector w})

/-- Zero-state two-channel system assembly. Channel zero occupies the least
    significant packed element for every AXI and controller bus. -/
def build (c : Config) : Except String Module := do
  let cs ← contracts c
  let some board := cs[0]? | throw "NativeSys: Board contract missing"
  let some split := cs[1]? | throw "NativeSys: split contract missing"
  let some channel := cs[2]? | throw "NativeSys: channel contract missing"
  let (ins,outs) ← ports c
  return runModule "otpu_native_sys_sparkle" do
    for (n,w) in ins do let _ ← input n w
    for (n,w) in outs do
      addOutput n (.bitVector w)
      declared n w
    for p in board.inputs ++ board.outputs do declared p.name p.ty.bitWidth
    for p in split.inputs ++ split.outputs do
      if p.name.startsWith "m_" then declared p.name p.ty.bitWidth
    emitInstance board.name "u_board" ((board.inputs ++ board.outputs).map fun p => (p.name,ref p.name))
    emitInstance split.name "u_split" ((split.inputs ++ split.outputs).map fun p =>
      (p.name,ref (if p.name == "clk" then "xclk" else if p.name == "rst" then "xrst"
        else if p.name.startsWith "s_" then "x_" ++ (p.name.drop 2).toString else p.name)))
    for ch in [:2] do
      emitInstance channel.name s!"u_ch{ch}" ((channel.inputs ++ channel.outputs).map fun p =>
        let name := if p.name.startsWith "x_" then "m_" ++ (p.name.drop 2).toString else p.name
        let shared := ["clk","rst","xclk","xrst"].contains name
        (p.name,if shared then ref name else slice (ref name) (ch*p.ty.bitWidth) p.ty.bitWidth))

def toVerilog (c : Config) : Except String String := do
  return Sparkle.Backend.Verilog.toVerilog (← build c)

end OpenTPU.NativeSys
