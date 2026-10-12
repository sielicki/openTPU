import OpenTPU.BoardConfig
import OpenTPU.DmaSplit
import OpenTPU.MemChannel

namespace OpenTPU.NativeSys

structure Config where
  columns : Nat := 2
  actRows : Nat := 2
  vpuCompositeLanes : Nat := 2
  mxuImplementation : Nat := 0
  lanes : Nat := 8
  unitLanes : Nat := 8
  coreKhz : Nat := 100000
  buildId : Nat := 0
  ddrMts : Nat := 0
  dstep : Bool := true
  hostCalibration : Bool := false
  registeredDma : Bool := false
  deriving Repr

/-- Original NativeSys overrides exactly these Board fields. All other Board
    parameters retain their original defaults. Dependent ACT_ROWS is explicit. -/
def Config.board (c : Config) : Board.Config :=
  {columns:=c.columns,actRows:=c.actRows,vpuCompositeLanes:=c.vpuCompositeLanes,
   mxuImplementation:=c.mxuImplementation,lanes:=c.lanes,unitLanes:=c.unitLanes,
   readsPerBank:=8*c.lanes,
   coreKhz:=c.coreKhz,buildId:=c.buildId,ddrMts:=c.ddrMts,dstep:=c.dstep,
   hostCalibration:=c.hostCalibration}

def Config.split (c : Config) : DmaSplit.Config :=
  {registered:=c.registeredDma,idWidth:=4,dataWidth:=128}

def Config.channel (_c : Config) : MemChannel.Config := {idWidth:=4}

def Config.parameters (c : Config) : List (String × Nat) :=
  [("MCOLS",c.columns),("ACT_ROWS",c.actRows),("VPU_CL",c.vpuCompositeLanes),
   ("MXU_IMPL",c.mxuImplementation),("LANES",c.lanes),("ULANES",c.unitLanes),
   ("CORE_KHZ",c.coreKhz),("BUILD_ID",c.buildId),("DDR_MTS",c.ddrMts),
   ("DSTEP",if c.dstep then 1 else 0),("HOSTCAL",if c.hostCalibration then 1 else 0),
   ("XREG",if c.registeredDma then 1 else 0)]

end OpenTPU.NativeSys
