import OpenTPU.Circuit

namespace OpenTPU.Control
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

structure Config where
  depth : Nat := 128
  columns : Nat := 2
  lanes : Nat := 8
  actRows : Nat := 2
  coreKhz : Nat := 100000
  buildId : Nat := 0
  ddrMts : Nat := 0
  traceDepth : Nat := 16384
  pqWindow : Nat := 1024
  hasTemp : Bool := true
  hasI2c : Bool := true
  channelHash : Bool := false
  dstep : Bool := true
  hostCalibration : Bool := false
  deriving Repr

def inputs : List (String × Nat) :=
  [("s_awaddr",12),("s_awvalid",1),("s_wdata",32),("s_wstrb",4),("s_wvalid",1),
   ("s_bready",1),("s_araddr",12),("s_arvalid",1),("s_rready",1),
   ("ld_busy",1),("halted",1),("error",1),("wait_to",1),("icount",32),
   ("wr_idle",1),("axi_err",1),("calib",2),("b_rd",1),("b_wr",1),("a_rd",1),
   ("a_wr",1),("b_wait",1),("temp_v",1),("temp",12),("mxu_busy",1),("mxu_mac",1),
   ("vpu_busy",1),("qnt_busy",1),("dma_busy",1),("tmem_deny",1),("mxu_starve",1),
   ("dram_rd",2),("dram_wr",2),("dram_wait",1),("instr",2),
   ("tr_count",32),("tr_drop",32),("tr_busy",1),("tr_rdata",64),("i2c_in",5)]

def caps (c : Config) : Nat :=
  0xc3000030 + (if c.hostCalibration then 2^27 else 0) +
  (if c.dstep then 2^26+2^6 else 0) + (clog2 c.pqWindow % 256)*2^16 +
  (if c.traceDepth == 0 then 0 else (clog2 c.traceDepth % 256)*2^8+1) +
  (if c.channelHash then 128 else 0) + (if c.ddrMts != 0 then 8 else 0) +
  (if c.hasI2c then 4 else 0) + (if c.hasTemp then 2 else 0)

private def extend (e : Expr) (w total : Nat) : Expr := pack [e,lit 0 (total-w)]

def build (c : Config) : Module := runModule "otpu_ctrl_sparkle" do
  clocks
  for (n,w) in inputs do let _ ← input n w
  let write ← wire "w_go" 1 (band (ref "s_awvalid") (band (ref "s_wvalid") (bnot (ref "s_bvalid"))))
  let select := fun a => band write (eq (slice (ref "s_awaddr") 2 10) (lit a 10))
  let ctrl := select 2
  let data := ref "s_wdata"
  reg "ld_pend_q" 2 true [(lit 1 1,pack [ref "ld_start",bit (ref "ld_pend_q") 0])]
  reg "run" 1 true [(ctrl,bit data 0)]
  reg "ld_start" 1 true [(lit 1 1,band ctrl (band (bit data 1) (band (bnot (bit data 0)) (bnot (ref "run")))))]
  reg "clear" 1 true [(lit 1 1,band ctrl (bit data 2))]
  reg "snap" 1 true [(lit 1 1,select 20)]
  reg "tr_clear" 1 true [(lit 1 1,band (select 128) (bit data 1))]
  reg "s_bvalid" 1 true [(band (ref "s_bvalid") (ref "s_bready"),lit 0 1),(write,lit 1 1)]
  for (n,a) in [("ld_addr",4),("ld_n",5),("scratch",14)] do
    reg n 32 true [(select a,data)]
  reg "tr_en" 1 true [(select 128,bit data 0)]
  reg "tr_stop" 1 true [(select 128,bit data 2)]
  let trInc := band (bit (ref "r_p") 1) (eq (ref "r_a") (lit 133 10))
  reg "tr_addr" 32 true [(trInc,add (ref "tr_addr") (lit 1 32)),(select 131,data)]
  reg "i2c_lo" 4 true [(select 136,slice data 0 4)]
  for i in List.range 8 do reg s!"arg{i}" 32 true [(select (24+i),data)]
  let running := band (ref "run") (bnot (ref "halted"))
  for (n,w,inc) in [("cycles",64,running),("n_brd",32,ref "b_rd"),("n_bwr",32,ref "b_wr"),
      ("n_ard",32,ref "a_rd"),("n_awr",32,ref "a_wr"),("n_bst",32,ref "b_wait")] do
    reg n w true [(inc,add (ref n) (lit 1 w)),(ref "clear",lit 0 w)]
  let increments := [lit 1 2,extend running 1 2] ++
    (["mxu_busy","mxu_mac","vpu_busy","qnt_busy","dma_busy","tmem_deny"].map fun n => extend (ref n) 1 2) ++
    [ref "dram_rd",ref "dram_wr",extend (ref "dram_wait") 1 2,ref "instr",extend (ref "mxu_starve") 1 2]
  for i in List.range 13 do
    reg s!"fr_inc{i}" 2 true [(lit 1 1,increments[i]!)]
    reg s!"fr{i}" 64 true [(lit 1 1,add (ref s!"fr{i}") (extend (ref s!"fr_inc{i}") 2 64))]
    reg s!"fr_s{i}" 64 true [(ref "snap",ref s!"fr{i}")]
  reg "n_snap" 32 true [(ref "snap",add (ref "n_snap") (lit 1 32))]
  let arReady ← wire "ar_ready" 1 (band (bnot (ref "s_rvalid")) (eq (ref "r_p") (lit 0 2)))
  let take := band (ref "s_arvalid") arReady
  reg "r_p" 2 true [(lit 1 1,pack [take,bit (ref "r_p") 0])]
  reg "s_rvalid" 1 true [(band (ref "s_rvalid") (ref "s_rready"),lit 0 1),(bit (ref "r_p") 1,lit 1 1)]
  reg "s_rdata" 32 false [(bit (ref "r_p") 1,ref "r_d")]
  let _ ← clocked "r_a" 10 take (slice (ref "s_araddr") 2 10)
  let ldPending := bor (ref "ld_start") (bnot (eq (ref "ld_pend_q") (lit 0 2)))
  let mut reads := [
    (0,lit 0x4f545055 32),(1,pack [lit c.lanes 8,lit c.columns 8,lit c.depth 16]),
    (2,extend (ref "run") 1 32),
    (3,pack [ref "halted",ref "error",bor (ref "ld_busy") ldPending,ref "wr_idle",ref "axi_err",ref "calib",ref "run",ref "wait_to",lit 0 23]),
    (4,ref "ld_addr"),(5,ref "ld_n"),(6,slice (ref "cycles") 0 32),(7,slice (ref "cycles") 32 32),
    (8,ref "icount"),(9,ref "n_brd"),(10,ref "n_bwr"),(11,ref "n_ard"),(12,ref "n_awr"),
    (13,ref "n_bst"),(14,ref "scratch"),(15,lit 3 32),(16,lit (caps c) 32),
    (17,lit c.coreKhz 32),(18,lit c.buildId 32),(19,pack [ref "temp",lit 0 19,ref "temp_v"]),
    (20,ref "n_snap"),(21,lit c.ddrMts 32),(22,lit c.actRows 32),
    (128,pack [ref "tr_en",lit 0 1,ref "tr_stop",ref "tr_busy",lit 0 28]),
    (129,ref "tr_count"),(130,ref "tr_drop"),(131,ref "tr_addr"),
    (132,slice (ref "tr_rdata") 0 32),(133,slice (ref "tr_rdata") 32 32),
    (136,extend (ref "i2c_lo") 4 32),(137,extend (ref "i2c_in") 5 32)]
  for i in List.range 8 do reads := reads ++ [(24+i,ref s!"arg{i}")]
  for i in List.range 13 do
    reads := reads ++ [(64+2*i,slice (ref s!"fr_s{i}") 0 32),(65+2*i,slice (ref s!"fr_s{i}") 32 32)]
  let read := reads.foldl (fun prev (a,v) => mux (eq (ref "r_a") (lit a 10)) v prev) (lit 0xdeadbeef 32)
  let _ ← clocked "r_d" 32 (lit 1 1) read
  for (n,w) in [("run",1),("ld_start",1),("ld_addr",32),("ld_n",32),("s_bvalid",1),
    ("s_rvalid",1),("s_rdata",32),("tr_en",1),("tr_stop",1),("tr_clear",1),("tr_addr",32),("i2c_lo",4)] do
    addOutput n (.bitVector w)
  output "arg" 256 (pack ((List.range 8).map fun i => ref s!"arg{i}"))
  output "s_awready" 1 write
  output "s_wready" 1 write
  output "s_bresp" 2 (lit 0 2)
  output "s_arready" 1 arReady
  output "s_rresp" 2 (lit 0 2)

end OpenTPU.Control
