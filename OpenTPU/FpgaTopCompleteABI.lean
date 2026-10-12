import OpenTPU.FpgaTopABI
import OpenTPU.SlicePhysicalABI

namespace OpenTPU.FpgaTop

/-- Complete native hardware with behavioral arithmetic ASTs. Only the FPGA
vendor clock/I/O primitives, PCIe block design and LiteDRAM remain external.
Component proof applicability is qualified separately for each configuration. -/
def abiVerilog (c : Config) : Except String String := do
  return (← NativeSys.abiVerilog c.system) ++ (← emitShell c)

/-- Physical MXU selection additionally exposes explicit DSP48E1 primitives;
all non-MXU native modules and FPGA boundary wiring retain the same definitions. -/
def physicalAbiVerilog (c : Config) : Except String String := do
  return (← NativeSys.physicalAbiVerilog c.system) ++ (← emitShell c)

end OpenTPU.FpgaTop
