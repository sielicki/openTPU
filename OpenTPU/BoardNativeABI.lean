import OpenTPU.BoardABI
import OpenTPU.SliceABI

namespace OpenTPU.Board

/-- All original board-to-slice parameter overrides, including the streaming
feature flag and performance bucket window. -/
def Config.nativeSlice (c : Config) : Slice.Config :=
  { sliceId := 0
    slices := 1
    depth := c.d
    columns := c.columns
    actBlocks := c.actBlocks
    actRows := c.actRows
    tmemWords := c.tmemWords
    imemWords := c.imemWords
    fifoDepth := c.fifoDepth
    lanes := c.lanes
    slots := c.window
    readsPerBank := c.readsPerBank
    writesPerBank := c.writesPerBank
    mxuImpl := c.mxuImplementation
    mxuChain := c.mxuChainLength
    compositeLanes := c.vpuCompositeLanes
    unitLanes := c.unitLanes
    pqWindow := c.pqWindow
    streams := c.dstep }

/-- Complete native board hardware behind the original board ABI. The existing
packed/unpacked slice bridge now resolves to the native Slice ABI included here.
No original board or slice hardware source is needed. -/
def nativeAbiVerilog (c : Config) : Except String String := do
  return (← Slice.abiVerilog c.nativeSlice) ++ (← abiVerilog c)

end OpenTPU.Board
