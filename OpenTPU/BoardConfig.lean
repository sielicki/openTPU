import OpenTPU.Control
import OpenTPU.Trace
import OpenTPU.Collective
import OpenTPU.NativeDram

namespace OpenTPU.Board
open OpenTPU.Circuit

/-- Elaboration values of the original single-slice board. Dependent defaults
    are explicit fields: callers changing LANES/MCOLS must set their companions. -/
structure Config where
  d : Nat := 128
  columns : Nat := 2
  actBlocks : Nat := 128
  actRows : Nat := 2
  tmemWords : Nat := 65536
  imemWords : Nat := 32768
  fifoDepth : Nat := 1024
  lanes : Nat := 8
  window : Nat := 16
  readsPerBank : Nat := 64
  writesPerBank : Nat := 1
  mxuImplementation : Nat := 0
  mxuChainLength : Nat := 16
  vpuCompositeLanes : Nat := 2
  unitLanes : Nat := 8
  coreKhz : Nat := 100000
  buildId : Nat := 0
  ddrMts : Nat := 0
  traceDepth : Nat := 16384
  traceQueueDepth : Nat := 32
  pqWindow : Nat := 1024
  hasI2c : Bool := true
  channelHash : Bool := true
  dstep : Bool := true
  hostCalibration : Bool := false
  deriving Repr

def Config.control (c : Config) : Control.Config :=
  {depth:=c.d,columns:=c.columns,lanes:=c.lanes,actRows:=c.actRows,
   coreKhz:=c.coreKhz,buildId:=c.buildId,ddrMts:=c.ddrMts,
   traceDepth:=c.traceDepth,pqWindow:=c.pqWindow,hasTemp:=true,
   hasI2c:=c.hasI2c,channelHash:=c.channelHash,dstep:=c.dstep,hostCalibration:=c.hostCalibration}

def Config.trace (c : Config) : Trace.Config :=
  {depth:=c.traceDepth,queueDepth:=c.traceQueueDepth,window:=c.window}

def Config.collective (c : Config) : Collective.Config := {slices:=1,lanes:=c.lanes}

/-- The board overrides exactly D and CHASH; all adapter queue settings retain
    their reference defaults. -/
def Config.memory (c : Config) : NativeDram.Config := {depth:=c.d,channelHash:=c.channelHash}

def Config.sliceParameters (c : Config) : List (String × Nat) :=
  [("SID",0),("S",1),("D",c.d),("MCOLS",c.columns),("ACT_BLOCKS",c.actBlocks),
   ("ACT_ROWS",c.actRows),("TMEM_WORDS",c.tmemWords),("IMEM_WORDS",c.imemWords),
   ("FIFO_DEPTH",c.fifoDepth),("LANES",c.lanes),("WIN",c.window),
   ("RPB",c.readsPerBank),("WPB",c.writesPerBank),("MXU_IMPL",c.mxuImplementation),
   ("MXU_CL",c.mxuChainLength),("VPU_CL",c.vpuCompositeLanes),("ULANES",c.unitLanes),
   ("PQ_WIN",c.pqWindow),("HAS_DSTEP",if c.dstep then 1 else 0)]

def Config.parameters (c : Config) : List (String × Nat) :=
  (c.sliceParameters.filter fun p => p.1 != "SID" && p.1 != "S" && p.1 != "HAS_DSTEP" && p.1 != "PQ_WIN") ++
  [("CORE_KHZ",c.coreKhz),("BUILD_ID",c.buildId),("DDR_MTS",c.ddrMts),
   ("TRACE_DEPTH",c.traceDepth),("TRACE_QD",c.traceQueueDepth),("PQ_WIN",c.pqWindow),
   ("HAS_I2C",if c.hasI2c then 1 else 0),("CHASH",if c.channelHash then 1 else 0),
   ("DSTEP",if c.dstep then 1 else 0),("HOSTCAL",if c.hostCalibration then 1 else 0)]

def Config.validate (c : Config) : Except String Unit := do
  c.memory.validate
  c.collective.validate
  if c.columns == 0 || c.actRows < c.columns || c.actRows > 255 then
    throw "board: require 1 <= MCOLS <= ACT_ROWS <= 255"
  if c.pqWindow == 0 || c.pqWindow >= 2^24 then throw "board: PQ_WIN must be 1 .. 2^24-1"
  if c.buildId >= 2^32 then throw "board: BUILD_ID must fit 32 bits"
  if c.traceDepth != 0 then
    let _ ← Trace.build c.trace
    pure ()

end OpenTPU.Board
