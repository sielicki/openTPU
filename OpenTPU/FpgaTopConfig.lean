import OpenTPU.NativeSys

namespace OpenTPU.FpgaTop
structure Config where
  columns : Nat := 4
  actRows : Nat := 4
  vpuCompositeLanes : Nat := 2
  mxuImplementation : Nat := 2
  lanes : Nat := 8
  unitLanes : Nat := 8
  coreKhz : Nat := 100000
  buildId : Nat := 0
  ddrMts : Nat := 1066
  dstep : Bool := true
  pcieGen : Nat := 1
  deriving Repr

def Config.system (c : Config) : NativeSys.Config :=
  {columns:=c.columns,actRows:=c.actRows,vpuCompositeLanes:=c.vpuCompositeLanes,
   mxuImplementation:=c.mxuImplementation,lanes:=c.lanes,unitLanes:=c.unitLanes,
   coreKhz:=c.coreKhz,buildId:=c.buildId,ddrMts:=c.ddrMts,dstep:=c.dstep,
   hostCalibration:=true,registeredDma:=c.pcieGen == 2}

def Config.parameters (c : Config) : List (String × Nat) :=
  (c.system.parameters.filter fun p => p.1 != "HOSTCAL" && p.1 != "XREG") ++ [("PCIE_GEN",c.pcieGen)]
end OpenTPU.FpgaTop
