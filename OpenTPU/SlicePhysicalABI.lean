import OpenTPU.NativeSysCompleteABI
import OpenTPU.MxuPhysical

/-! Native Slice/Board/System assembly with explicit MXU DSP48E1 primitives.
The primitive implementation/model is external. Simulation diagnostics use the
same Yosys DSP model hierarchy as the qualified physical MXU ABI.+-/
namespace OpenTPU.Slice

/-- Keep the native composition and every non-MXU child unchanged. Hardware is
emitted from ASTs; only the MXU implementation selects explicit DSP primitives. -/
def physicalVerilog (c : Config) : Except String String := do
  let top ← build c
  let emitted := (← Physical.seq c.seq) ++ (← Physical.tmem c.tmem) ++
    (← Physical.actram c.act) ++ (← Dma.toVerilog c.dma) ++
    (← MxuPhysical.emit c.mxu) ++ (← Quant.toVerilog c.quant) ++
    (← Vpu.toVerilog c.vpu) ++ (← SliceLoader.toVerilog c.depth) ++
    SliceRld.toVerilog ++ (← SlicePorts.dramVerilog c.depth) ++
    (← SlicePorts.tmemVerilog c.lanes c.unitLanes) ++
    (← SliceArbiter.toVerilog c.arbiter) ++
    (← SlicePerf.toVerilog ⟨c.lanes,c.fifoDepth⟩) ++
    Sparkle.Backend.Verilog.toVerilog top
  return emitted.replace " ? " " ?\n        "

private def mxuSimulationBody (adapter : String) : Except String String := do
  let regions := adapter.splitOn "`ifndef SYNTHESIS"
  if regions.length != 2 then throw "physical Slice: expected one MXU simulation region"
  let body := regions[1]!.splitOn "`endif"
  if body.length != 2 then throw "physical Slice: expected one MXU simulation terminator"
  return body[0]!.replace "impl." "impl.u_mxu."

/-- Adapt only generated simulation diagnostics, never hardware text. Require
exactly one matching diagnostic block so upstream changes cannot silently omit it. -/
def physicalWrapper (c : Config) : Except String String := do
  let base ← wrapper c
  let oldBody ← mxuSimulationBody (Mxu.wrapper c.mxu)
  let newBody ← mxuSimulationBody (Mxu.wrapperDSPModel c.mxu)
  if (base.splitOn oldBody).length != 2 then
    throw "physical Slice: expected exactly one MXU diagnostic block"
  return base.replace oldBody newBody

def physicalAbiVerilog (c : Config) : Except String String := do
  return (← physicalVerilog c) ++ (← physicalWrapper c)

end OpenTPU.Slice

namespace OpenTPU.Board

def physicalNativeAbiVerilog (c : Config) : Except String String := do
  return (← Slice.physicalAbiVerilog c.nativeSlice) ++ (← abiVerilog c)

end OpenTPU.Board

namespace OpenTPU.NativeSys

def physicalAbiVerilog (c : Config) : Except String String := do
  return (← Board.physicalNativeAbiVerilog c.board) ++ (← emitShell c)

end OpenTPU.NativeSys
