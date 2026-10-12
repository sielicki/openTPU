import OpenTPU.VpuCommand

namespace OpenTPU.VpuSequence
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.SeqLogic
abbrev Config := VpuIssue.Config

def stateWidths (c : Config) : List (String × Nat) :=
  [("issuing",1),("red_act",1),("filling",1),("flushing",1),("ew_n",7),("last_tap",4),
   ("tag",8),("dst",20),("a",20),("b",20),("rows",16),("cols",16),("drs",16),("ars",16),("brs",16),
   ("func",8),("bmode",2),("imm",32),("nslots",4),("nch",16),("ir",16),("ic",16),("ch",16),
   ("a_row",20),("b_row",20),("d_row",20),("nfill",16),("oc_a",20),("od_a",20),("od_sc",1),("od_one",1),
   ("wr_row",20),("rows_done",16),("rdb",1),("fl",16),("mx_have",1),("mx_run",32),("mx_ri",17),
   ("done_i",1),("pf_u",1),("st_c",1),("st_frz",32),("pf_frz",32),("mi",102+c.lanes+clog2 (256/c.lanes))]

/-- Main VPU issue/reduction sequencer. Datapath completion signals and decoded
    queue/issue signals are explicit ports for composition and transition proofs. -/
def build (c : Config) : Except String Module := do
  if !powerOfTwo c.lanes || c.lanes > 16 then throw "VPU sequence requires power-of-two LANES <= 16"
  return runModule "otpu_vpu_sequence_sparkle" do
    clocks
    for (n,w) in [("en",1),("hc",240),("can_begin",1),("h_empty",1),("hf",8),("nchunks",16),
      ("busy",1),("iss_ok",1),("imask",c.lanes),("iwid",16),("irow_last",1),("iall_last",1),
      ("mo_v",1),("mo_all_last",1),("mxm_v",1),("mxm_tag",8),("mxm_row_last",1),("mxm_all_last",1),
      ("mx_new",32),("mx_ni",17),("am4_v",1),("am4_l",1),("root_v",1)] do
      let _ ← input n w
    let all := every
    let f := ref "func"
    let isF := fun code => eq f (lit code 8)
    let sum := bor (bor (isF 16) (isF 18)) (isF 19)
    let am := isF 20
    let mx := bor (isF 17) am
    let red := bor sum mx
    let begin := all [ref "can_begin",ref "en"]
    let start := band begin (bnot (ref "h_empty"))
    let hred := VpuDecode.isReduction (ref "hf")
    let startRed := band start hred
    let startEw := band start (bnot hred)
    let outer := eq (ref "hf") (lit 6 8)
    let fill := all [ref "en",ref "issuing",ref "filling"]
    let issue := all [ref "en",ref "issuing",bnot (ref "filling"),ref "iss_ok"]
    let fillEnd := eq (add (zext (ref "ch") 16 32) (lit 1)) (zext (ref "nfill") 16 32)
    let rowEnd := band issue (ref "irow_last")
    let allEnd := eq (add (zext (ref "ir") 16 32) (lit 1)) (zext (ref "rows") 16 32)
    let mxStep := all [ref "en",ref "red_act",mx,ref "mxm_v",eq (ref "mxm_tag") (ref "tag")]
    let sumStep := all [ref "en",ref "red_act",sum,ref "root_v"]
    let sumEnd := eq (add (zext (ref "rows_done") 16 32) (lit 1)) (zext (ref "rows") 16 32)
    let flush := band (ref "en") (ref "flushing")
    let flushEnd := bnot (lt (add (zext (ref "fl") 16 32) (lit c.lanes)) (zext (ref "rows") 16 32))
    let fin := [all [mxStep,ref "mxm_all_last",bnot am],
      all [ref "en",ref "red_act",am,ref "am4_v",ref "am4_l"],
      all [sumStep,sumEnd,bnot (ref "rdb")],band flush flushEnd].foldl bor (lit 0 1)
    let ewfin := all [ref "en",ref "mo_v",ref "mo_all_last"]
    let complete := bor fin ewfin
    let word := fun n => slice (ref "hc") ((7-n)*32) 32
    let field := fun n lo w => slice (word n) lo w
    reg "issuing" 1 true [(start,lit 1 1),(band rowEnd allEnd,lit 0 1)]
    reg "red_act" 1 true [(startRed,lit 1 1),(fin,lit 0 1)]
    reg "filling" 1 true [(start,outer),(band fill fillEnd,lit 0 1)]
    reg "flushing" 1 true [(all [sumStep,sumEnd,ref "rdb"],lit 1 1),(band flush flushEnd,lit 0 1)]
    let ewn := mux startEw (add (ref "ew_n") (lit 1 7)) (ref "ew_n")
    reg "ew_n" 7 true [(lit 1 1,mux ewfin (sub ewn (lit 1 7)) ewn)]
    reg "last_tap" 4 true [(startEw,VpuDecode.slotCount (ref "hf"))]
    reg "tag" 8 true [(start,add (ref "tag") (lit 1 8))]
    for (n,v) in [("dst",field 1 0 20),("a",field 2 0 20),("b",field 3 0 20),
      ("oc_a",field 7 0 20),("od_a",field 2 0 20)] do reg n 20 false [(start,v)]
    for (n,v) in [("rows",field 4 0 16),("cols",field 4 16 16),("drs",field 5 0 16),
      ("ars",mux outer (field 5 0 16) (field 5 16 16)),("brs",field 6 0 16),
      ("nch",ref "nchunks"),("nfill",mux (lt (ref "nchunks") (lit 2 16)) (lit 2 16) (ref "nchunks"))] do
      reg n 16 false [(start,v)]
    for (n,w,v) in [("func",8,ref "hf"),("bmode",2,field 6 24 2),("imm",32,word 7),
      ("nslots",4,VpuDecode.slotCount (ref "hf")),("od_sc",1,bit (ref "hc") 224),("od_one",1,bit (ref "hc") 225)] do
      reg n w false [(start,v)]
    reg "ir" 16 false [(start,lit 0 16),(band rowEnd (bnot allEnd),add (ref "ir") (lit 1 16))]
    reg "ic" 16 false [(start,lit 0 16),(fill,mux fillEnd (lit 0 16) (add (ref "ic") (lit c.lanes 16))),
      (issue,mux (ref "irow_last") (lit 0 16) (add (ref "ic") (ref "iwid")))]
    reg "ch" 16 false [(start,lit 0 16),(fill,mux fillEnd (lit 0 16) (add (ref "ch") (lit 1 16))),
      (issue,mux (ref "irow_last") (lit 0 16) (add (ref "ch") (lit 1 16)))]
    for (n,v,stride) in [("a_row",mux outer (field 1 0 20) (field 2 0 20),"ars"),
      ("b_row",field 3 0 20,"brs"),("d_row",field 1 0 20,"drs")] do
      reg n 20 false [(start,v),(rowEnd,add (ref n) (zext (ref stride) 16 20))]
    reg "wr_row" 20 false [(startRed,field 1 0 20),(sumStep,add (ref "wr_row") (zext (ref "drs") 16 20))]
    reg "rows_done" 16 false [(startRed,lit 0 16),(sumStep,add (ref "rows_done") (lit 1 16))]
    reg "rdb" 1 false [(startRed,all [eq (ref "hf") (lit 19 8),bnot (lt (lit 256 16) (field 4 0 16)),eq (field 5 0 16) (lit 1 16)])]
    reg "fl" 16 false [(startRed,lit 0 16),(flush,add (ref "fl") (lit c.lanes 16))]
    reg "mx_have" 1 false [(startRed,lit 0 1),(mxStep,bnot (ref "mxm_row_last"))]
    reg "mx_run" 32 false [(band mxStep (bnot (ref "mxm_row_last")),ref "mx_new")]
    reg "mx_ri" 17 false [(band mxStep (bnot (ref "mxm_row_last")),ref "mx_ni")]
    let noRst := bnot (ref "rst")
    let _ ← clocked "done_i" 1 (lit 1 1) (band noRst (bor (band begin (ref "h_empty")) complete))
    let _ ← clocked "pf_u" 1 (lit 1 1) (band noRst complete)
    let _ ← clocked "st_c" 1 (lit 1 1) (band (ref "busy") (bnot (ref "en")))
    let count := add (ref "st_frz") (zext (ref "st_c") 1 32)
    let _ ← clocked "st_frz" 32 (lit 1 1) (mux (band noRst start) (lit 0) count)
    reg "pf_frz" 32 false [(complete,count)]
    let cbw := clog2 (256/c.lanes)
    let rl := 64/c.lanes
    let issuedMeta := Expr.concat [lit 1 1,ref "tag",f,ref "bmode",ref "imm",ref "imask",
      mux red (ref "d_row") (add (ref "d_row") (zext (ref "ic") 16 20)),
      ref "irow_last",ref "iall_last",lt (ref "ch") (lit rl 16),
      bnot (lt (slice (add (ref "ch") (lit rl 16)) 0 16) (ref "nch")),
      zext (slice (ref "ch") 0 (clog2 rl)) (clog2 rl) 8,isF 18,isF 19,lit 0 1,
      slice (ref "ch") 0 cbw,ref "ic"]
    let mw := 102+c.lanes+cbw
    let fillMeta := pack [lit 0 16,slice (ref "ch") 0 cbw,lit 1 1,lit 0 (mw-17-cbw)]
    reg "mi" mw true [(ref "en",mux fill fillMeta (mux issue issuedMeta (lit 0 mw)))]
    for (n,w) in stateWidths c do output s!"o_{n}" w (ref n)

end OpenTPU.VpuSequence
