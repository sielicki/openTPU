import OpenTPU.MemChannelReset
import OpenTPU.MemChannelAccelerator
import OpenTPU.MemChannelXdma
import OpenTPU.MemChannelController

namespace OpenTPU.MemChannel
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.MemChannelSupport
abbrev Config := MemChannelSupport.Config

def inputPorts (c : Config) : List (String × Nat) :=
  [("clk",1),("rst",1),("n_cvalid",1),("n_cwe",1),("n_caddr",25),
   ("n_wvalid",1),("n_wdata",512),("n_wmask",64),("xclk",1),("xrst",1),
   ("x_awvalid",1),("x_awid",c.idWidth),("x_awaddr",32),("x_awlen",8),
   ("x_wvalid",1),("x_wdata",128),("x_wstrb",16),("x_wlast",1),("x_bready",1),
   ("x_arvalid",1),("x_arid",c.idWidth),("x_araddr",32),("x_arlen",8),("x_rready",1),
   ("uclk",1),("urst",1),("c_cmd_ready",2),("c_wdata_ready",2),("c_rdata_valid",2),("c_rdata_data",1024)]

def outputPorts (c : Config) : List (String × Nat) :=
  [("n_cready",1),("n_wready",1),("n_rvalid",1),("n_rdata",512),("n_wdone",16),("n_err",1),
   ("x_awready",1),("x_wready",1),("x_bvalid",1),("x_bid",c.idWidth),("x_bresp",2),
   ("x_arready",1),("x_rvalid",1),("x_rid",c.idWidth),("x_rdata",128),("x_rresp",2),("x_rlast",1),
   ("c_cmd_valid",2),("c_cmd_we",2),("c_cmd_addr",50),("c_wdata_valid",2),("c_wdata_data",1024),("c_wdata_we",128)]

structure FifoInstance where
  name : String
  module : Module
  inputs : List (String × Expr)
  outputs : List (String × String × Nat)

def afifoName (c : AsyncFifo.Config) :=
  s!"otpu_mem_channel_afifo_{c.width}_{c.depth}_{if c.outOfOrder then 1 else 0}_{if c.registeredReady then 1 else 0}"
def sfifoName (c : BoardFifo.Config) :=
  s!"otpu_mem_channel_sfifo_{c.width}_{c.depth}_{if c.registeredOutput then 1 else 0}"

def fifos (c : Config) : Except String (List FifoInstance) := do
  let mut result := []
  for (p,conf,wclk,wrst,rclk,rrst) in [
      ("aq",⟨26,32,false,false⟩,"clk","a_hs2","uclk","a_hold"),
      ("ad",⟨577,32,false,false⟩,"clk","a_hs2","uclk","a_hold"),
      ("ar",⟨512,c.acceleratorDepth,true,false⟩,"uclk","a_hold","clk","a_hs2"),
      ("xq",⟨26,16,false,true⟩,"xclk","x_hs2","uclk","x_hold"),
      ("xd",⟨577,16,false,true⟩,"xclk","x_hs2","uclk","x_hold"),
      ("xr",⟨512,c.xdmaDepth,true,false⟩,"uclk","x_hold","xclk","x_hs2")] do
    let conf : AsyncFifo.Config := conf
    let core ← AsyncFifo.build conf
    result := result ++ [{
      name := s!"u_{p}",module := {core with name := afifoName conf},
      inputs := [("wclk",ref wclk),("wrst",ref wrst),("wvalid",ref s!"{p}_wv"),("wdata",ref s!"{p}_wd"),
        ("wslot",if conf.outOfOrder then ref s!"{p}_slot" else lit 0 (clog2 conf.depth)),
        ("rclk",ref rclk),("rrst",ref rrst),("rready",ref s!"{p}_rr")],
      outputs := [("wready",s!"{p}_wr",1),("wcommit",s!"{p}_cmt",1),("wused",s!"{p}_used",clog2 conf.depth+1),
        ("rvalid",s!"{p}_rv",1),("rdata",s!"{p}_rd",conf.width)]}]
  for (p,w,d) in [("xai",32,4),("xwi",27,4),("xrq",c.idWidth+10,16),("xbq",c.idWidth+7,16)] do
    let conf : BoardFifo.Config := ⟨w,d,true⟩
    let core ← BoardFifo.fifo conf
    result := result ++ [{
      name := s!"u_{p}",module := {core with name := sfifoName conf},
      inputs := [("clk",ref "xclk"),("rst",ref "x_crst"),("wvalid",ref s!"{p}_wv"),
        ("wdata",ref s!"{p}_wd"),("rready",ref s!"{p}_rr")],
      outputs := [("wready",s!"{p}_wr",1),("rvalid",s!"{p}_rv",1),("rdata",s!"{p}_rd",w)]}]
  for p in List.range 2 do
    for (q,w,d,wvalid,wdata,rready) in [
        ("oq",27,c.commandDepth,bit (ref "oq_push") p,ref "oq_wd",bit (ref "oq_rr") p),
        ("of",512,c.dataDepth,bit (ref "of_wv") p,ref "of_wd",bit (ref "c_wdata_ready") p),
        ("tg",tw c,128,bit (ref "tg_wv") p,ref "tg_wd",bit (ref "tg_rr") p)] do
      let conf : BoardFifo.Config := ⟨w,d,false⟩
      let core ← BoardFifo.fifo conf
      result := result ++ [{
        name := s!"u_{q}{p}",module := {core with name := sfifoName conf},
        inputs := [("clk",ref "uclk"),("rst",ref "urq"),("wvalid",wvalid),("wdata",wdata),("rready",rready)],
        outputs := [("wready",s!"{q}_wr{p}",1),("rvalid",s!"{q}_rv{p}",1),("rdata",s!"{q}_rd{p}",w)]}]
  return result

def units (c : Config) : List (String × Module) :=
  [("reset",MemChannelReset.build c),("accelerator",MemChannelAccelerator.build),
   ("xdma",MemChannelXdma.build c),("controller",MemChannelController.build c)]

private def nameOf (name : String) := (name.drop 2).toString

def aggregates (c : Config) : List (String × Nat × Expr) :=
  [("oq_wr",2,pack [ref "oq_wr0",ref "oq_wr1"]),("oq_rv",2,pack [ref "oq_rv0",ref "oq_rv1"]),
   ("oq_rd",54,pack [ref "oq_rd0",ref "oq_rd1"]),("of_wr",2,pack [ref "of_wr0",ref "of_wr1"]),
   ("tg_wr",2,pack [ref "tg_wr0",ref "tg_wr1"]),("tg_rv",2,pack [ref "tg_rv0",ref "tg_rv1"]),
   ("tg_rd",2*tw c,pack [ref "tg_rd0",ref "tg_rd1"]),
   ("c_wdata_valid",2,pack [ref "of_rv0",ref "of_rv1"]),
   ("c_wdata_data",1024,pack [ref "of_rd0",ref "of_rd1"]),("c_wdata_we",128,lit (2^128-1) 128)]

/-- Closed native assembly: child widths and every control boundary are checked. -/
def build (c : Config) : Except String Design := do
  validate c
  let us := units c
  let fs ← fifos c
  let sources := us.flatMap (fun (_,m) => m.outputs.map fun p => (nameOf p.name,p.ty.bitWidth)) ++
    fs.flatMap (fun f => f.outputs.map fun (_,n,w) => (n,w)) ++ (aggregates c).map (fun (n,w,_) => (n,w))
  let mut seen : List String := []
  for (n,_) in sources do
    if seen.contains n then throw s!"Memory channel duplicate driver {n}"
    seen := n :: seen
  for (unit,m) in us do
    for port in m.inputs do
      let some (_,width) := (sources ++ inputPorts c).find? (fun (n,_) => n == port.name)
        | throw s!"Memory channel missing input {unit}.{port.name}"
      if width != port.ty.bitWidth then throw s!"Memory channel input width {unit}.{port.name}"
  for (n,w) in outputPorts c do
    if !(sources.contains (n,w)) then throw s!"Memory channel missing output {n}"
  let top := runModule "otpu_mem_channel_sparkle" do
    for (n,w) in inputPorts c do let _ ← input n w
    for (n,w) in sources do declared n w
    for (unit,m) in us do
      emitInstance m.name s!"u_{unit}" ((m.inputs.map fun p => (p.name,ref p.name)) ++
        (m.outputs.map fun p => (p.name,ref (nameOf p.name))))
    for fifo in fs do
      emitInstance fifo.module.name fifo.name (fifo.inputs ++ fifo.outputs.map (fun (p,n,_) => (p,ref n)))
    for (n,_,value) in aggregates c do emitAssign n value
    for (n,w) in outputPorts c do addOutput n (.bitVector w)
  let mut ms := us.map Prod.snd
  for fifo in fs do
    if !(ms.any (·.name == fifo.module.name)) then ms := ms ++ [fifo.module]
  return {topModule := top.name, modules := ms ++ [top]}

def toVerilog (c : Config) : Except String String := do
  let design ← build c
  let mut result := ""
  for m in design.modules do
    let async := m.name.startsWith "otpu_mem_channel_afifo_"
    let fifo := async || m.name.startsWith "otpu_mem_channel_sfifo_"
    let hints : Backend.RegisterHints :=
      if m.name == "otpu_mem_channel_reset_sparkle" then MemChannelReset.hints
      else if m.name == "otpu_mem_channel_accelerator_sparkle" then MemChannelAccelerator.hints
      else if m.name == "otpu_mem_channel_xdma_sparkle" then MemChannelXdma.hints
      else if async then
        (["rgray_w1","rgray_w2","wgray_r1","wgray_r2"].map fun n => (n,[.asyncRegister])) ++
          (if m.wires.any (·.name == "wa_q") then [("wa_q",[.maxFanout 32])] else [])
      else []
    let emitted ← Backend.withRegisterHints m hints false false (if fifo then [("mem",.distributed)] else [])
    result := result ++ emitted.replace " ? " " ?\n        "
  return result

end OpenTPU.MemChannel
