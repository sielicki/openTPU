import OpenTPU.QuantRead
import OpenTPU.QuantScale
import OpenTPU.QuantWrite
import OpenTPU.SeqFetch

/-! Complete native quantizer: command/reader control, streaming block RAMs,
    two-pass sequencing, write arbitration, completion and profiling. Arithmetic
    is composed from the independently verified native quantizer pipelines. -/
namespace OpenTPU.Quant
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.SeqLogic

structure Config where
  depth : Nat := 32
  lanes : Nat := 8
  deriving Repr

def Config.validate (c : Config) : Except String Unit := do
  (QuantRead.Config.mk c.lanes).validate
  if c.depth == 0 || c.depth % c.lanes != 0 then
    throw "quantizer requires positive D divisible by LANES"

def Config.chunks (c : Config) := c.depth / c.lanes
def Config.chunkBits (c : Config) := max 1 (clog2 c.chunks)
def Config.readWidth (c : Config) := 118+c.lanes
def Config.writeWidth (c : Config) := 92+c.lanes

private def nz (x : Expr) (width : Nat := 32) := bnot (eq x (lit 0 width))
private def choose (name : String) (index : Expr) (width : Nat := 32) :=
  SeqWindow.select ((List.range 4).map fun i => ref s!"{name}{i}") index 2 width
private def inst (module name : String) (inputs : List (String × Expr))
    (outputs : List (String × Nat × String)) : CircuitM Unit := do
  let mut ports := inputs
  for (port,width,signal) in outputs do
    let m ← getModule
    setModule <| m.addWire {name := signal,ty := .bitVector width}
    ports := ports ++ [(port,ref signal)]
  emitInstance module name ports

private def rfield (c : Config) (m : Expr) (offset width : Nat) := slice m (c.lanes+offset) width

def build (c : Config) : Module := runModule "otpu_quant_sparkle" do
  clocks
  let start ← input "start" 1
  let cmd ← input "cmd" 240
  let en ← input "gnt" 1
  let idle ← input "wr_idle" 1
  let data ← input "t_rdata" (32*c.lanes)
  let col ← input "t_rdata2" (32*c.lanes)
  let row ← input "t_rdata3" 32
  let one := lit 1 1
  let zero := lit 0 1
  let busy := ref "busy"
  let ackw := ref "ackw"
  let strm := ref "strm"
  let pass := ref "pass"
  let isst := ref "is_st"
  let rbuf := slice (ref "gi") 0 2
  let begin ← wire "begin_cmd" 1 (band (bnot ackw) start)
  let active ← wire "active" 1 (every [bnot ackw,bnot start,busy,en])
  let ew ← wire "ew" 32 (mux (band isst pass) (mux (ref "wide") (lit 4) (lit 1)) (lit c.lanes))
  let bstep ← wire "bstep" 32 (mux (ref "wide") (lit 4) (ref "es"))
  let gr ← wire "Gr" 32 (mux pass (ref "GW") (ref "G"))
  let rlast ← wire "rlast" 1 (bnot (lt (add (ref "e") ew) gr))
  let rmask ← wire "rmask" c.lanes (pack ((List.range c.lanes).map fun l =>
    band (lt (lit l) ew) (lt (lit l) (ref "rem"))))
  let riss ← wire "riss" 1 (every [busy,bnot (ref "rd_done"),bnot (ref "rd_wait"),
    bor (bnot strm) (bor (nz (ref "e")) (eq (choose "bst" rbuf 2) (lit 0 2)))])
  let issue ← wire "issue" 1 (band active riss)
  let nextElement ← wire "next_element" 1 (band issue (bnot rlast))
  let reread ← wire "reread" 1 (every [issue,rlast,bnot strm,bnot pass])
  let nextGroup ← wire "next_group" 1 (every [issue,rlast,bor strm pass])
  let groupInRow ← wire "group_in_row" 1 (band (eq (ref "G") (lit c.depth))
    (lt (add (ref "g") (lit 1)) (zext (ref "KB") 16 32)))
  let moreGroup := band nextGroup groupInRow
  let nextRow := band nextGroup (bnot groupInRow)
  let lastGroup ← wire "last_group" 1 (eq (add (ref "gi") (lit 1)) (ref "groups"))
  output "t_ren" c.lanes (mux riss rmask (lit 0 c.lanes))
  output "t_ren2" c.lanes (mux (band riss (ref "csf")) rmask (lit 0 c.lanes))
  output "t_ren3" 1 (band riss (ref "rsf"))
  output "t_raddr" (32*c.lanes) (pack ((List.range c.lanes).map fun l => add (add (ref "grp_src") (ref "e")) (lit l)))
  output "t_raddr2" (32*c.lanes) (pack ((List.range c.lanes).map fun l => add (add (ref "csb") (ref "rel")) (lit l)))
  output "t_raddr3" 32 (add (ref "rsb") (zext (ref "r") 16 32))
  inst "otpu_qread_sparkle" "reader" [("clk",ref "clk"),("en",en),("csf",ref "csf"),("rsf",ref "rsf"),
    ("t_rdata",data),("t_rdata2",col),("t_rdata3",row),("m0",ref "m0"),("badr",ref "badr")]
    [("xp",32*c.lanes,"xp"),("mp",c.readWidth,"mp"),("mp_baddr",32,"mp_baddr"),
     ("cmax",32,"cmax"),("mc",c.readWidth,"mc")]
  let rf := rfield c
  let mp := ref "mp"
  let mc := ref "mc"
  let mcv := rf mc 117 1
  let mcp := rf mc 116 1
  let mcb := rf mc 114 2
  let mclast := rf mc 49 1
  let amx ← wire "amx" 32 (ref "bamax_read")
  let nmax ← wire "nmax" 32 (mux (band (nz (rf mc 82 32)) (lt (slice (ref "cmax") 0 31) (slice amx 0 31))) amx (ref "cmax"))
  let sqiv ← wire "sq_iv" 1 (every [mcv,mclast,bor strm (bnot mcp)])
  inst "otpu_qscale_sparkle" "scaler" [("clk",ref "clk"),("rst",ref "rst"),("en",en),("iv",sqiv),("itag",mcb),("amax",nmax)]
    [("ov",1,"sq_ov"),("otag",2,"sq_otag"),("sc",32,"sq_sc"),("inv",32,"sq_inv")]
  let wgo ← wire "w_go" 1 (every [busy,strm,eq (choose "bst" (ref "wsel") 2) (lit 3 2)])
  let ci := c.chunkBits
  let wa ← wire "sb_wa" (2+ci) (.concat [rf mp 114 2,slice mp (c.lanes+82+clog2 c.lanes) ci])
  let ra ← wire "sb_ra" (2+ci) (.concat [ref "wsel",slice (ref "wc") 0 ci])
  let we ← wire "sb_we" 1 (every [bnot (ref "rst"),active,rf mp 117 1,strm])
  let mut buffered := []
  for l in [:c.lanes] do
    let name := s!"sb_rd{l}"
    let m ← getModule
    setModule <| (m.addWire {name,ty := .bitVector 32}).addStmt
      (.memory s!"sb_mem{l}" (2+ci) 32 "clk" wa (slice (ref "xp") (32*l) 32) we ra name true [] [])
    buffered := buffered ++ [ref name]
  let wend ← wire "write_end" 1 (eq (add (ref "wc") (lit 1)) (lit c.chunks))
  let streamFin := band wend (eq (add (ref "wdone") (lit 1)) (ref "groups"))
  let block ← wire "selected_block" 32 (ref "bblk_read")
  let blockBase ← wire "block_base" 32 (add (zext (ref "ab") 8 32) block)
  let streamIdx ← wire "stream_index" 32 (add (.mul blockBase (lit c.depth)) (.mul (ref "wc") (lit c.lanes)))
  let streamMeta := pack [streamFin,lit 0,zero,slice blockBase 0 16,eq (ref "wc") (lit 0),streamIdx,
    slice (ref "brow_read") 0 8,lit (2^c.lanes-1) c.lanes,one]
  let rel := rf mp 50 32
  let (div,mod) ← SeqFetch.divMod "block_number" rel c.depth
  let mask := lit (2^32-c.lanes)
  let twoPassMeta := pack [rf mp 48 1,ref "mp_baddr",isst,
    add (zext (ref "ab") 8 16) (slice div 0 16),band (bnot isst) (eq mod (lit 0 (max 1 (clog2 c.depth)))),
    band (add (.mul (zext (ref "ab") 8 32) (lit c.depth)) rel) mask,
    rf mp 32 8,slice mp 0 c.lanes,one]
  let twoPass ← wire "two_pass_write" 1 (every [bnot strm,rf mp 117 1,rf mp 116 1])
  let wq ← wire "wq" c.writeWidth (mux wgo streamMeta (mux twoPass twoPassMeta (lit 0 c.writeWidth)))
  let wx ← wire "wx" (32*c.lanes) (mux wgo (pack buffered) (mux twoPass (ref "xp") (lit 0 (32*c.lanes))))
  let winv ← wire "winv" 32 (mux wgo (ref "binv_read") (mux twoPass (ref "inv2") (lit 0)))
  let wsc ← wire "wsc_in" 32 (mux wgo (ref "bsc_read") (mux twoPass (ref "sc2") (lit 0)))
  inst "otpu_qwrite_sparkle" "writer" [("clk",ref "clk"),("rst",ref "rst"),("en",en),
    ("wq",wq),("wx",wx),("winv",winv),("wsc_in",wsc)]
    [("wqd",c.writeWidth,"wqd"),("qb",8*c.lanes,"qb"),("wsc_d",32,"wsc_d")]
  let wd := ref "wqd"
  let writeValid ← wire "write_valid" 1 (every [busy,bnot ackw,bit wd (91+c.lanes)])
  let writeAct := band writeValid (bnot (bit wd 33))
  let writeDram := band writeValid (bit wd 33)
  let writeScale ← wire "st_scale_w" 1 (every [busy,bnot ackw,isst,ref "sq_ov"])
  let byteAddr := slice wd 1 32
  output "a_want" 1 (bor writeDram writeScale)
  output "a_req" 1 (band en (bor writeDram writeScale))
  output "a_we" 1 (band en (bor writeDram writeScale))
  output "a_addr" 32 (mux writeScale (.op .shr [ref "saddr",lit 2]) (mux writeDram (.op .shr [byteAddr,lit 2]) (lit 0)))
  output "a_wdata" 32 (mux writeScale (ref "sq_sc") (mux writeDram
    (mux (bit wd 92) (slice (ref "qb") 0 32) (.concat (List.replicate 4 (slice (ref "qb") 0 8)))) (lit 0)))
  output "a_be" 4 (mux writeScale (lit 15 4) (mux writeDram (mux (bit wd 92) (lit 15 4)
    (.op .shl [lit 1 4,slice byteAddr 0 2])) (lit 0 4)))
  output "act_dup" 1 (ref "dup")
  output "act_off" 8 (slice (ref "rows") 0 8)
  output "act_we" c.lanes (mux (every [en,writeAct,bit wd 91]) (lit (2^c.lanes-1) c.lanes) (lit 0 c.lanes))
  output "act_row" 8 (mux writeAct (slice wd 83 8) (lit 0 8))
  output "act_idx" 32 (mux writeAct (band (slice wd 51 32) mask) (lit 0))
  output "act_data" (8*c.lanes) (mux writeAct (ref "qb") (lit 0 (8*c.lanes)))
  let ascale := band writeAct (bit wd 50)
  output "asc_we" 1 (band en ascale)
  output "asc_row" 8 (mux ascale (slice wd 83 8) (lit 0 8))
  output "asc_blk" 16 (mux ascale (slice wd 34 16) (lit 0 16))
  output "asc_data" 32 (mux ascale (ref "wsc_d") (lit 0))
  -- Control registers. reg suppresses all updates during reset unless it owns
  -- a synchronous reset; the profiler and done pulses are clocked separately.
  let qst := eq (slice cmd 232 8) (lit 0x22 8)
  let flag := fun i => bit cmd (224+i)
  let cw := word cmd
  let rows ← wire "command_rows" 16 (mux qst (slice (cw 4) 0 16) (zext (slice (cw 2) 0 8) 8 16))
  let kb ← wire "command_blocks" 16 (mux qst (slice (cw 4) 16 16) (slice (cw 2) 16 16))
  let groupSize ← wire "command_group_size" 32 (mux (flag 0) (.mul (zext kb 16 32) (lit c.depth)) (lit c.depth))
  let gw ← wire "command_write_size" 32 (mux (every [qst,flag 0,flag 1]) (.op .shr [groupSize,lit 1]) groupSize)
  let empty ← wire "empty_cmd" 1 (bor (eq rows (lit 0 16)) (eq kb (lit 0 16)))
  let scAvailable := every [active,ref "sq_ov",bnot strm]
  let fin ← wire "finish" 1 (every [active,bit wd (91+c.lanes),bit wd 0])
  let actFin := band fin (bnot isst)
  let ackFin := band ackw idle
  reg "busy" 1 true [(ackFin,zero),(band begin (bnot empty),one),(actFin,zero)]
  reg "ackw" 1 true [(ackFin,zero),(band fin isst,one)]
  let issued := pack [rmask,ref "g",ref "r",band rlast lastGroup,rlast,ref "rel",ref "e",rbuf,pass,one]
  reg "m0" c.readWidth true [(ackw,lit 0 c.readWidth),(begin,lit 0 c.readWidth),
    (active,mux riss issued (lit 0 c.readWidth))]
  for (name,width,value) in [("is_st",1,qst),("rowm",1,flag 0),("csf",1,band (bnot qst) (flag 1)),
      ("rsf",1,band (bnot qst) (flag 2)),("strm",1,band (bnot qst) (bnot (flag 0))),
      ("dup",1,band (bnot qst) (flag 3)),("csb",32,cw 4),("rsb",32,cw 5),
      ("rows",16,rows),("KB",16,kb),("srs",32,mux qst (cw 5) (cw 3)),
      ("G",32,groupSize),("GW",32,gw),
      ("groups",32,mux qst
        (.mul (zext (slice (cw 4) 0 16) 16 32)
          (mux (flag 0) (lit 1) (zext (slice (cw 4) 16 16) 16 32)))
        (.mul (zext (slice (cw 2) 0 8) 8 32)
          (mux (flag 0) (lit 1) (zext (slice (cw 2) 16 16) 16 32))))] do
    reg name width false [(begin,value)]
  for (name,value) in [("sdst",cw 3),("drs",cw 6),("es",cw 7)] do
    reg name 32 false [(band begin qst,value)]
  reg "ab" 8 false [(band begin (bnot qst),slice (cw 2) 8 8)]
  reg "r" 16 false [(begin,lit 0 16),(nextRow,add (ref "r") (lit 1 16))]
  reg "g" 32 false [(begin,lit 0),(moreGroup,add (ref "g") (lit 1)),(nextRow,lit 0)]
  reg "e" 32 false [(begin,lit 0),(nextElement,add (ref "e") ew),(bor reread nextGroup,lit 0)]
  reg "gi" 32 false [(begin,lit 0),(nextGroup,add (ref "gi") (lit 1))]
  reg "rel" 32 false [(begin,lit 0),(nextElement,add (ref "rel") ew),(reread,sub (ref "rel") (ref "e")),
    (moreGroup,add (ref "rel") ew),(nextRow,lit 0)]
  reg "rem" 32 false [(begin,groupSize),(nextElement,sub (ref "rem") ew),
    (bor reread nextGroup,ref "G"),(scAvailable,ref "GW")]
  reg "pass" 1 false [(begin,zero),(nextGroup,zero),(scAvailable,one)]
  reg "wide" 1 false [(begin,zero),(reread,every [isst,eq (ref "es") (lit 1),eq (slice (ref "bgrp") 0 2) (lit 0 2)]),(nextGroup,zero)]
  reg "rd_wait" 1 false [(begin,zero),(reread,one),(scAvailable,zero)]
  reg "rd_done" 1 false [(begin,empty),(band nextGroup lastGroup,one)]
  reg "row_src" 32 false [(begin,cw 1),(nextRow,add (ref "row_src") (ref "srs"))]
  reg "grp_src" 32 false [(begin,cw 1),(moreGroup,add (ref "grp_src") (lit c.depth)),(nextRow,add (ref "row_src") (ref "srs"))]
  reg "badr" 32 false [(begin,cw 2),(bor nextElement moreGroup,add (ref "badr") bstep),
    (reread,ref "bgrp"),(nextRow,add (ref "brs") (ref "drs"))]
  reg "bgrp" 32 false [(begin,cw 2),(moreGroup,add (ref "badr") bstep),(nextRow,add (ref "brs") (ref "drs"))]
  reg "brs" 32 false [(begin,cw 2),(nextRow,add (ref "brs") (ref "drs"))]
  reg "saddr" 32 false [(begin,cw 3),(band scAvailable isst,add (ref "saddr") (lit 4))]
  reg "sc2" 32 false [(scAvailable,ref "sq_sc")]
  reg "inv2" 32 false [(scAvailable,ref "sq_inv")]
  let wrote := band active wgo
  let finishedBuffer := band wrote wend
  reg "wsel" 2 false [(begin,lit 0 2),(finishedBuffer,add (ref "wsel") (lit 1 2))]
  reg "wc" 32 false [(begin,lit 0),(wrote,mux wend (lit 0) (add (ref "wc") (lit 1)))]
  reg "wdone" 32 false [(begin,lit 0),(finishedBuffer,add (ref "wdone") (lit 1))]
  for b in [:4] do
    let first := every [issue,strm,eq (ref "e") (lit 0),eq rbuf (lit b 2)]
    let full := every [active,mcv,strm,mclast,eq mcb (lit b 2)]
    let scaled := every [active,ref "sq_ov",strm,eq (ref "sq_otag") (lit b 2)]
    let freed := band finishedBuffer (eq (ref "wsel") (lit b 2))
    reg s!"bst{b}" 2 false [(begin,lit 0 2),(first,lit 1 2),(full,lit 2 2),(scaled,lit 3 2),(freed,lit 0 2)]
  -- Metadata arrays each have one indexed write port and one asynchronous
  -- read port. Retaining memory structure matches the RTL's distributed RAM.
  let first := every [bnot (ref "rst"),issue,strm,eq (ref "e") (lit 0)]
  let maximum := every [bnot (ref "rst"),active,mcv,bor strm (bnot mcp)]
  let scaled := every [bnot (ref "rst"),active,ref "sq_ov",strm]
  for (name,width,address,value,enable,readAddress) in [
      ("brow",16,rbuf,ref "r",first,ref "wsel"),
      ("bblk",32,rbuf,ref "g",first,ref "wsel"),
      ("bamax",32,mcb,nmax,maximum,mcb),
      ("bsc",32,ref "sq_otag",ref "sq_sc",scaled,ref "wsel"),
      ("binv",32,ref "sq_otag",ref "sq_inv",scaled,ref "wsel")] do
    let m ← getModule
    setModule <| (m.addWire {name := s!"{name}_read",ty := .bitVector width}).addStmt
      (.memory s!"{name}_mem" 2 width "clk" address value enable readAddress s!"{name}_read" true [] [])
  let _ ← clocked "st_c" 1 one (band busy (bnot en))
  let freeze ← wire "freeze_count" 32 (add (ref "st_frz") (zext (ref "st_c") 1 32))
  let _ ← clocked "st_frz" 32 one (mux (band (bnot (ref "rst")) begin) (lit 0) freeze)
  let _ ← clocked "done_w" 1 one (every [bnot (ref "rst"),bor ackFin (bor (band begin empty) actFin)])
  let done ← clocked "done_q" 1 one (band (bnot (ref "rst")) (ref "done_w"))
  let pf ← clocked "pf_u_q" 1 one (band (bnot (ref "rst")) actFin)
  reg "pf_frz_q" 32 false [(actFin,freeze)]
  output "rdy" 1 (bnot busy)
  output "done" 1 done
  output "pf_u" 1 pf
  output "pf_frz" 32 (ref "pf_frz_q")

def toVerilog (c : Config) : Except String String := do
  c.validate
  let core ← Backend.withRegisterHints (build c) []
  return core ++ (← QuantRead.toVerilog ⟨c.lanes⟩) ++
    (← QuantScale.toVerilog ⟨2,4,2⟩) ++ (← QuantWrite.toVerilog ⟨c.lanes⟩)

def wrapper (c : Config) : String := s!"
module otpu_quant import otpu_pkg::*; #(
  parameter int D={c.depth}, LANES={c.lanes}, SID=0
)(
  input logic clk,rst,start,
  input cmd_t cmd,
  output logic rdy,done,
  input logic gnt,
  output logic [LANES-1:0] t_ren,t_ren2,
  output logic [LANES-1:0][31:0] t_raddr,t_raddr2,
  input logic [LANES-1:0][31:0] t_rdata,t_rdata2,
  output logic t_ren3,
  output logic [31:0] t_raddr3,
  input logic [31:0] t_rdata3,
  output logic [LANES-1:0] act_we,
  output logic [7:0] act_row,
  output logic [31:0] act_idx,
  output logic [LANES-1:0][7:0] act_data,
  output logic act_dup,
  output logic [7:0] act_off,
  output logic asc_we,
  output logic [7:0] asc_row,
  output logic [15:0] asc_blk,
  output logic [31:0] asc_data,
  output logic a_want,
  input logic wr_idle,
  output logic a_req,a_we,
  output logic [31:0] a_addr,a_wdata,
  output logic [3:0] a_be,
  output logic pf_u,
  output logic [31:0] pf_frz
);
  initial if(D!={c.depth} || LANES!={c.lanes})
    $fatal(1, \"Sparkle quantizer configuration mismatch; regenerate\");
  otpu_quant_sparkle impl(.clk,.rst,.start,.cmd,.rdy,.done,.gnt,
    .t_ren,.t_raddr,.t_rdata,.t_ren2,.t_raddr2,.t_rdata2,.t_ren3,.t_raddr3,.t_rdata3,
    .act_we,.act_row,.act_idx,.act_data,.act_dup,.act_off,
    .asc_we,.asc_row,.asc_blk,.asc_data,
    .a_want,.wr_idle,.a_req,.a_we,.a_addr,.a_wdata,.a_be,.pf_u,.pf_frz);
`ifndef SYNTHESIS
  bit rem_rst=0;
  always @(posedge clk) begin
    if(rst) rem_rst<=1'b1;
    if(!rst && rem_rst && impl.busy && impl.rem != impl._gen_Gr - impl.e)
      $fatal(1, \"otpu_quant: remaining-element counter mismatch\");
    if(!rst && impl.busy && !impl.ackw && impl.wqd[91+LANES] && !impl.wqd[33]
       && (impl.wqd[91+:LANES] != '1 || (impl.wqd[51+:32] & 32'(LANES-1)) != 0))
      $fatal(1, \"otpu_quant: QACT write not a whole LANES-aligned chunk\");
  end
`endif
endmodule
"

end OpenTPU.Quant
