import OpenTPU.FpgaTopConfig

/-! Native FPGA glue. Vendor bidirectional pads remain in a structural ABI shell;
all directed wiring and the two reset registers are represented by native AST. -/
namespace OpenTPU.FpgaTop
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

structure Pin where
  name : String
  width : Nat
  value : Expr

structure Boundary where
  name : String
  moduleName : String
  inputs : List Pin
  outputs : List (String × Nat)
  pads : List (String × Nat × String) := []
  unusedOutputs : List (String × Nat) := []

def Boundary.signal (b : Boundary) (p : String) := b.name ++ "_" ++ p
private def leaf (u p : String) : Expr := ref (u ++ "_" ++ p)
private def pin (n : String) (w : Nat) (e : Expr) : Pin := ⟨n,w,e⟩

def externalInputs : List (String × Nat) :=
  [("SYS_CLK",1),("lm73_alert_n",1),("pcie_refclk_clk_p",1),("pcie_refclk_clk_n",1),
   ("pcie_perstn",1),("pcie_mgt_rxp",8),("pcie_mgt_rxn",8)]

def ddrOutputs : List (String × Nat) :=
  (List.range 2).flatMap fun ch =>
    [("a",15),("ba",3),("ras_n",1),("cas_n",1),("we_n",1),("reset_n",1),
     ("clk_p",1),("clk_n",1),("cke",1),("cs_n",1),("odt",1)].map fun (n,w) => (s!"ddram{ch}_{n}",w)

def externalOutputs : List (String × Nat) :=
  [("led",3),("pcie_mgt_txp",8),("pcie_mgt_txn",8)] ++ ddrOutputs

def externalPads : List (String × Nat) :=
  [("lm73_scl",1),("lm73_sda",1),("smb_scl",1),("smb_sda",1)] ++
  (List.range 2).flatMap fun ch => [(s!"ddram{ch}_dq",72),(s!"ddram{ch}_dqs_p",9),(s!"ddram{ch}_dqs_n",9)]

/-- AXI-Lite master directions; true means master drives this signal. -/
private def axil : List (String × Nat × Bool) :=
  [("awaddr",32,true),("awvalid",1,true),("awready",1,false),
   ("wdata",32,true),("wstrb",4,true),("wvalid",1,true),("wready",1,false),
   ("bresp",2,false),("bvalid",1,false),("bready",1,true),
   ("araddr",32,true),("arvalid",1,true),("arready",1,false),
   ("rdata",32,false),("rresp",2,false),("rvalid",1,false),("rready",1,true)]

private def bd (systemInputs systemOutputs : List (String × Nat)) : Boundary := Id.run do
  let mut ins := [pin "sys_clk_50" 1 (leaf "u_bufg50" "O")]
  let mut outs := [("pcie_link_up",1),("core_clk",1),("core_rstn",1),("xdma_aclk",1),("xdma_aresetn",1),("device_temp",12)]
  for (n,w) in externalInputs do
    if n.startsWith "pcie_" then ins := ins ++ [pin n w (ref n)]
  outs := outs ++ [("pcie_mgt_txp",8),("pcie_mgt_txn",8)]
  for (stem,target,portPrefix) in [("M_AXI_CTL_","u_sys","s_ctl_"),("M_AXI_MEMCAL_","u_ld","ctl_")] do
    for (n,w,master) in axil do
      if master then outs := outs ++ [(stem ++ n,w)]
      else ins := ins ++ [pin (stem ++ n) w (leaf target (portPrefix ++ n))]
  for (n,w) in systemInputs ++ systemOutputs do
    if n.startsWith "x_" then
      let suffix := (n.drop 2).toString
      let width := if suffix == "awaddr" || suffix == "araddr" then 64 else w
      if systemInputs.contains (n,w) then outs := outs ++ [("M_AXI_DMA_" ++ suffix,width)]
      else ins := ins ++ [pin ("M_AXI_DMA_" ++ suffix) w (leaf "u_sys" n)]
  -- Original BD metadata pins are deliberately unconsumed at this boundary.
  let mut unused := []
  for direction in ["aw","ar"] do
    for (suffix,w) in [("size",3),("burst",2),("lock",1),("cache",4),("prot",3)] do
      unused := unused ++ [("M_AXI_DMA_" ++ direction ++ suffix,w)]
  return {name:="u_bd",moduleName:="otpu_bd_wrapper",inputs:=ins,outputs:=outs,unusedOutputs:=unused}

private def litedram (c : Config) : Boundary := Id.run do
  let mut ins := [pin "clk50g" 1 (leaf "u_bufg50" "O"),pin "rst" 1 (lit 0 1),
    pin "ctl_clk" 1 (leaf "u_bd" (if c.pcieGen == 2 then "core_clk" else "xdma_aclk")),
    pin "ctl_rst" 1 (ref (if c.pcieGen == 2 then "core_rst" else "xrst"))]
  let mut outs := [("sys_clk",1),("sys_rst",1)]
  for (n,w,master) in axil do
    if master then
      let v := leaf "u_bd" ("M_AXI_MEMCAL_" ++ n)
      let address := n == "awaddr" || n == "araddr"
      ins := ins ++ [pin ("ctl_" ++ n) (if address then 16 else w) (if address then slice v 0 16 else v)]
    else outs := outs ++ [("ctl_" ++ n,w)]
  for ch in [:2] do
    outs := outs ++ [(s!"c{ch}_ready",1)]
    for p in [:2] do
      let stem := s!"c{ch}" ++ (if p == 1 then "b_" else "_")
      for (n,w,driven) in [("cmd_valid",1,true),("cmd_ready",1,false),("cmd_we",1,true),
          ("cmd_addr",25,true),("wdata_valid",1,true),("wdata_ready",1,false),
          ("wdata_data",512,true),("wdata_we",64,true),("rdata_valid",1,false),("rdata_data",512,false)] do
        if driven then ins := ins ++ [pin (stem ++ n) w (slice (leaf "u_sys" ("c_" ++ n)) ((2*ch+p)*w) w)]
        else outs := outs ++ [(stem ++ n,w)]
      ins := ins ++ [pin (stem ++ "rdata_ready") 1 (lit 1 1)]
  return {name:="u_ld",moduleName:="otpu_litedram",inputs:=ins,outputs:=(outs ++ ddrOutputs), pads:=((externalPads.filter fun (n,_) => n.startsWith "ddram").map fun (n,w) => (n,w,n))}

private def systemValue (n : String) (w : Nat) : Expr :=
  if n == "clk" then leaf "u_bd" "core_clk"
  else if n == "rst" then ref "core_rst"
  else if n == "xclk" then leaf "u_bd" "xdma_aclk"
  else if n == "xrst" then ref "xrst"
  else if n == "calib" then pack [leaf "u_ld" "c0_ready",leaf "u_ld" "c1_ready"]
  else if n == "temp" then leaf "u_bd" "device_temp"
  else if n == "i2c_pin" then pack ([leaf "u_iob_scl0" "O",leaf "u_iob_sda0" "O",leaf "u_iob_scl1" "O",leaf "u_iob_sda1" "O",ref "lm73_alert_n"])
  else if n.startsWith "s_ctl_" then slice (leaf "u_bd" ("M_AXI_CTL_" ++ (n.drop 6).toString)) 0 w
  else if n.startsWith "x_" then slice (leaf "u_bd" ("M_AXI_DMA_" ++ (n.drop 2).toString)) 0 w
  else if n == "uclk" then pack [leaf "u_ld" "sys_clk",leaf "u_ld" "sys_clk"]
  else if n == "urst" then pack [leaf "u_ld" "sys_rst",leaf "u_ld" "sys_rst"]
  else pack <| (List.range 4).map fun i => leaf "u_ld" (s!"c{i/2}" ++ (if i%2 == 1 then "b_" else "_") ++ (n.drop 2).toString)

def boundaries (c : Config) : Except String (List Boundary) := do
  let (ins,outs) ← NativeSys.ports c.system
  let buffers := [({name:="u_ibuf50",moduleName:="IBUF",inputs:=[pin "I" 1 (ref "SYS_CLK")],outputs:=[("O",1)]} : Boundary),
    {name:="u_bufg50",moduleName:="BUFG",inputs:=[pin "I" 1 (leaf "u_ibuf50" "O")],outputs:=[("O",1)]}]
  let pads := [("scl0","lm73_scl"),("sda0","lm73_sda"),("scl1","smb_scl"),("sda1","smb_sda")]
  let iobs := pads.zipIdx |>.map fun ((suffix,padName),i) =>
    ({name:="u_iob_" ++ suffix,moduleName:="IOBUF",
      inputs:=[pin "I" 1 (lit 0 1),pin "T" 1 (bnot (bit (leaf "u_sys" "i2c_lo") i))],
      outputs:=[("O",1)],pads:=[("IO",1,padName)]} : Boundary)
  return buffers ++ [bd ins outs,litedram c] ++ iobs ++
    [{name:="u_sys",moduleName:="otpu_native_sys",inputs:=ins.map fun (n,w) => pin n w (systemValue n w),outputs:=outs}]

/-- Two independent clock-domain reset registers. No reset is added; the initial
zero refines the reference's unconstrained power-up value. -/
def build (c : Config) : Except String Module := do
  let bs ← boundaries c
  return runModule "otpu_fpga_top_ld_sparkle" do
    for (n,w) in externalInputs do let _ ← input n w
    for b in bs do
      for (n,w) in b.outputs do let _ ← input (b.signal n) w
    let m ← getModule
    setModule (m.addWire {name:="no_reset",ty:=.bitVector 1})
    emitAssign "no_reset" (lit 0 1)
    for (n,clk,rstn) in [("core_rst","core_clk","core_rstn"),("xrst","xdma_aclk","xdma_aresetn")] do
      let m ← getModule
      setModule <| (m.addWire {name:=n,ty:=.bitVector 1}).addStmt
        (.register n ("u_bd_" ++ clk) ("no_reset",.synchronous) (bnot (leaf "u_bd" rstn)) 0)
    for b in bs do
      for p in b.inputs do output (b.signal p.name) p.width p.value
    for (n,w) in externalOutputs do
      let value := if n == "led" then
        pack [bit (leaf "u_sys" "led") 0,
          band (leaf "u_bd" "pcie_link_up") (band (leaf "u_ld" "c0_ready") (leaf "u_ld" "c1_ready")),
          bor (bit (leaf "u_sys" "led") 2) (bit (leaf "u_sys" "led") 1)]
        else leaf (if n.startsWith "ddram" then "u_ld" else "u_bd") n
      output n w value
end OpenTPU.FpgaTop
