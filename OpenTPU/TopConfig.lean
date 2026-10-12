import OpenTPU.SliceABI
import OpenTPU.Collective
import OpenTPU.DramABI
import OpenTPU.NativeDramABI

namespace OpenTPU.Top
structure Config where
  slice : Slice.Config := {}
  dramWords : Nat := 262144
  dramLatency : Nat := 8
  axi : Nat := 0
  deriving Repr

def Config.at (c : Config) (sid : Nat) : Slice.Config := {c.slice with sliceId:=sid}
def Config.dram (c : Config) : Dram.Config := ⟨c.dramWords,c.slice.depth,c.dramLatency⟩
def Config.memory (c : Config) : NativeDram.Config := {depth:=c.slice.depth}
def Config.collective (c : Config) : Collective.Config := ⟨c.slice.slices,c.slice.lanes⟩
def Config.sliceParameters (c : Config) (sid : Nat) : List (String × Nat) :=
  let p := c.at sid
  [("SID",sid),("S",p.slices),("D",p.depth),("MCOLS",p.columns),("ACT_BLOCKS",p.actBlocks),
   ("ACT_ROWS",p.actRows),("TMEM_WORDS",p.tmemWords),("IMEM_WORDS",p.imemWords),
   ("FIFO_DEPTH",p.fifoDepth),("LANES",p.lanes),("WIN",p.slots),("RPB",p.readsPerBank),
   ("WPB",p.writesPerBank),("MXU_IMPL",p.mxuImpl),("MXU_CL",p.mxuChain),
   ("VPU_CL",p.compositeLanes),("ULANES",p.unitLanes)]
def Config.parameters (c : Config) : List (String × Nat) :=
  (c.sliceParameters 0).filter (fun p => p.1 != "SID") ++
  [("DRAM_WORDS",c.dramWords),("DRAM_LAT",c.dramLatency),("AXI",c.axi)]
def Config.validate (c : Config) : Except String Unit := do
  if c.axi > 2 then throw "top: AXI must be 0, 1 or 2"
  if c.slice.sliceId != 0 then throw "top: slice template SID must be zero; each instance receives its own SID"
  if c.slice.pqWindow != 64 || !c.slice.streams then
    throw "top: original simulation top uses default PQ_WIN=64 and HAS_DSTEP=1"
  c.slice.validate
  c.collective.validate
  c.dram.validate
  if c.axi != 0 then c.memory.validate
end OpenTPU.Top
