import OpenTPU.AxiSlice

namespace OpenTPU.AxiSplit
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

structure Config where
  idWidth : Nat := 4
  dataWidth : Nat := 128
  outstanding : Nat := 16
  deriving Repr

/-- Address-bit-31 split with independent retained W, B and R ordering queues. -/
def build (c : Config) : Except String Design := do
  if c.idWidth == 0 || c.dataWidth == 0 || c.dataWidth % 8 != 0 then
    throw "AXI split requires positive ID width and byte-multiple data width"
  let fifo ← BoardFifo.fifo ⟨1,c.outstanding,true⟩
  let top := runModule "otpu_axi_split2_sparkle" do
    let _ ← input "clk" 1
    let _ ← input "rst" 1
    for (channel,reverse,fields) in AxiSlice.channels ⟨false,c.idWidth,c.dataWidth⟩ do
      let origin := if reverse then "m" else "s"
      let dest := if reverse then "s" else "m"
      let _ ← input s!"{origin}_{channel}valid" (if reverse then 2 else 1)
      let _ ← input s!"{dest}_{channel}ready" (if reverse then 1 else 2)
      for (field,w) in fields do
        let _ ← input s!"{origin}_{channel}{field}" (if reverse then 2*w else w)
    for route in ["ow","ob","or"] do
      for suffix in ["wr","rv","rd"] do
        let m ← getModule
        setModule (m.addWire {name := s!"{route}_{suffix}",ty := .bitVector 1})
    let awc := bit (ref "s_awaddr") 31
    let arc := bit (ref "s_araddr") 31
    let select := fun (name : String) (width : Nat) (index : Expr) =>
      mux index (slice (ref name) width width) (slice (ref name) 0 width)
    let route := fun (enabled index : Expr) => pack [band enabled (bnot index),band enabled index]
    let awready := band (band (ref "ow_wr") (ref "ob_wr")) (select "m_awready" 1 awc)
    let wready := band (ref "ow_rv") (select "m_wready" 1 (ref "ow_rd"))
    let bvalid := band (ref "ob_rv") (select "m_bvalid" 1 (ref "ob_rd"))
    let arready := band (ref "or_wr") (select "m_arready" 1 arc)
    let rvalid := band (ref "or_rv") (select "m_rvalid" 1 (ref "or_rd"))
    let rlast := select "m_rlast" 1 (ref "or_rd")
    for (name,writeData,writeEnable,readEnable) in
      [("ow",awc,band (ref "s_awvalid") awready,band (band (ref "s_wvalid") wready) (ref "s_wlast")),
       ("ob",awc,band (ref "s_awvalid") awready,band bvalid (ref "s_bready")),
       ("or",arc,band (ref "s_arvalid") arready,band (band rvalid (ref "s_rready")) rlast)] do
      emitInstance fifo.name s!"u_{name}" [("clk",ref "clk"),("rst",ref "rst"),
        ("wvalid",writeEnable),("wready",ref s!"{name}_wr"),("wdata",writeData),
        ("rvalid",ref s!"{name}_rv"),("rready",readEnable),("rdata",ref s!"{name}_rd")]
    output "m_awvalid" 2 (route (band (ref "s_awvalid") (band (ref "ow_wr") (ref "ob_wr"))) awc)
    output "s_awready" 1 awready
    output "m_wvalid" 2 (route (band (ref "s_wvalid") (ref "ow_rv")) (ref "ow_rd"))
    output "s_wready" 1 wready
    output "s_bvalid" 1 bvalid
    output "s_bid" c.idWidth (select "m_bid" c.idWidth (ref "ob_rd"))
    output "s_bresp" 2 (select "m_bresp" 2 (ref "ob_rd"))
    output "m_bready" 2 (route (band (ref "s_bready") (ref "ob_rv")) (ref "ob_rd"))
    output "m_arvalid" 2 (route (band (ref "s_arvalid") (ref "or_wr")) arc)
    output "s_arready" 1 arready
    output "s_rvalid" 1 rvalid
    output "s_rid" c.idWidth (select "m_rid" c.idWidth (ref "or_rd"))
    output "s_rdata" c.dataWidth (select "m_rdata" c.dataWidth (ref "or_rd"))
    output "s_rresp" 2 (select "m_rresp" 2 (ref "or_rd"))
    output "s_rlast" 1 rlast
    output "m_rready" 2 (route (band (ref "s_rready") (ref "or_rv")) (ref "or_rd"))
  return {topModule := top.name,modules := [fifo,top]}

/-- Preserve the reference ordering FIFOs' distributed RAM inference. -/
def emitModules (modules : List Module) : Except String String := do
  let emitted ← modules.mapM fun m =>
    if m.name == "otpu_sfifo_sparkle" then Backend.withMemoryHints m [("mem",.distributed)]
    else pure (Sparkle.Backend.Verilog.toVerilog m)
  return String.join emitted

def toVerilog (c : Config) : Except String String := do
  emitModules (← build c).modules

end OpenTPU.AxiSplit
