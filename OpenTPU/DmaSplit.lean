import OpenTPU.AxiSplit

namespace OpenTPU.DmaSplit
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit
abbrev Config := AxiSlice.Config

private def declared (name : String) (width : Nat) : CircuitM Unit := do
  let m ← getModule
  setModule (m.addWire {name,ty := .bitVector width})

/-- Native XDMA ingress slice, ordered channel split and two egress slices. -/
def build (c : Config) : Except String Design := do
  let slices ← AxiSlice.build c
  let split ← AxiSplit.build ⟨c.idWidth,c.dataWidth,16⟩
  let some xs := slices.modules.find? (·.name == slices.topModule) | throw "AXI slice missing"
  let some sp := split.modules.find? (·.name == split.topModule) | throw "AXI split missing"
  let top := runModule "otpu_dma_split_sparkle" do
    for p in xs.inputs do
      let _ ← input p.name (p.ty.bitWidth * if p.name.startsWith "m_" then 2 else 1)
    for p in xs.outputs do
      declared s!"ext_{p.name}" (p.ty.bitWidth * if p.name.startsWith "m_" then 2 else 1)
    for p in xs.inputs ++ xs.outputs do
      if p.name.startsWith "m_" then declared s!"i_{(p.name.drop 2).toString}" p.ty.bitWidth
    for p in sp.inputs ++ sp.outputs do
      if p.name.startsWith "m_" then declared s!"j_{(p.name.drop 2).toString}" p.ty.bitWidth
    let external := fun (p : Port) => ref (if xs.outputs.any (·.name == p.name) then s!"ext_{p.name}" else p.name)
    let ingress := (xs.inputs ++ xs.outputs).map fun p => (p.name,
      if p.name.startsWith "m_" then ref s!"i_{(p.name.drop 2).toString}" else external p)
    emitInstance xs.name "u_xs" ingress
    emitInstance sp.name "u_split" ((sp.inputs ++ sp.outputs).map fun p =>
      (p.name, if p.name.startsWith "s_" then ref s!"i_{(p.name.drop 2).toString}"
       else if p.name.startsWith "m_" then ref s!"j_{(p.name.drop 2).toString}" else ref p.name))
    for channel in [:2] do
      let connections := (xs.inputs ++ xs.outputs).map fun p =>
        let suffix := (p.name.drop 2).toString
        let value := if p.name.startsWith "m_" then slice (external p) (channel*p.ty.bitWidth) p.ty.bitWidth
          else if p.name.startsWith "s_" then
            if (sp.inputs ++ sp.outputs).any (·.name == s!"m_{suffix}") then
              slice (ref s!"j_{suffix}") (channel*p.ty.bitWidth) p.ty.bitWidth
            else ref s!"i_{suffix}"
          else ref p.name
        (p.name,value)
      emitInstance xs.name s!"u_cs{channel}" connections
    for p in xs.outputs do
      output p.name (p.ty.bitWidth * if p.name.startsWith "m_" then 2 else 1) (ref s!"ext_{p.name}")
  return {topModule := top.name,modules := slices.modules ++ split.modules ++ [top]}

def toVerilog (c : Config) : Except String String := do
  AxiSplit.emitModules (← build c).modules

end OpenTPU.DmaSplit
