import OpenTPU.NativeSysABI
import OpenTPU.BoardNativeABI

namespace OpenTPU.NativeSys

/-- Complete native accelerator subsystem behind the original NativeSys ABI.
The board, Slice, DMA splitter and both memory channels are included. FPGA
vendor IP and the external memory-controller ports remain outside this boundary. -/
def abiVerilog (c : Config) : Except String String := do
  return (← Board.nativeAbiVerilog c.board) ++ (← emitShell c)

end OpenTPU.NativeSys
