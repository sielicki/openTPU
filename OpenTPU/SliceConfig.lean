import OpenTPU.Seq
import OpenTPU.Dma
import OpenTPU.Mxu
import OpenTPU.ActRam
import OpenTPU.Quant
import OpenTPU.Vpu
import OpenTPU.TMem
import OpenTPU.SliceArbiter

namespace OpenTPU.Slice
open OpenTPU.Circuit

structure Config where
  sliceId : Nat := 0
  slices : Nat := 1
  depth : Nat := 32
  columns : Nat := 8
  actBlocks : Nat := 64
  actRows : Nat := 8
  tmemWords : Nat := 65536
  imemWords : Nat := 65536
  fifoDepth : Nat := 128
  lanes : Nat := 8
  slots : Nat := 32
  readsPerBank : Nat := 4
  writesPerBank : Nat := 2
  mxuImpl : Nat := 0
  mxuChain : Nat := 16
  compositeLanes : Nat := 2
  unitLanes : Nat := 8
  pqWindow : Nat := 64
  streams : Bool := true
  deriving Repr

def Config.hasStream (c : Config) := c.streams && c.lanes == 8 && c.depth >= 32
def Config.buffered (c : Config) := c.readsPerBank >= 8*c.lanes && c.writesPerBank == 1

def Config.seq (c : Config) : Seq.Config :=
  {words := c.imemWords,depth := c.depth,slices := c.slices,slots := c.slots}
def Config.dma (c : Config) : Dma.Config := ⟨c.depth,c.lanes,128,c.hasStream⟩
def Config.mxu (c : Config) : Mxu.Config :=
  ⟨c.depth,c.columns,c.actRows,c.fifoDepth,c.unitLanes,c.mxuImpl,c.mxuChain,c.sliceId⟩
def Config.act (c : Config) : ActRam.Config := ⟨c.depth,c.columns,c.actRows,c.actBlocks,c.unitLanes⟩
def Config.quant (c : Config) : Quant.Config := ⟨c.depth,c.unitLanes⟩
def Config.vpu (c : Config) : Vpu.Config :=
  {lanes := c.lanes,compositeLanes := c.compositeLanes,streams := c.hasStream,buffered := c.buffered}
def Config.tmem (c : Config) : TMem.Config := ⟨c.tmemWords,c.lanes,8,4,c.writesPerBank,1,2,1,160⟩
def Config.arbiter (c : Config) : SliceArbiter.Config := ⟨c.lanes,c.readsPerBank,c.writesPerBank⟩

def Config.validate (c : Config) : Except String Unit := do
  if c.unitLanes > c.lanes then throw "slice requires ULANES <= LANES"
  if c.pqWindow == 0 || c.pqWindow >= 2^24 then throw "slice PQ_WIN must be 1 .. 2^24 - 1"
  c.seq.validate
  c.dma.validate
  c.mxu.validateWhole
  c.act.validate
  c.quant.validate
  c.tmem.validate
  VpuDatapathSupport.validate c.vpu.toConfig
  if c.readsPerBank == 0 || c.writesPerBank == 0 ||
      c.readsPerBank >= 2^31 || c.writesPerBank >= 2^31 then
    throw "slice bank capacities must be positive signed integers"

end OpenTPU.Slice
