import OpenTPU.Circuit

/-! Two-channel native DRAM adapter. This is a native Sparkle circuit: queues,
hazard buckets, gather buffers, prefetch runs and command/data handshakes are
elaborated directly as gates, registers and RAM, without an HDL import path. -/
namespace OpenTPU.NativeDram
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit
structure Config where
  depth : Nat := 128
  queueDepth : Nat := 16
  writeQueueDepth : Nat := 32
  channelHash : Bool := true
  gather : Nat := 4
  readDepth : Nat := 128
  aDepth : Nat := 64
  prefetch : Nat := 32
  deriving Repr

def Config.validate (c : Config) : Except String Unit := do
  if c.depth != 128 then throw "native DRAM: D must be 128"
  for (name,n) in [("QD",c.queueDepth),("WQD",c.writeQueueDepth),("RD",c.readDepth),("AD",c.aDepth)] do
    if !powerOfTwo n || n < 2 then throw s!"native DRAM: {name} must be a power of two >= 2"
  if c.prefetch < 1 || c.prefetch > 64 || c.aDepth < 2*c.prefetch-1 then
    throw "native DRAM: APF must be 1..64 and AD >= 2*APF-1"

private def all (xs : List Expr) := xs.foldl band (lit 1 1)
private def any (xs : List Expr) := xs.foldl bor (lit 0 1)
private def nz (e : Expr) (w : Nat) := bnot (eq e (lit 0 w))
private def xor (a b : Expr) := Expr.op .xor [a,b]
private def ext (e : Expr) (sourceWidth targetWidth : Nat) := if sourceWidth < targetWidth then Expr.concat [lit 0 (targetWidth-sourceWidth),e] else slice e 0 targetWidth
private def sel (v idx : Expr) (w : Nat) := slice (.op .shr [v, .op .mul [idx,lit w 32]]) 0 w
private def inc (v : Expr) (w : Nat) := slice (add v (lit 1 w)) 0 w
private def updn (v i d : Expr) (w : Nat) := mux (eq i d) v (mux i (inc v w) (sub v (lit 1 w)))
private def choose (i : Expr) (a b : Expr) := mux i b a
private def rr (n : String) (c : Nat) := ref s!"{n}{c}"
private def hash (v : Expr) := [slice v 0 6,slice v 6 6,slice v 12 6,slice v 18 6,ext (bit v 24) 1 6].foldl xor (lit 0 6)
private def parity (v : Expr) (lo hi : Nat) := (List.range (hi-lo)).foldl (fun a k => xor a (bit v (lo+k))) (lit 0 1)
private def setReg (name : String) (w : Nat) (reset : Bool) (updates : List (Expr × Expr)) : CircuitM Unit :=
  reg name w reset updates
private def unreset (name : String) (w : Nat) (updates : List (Expr × Expr)) : CircuitM Unit := do
  let v := updates.foldl (fun q (en,d) => mux en d q) (ref name)
  let _ ← clocked name w (lit 1 1) v
private def namedWire (name : String) (width : Nat) (value : Expr) : CircuitM Expr := do
  let m ← getModule
  setModule <| (m.addWire {name, ty := .bitVector width}).addStmt (.assign name value)
  return ref name
private def ram (name : String) (aw dw : Nat) (wa wd we ra : Expr)
    (rd : String) (extra : List (Expr × String) := []) : CircuitM Unit := do
  let mut m ← getModule
  for n in rd :: extra.map (·.2) do m := m.addWire {name := n, ty := .bitVector dw}
  setModule <| m.addStmt (.memory name aw dw "clk" wa wd we ra rd true [] extra)

def build (p : Config) : Module := runModule "otpu_native_dram_sparkle" do
  clocks
  for (n,w) in [("a_flush",1),("a_req_x",1),("a_we_x",1),("a_addr_x",32),
      ("a_wdata_x",32),("a_be_x",4),("sw_req",1),("sw_addr",32),("sw_wdata",32),("sw_be",4),
      ("b_req",1),("b_tag",1),("b_we",1),("b_wmask",32),("b_wdata",1024),("b_addr",32),("b_par",1),
      ("n_cready",2),("n_wready",2),("n_rvalid",2),("n_rdata",1024),("n_wdone",32)] do
    let _ ← input n w
  let qw := clog2 p.queueDepth
  let ww := clog2 p.writeQueueDepth
  let rw := clog2 p.readDepth
  let aw := clog2 p.aDepth
  let rnw := max 1 (clog2 p.prefetch)
  let od := 2*p.readDepth
  let ow := clog2 od
  let tw := clog2 (p.readDepth+p.aDepth+p.writeQueueDepth)
  let pw := clog2 (4*p.queueDepth+2*p.writeQueueDepth+1)
  let one := lit 1 1
  let zero := lit 0 1
  let chan := fun a => xor (bit a 4) (if p.channelHash then parity a 5 32 else zero)
  let ardy ← wire "a_rdy" 1 (all [lt (rr "qa_n" 0) (lit p.queueDepth (qw+1)),
    lt (rr "qa_n" 1) (lit p.queueDepth (qw+1)),lt (ref "ao_n") (lit od (ow+1))])
  let ardyx ← wire "a_ready_x" 1 (bor (bnot (ref "a_v")) ardy)
  output "a_rdy_x" 1 ardyx
  let brdy ← wire "b_ready" 1 (all [lt (rr "qb_n" 0) (lit p.queueDepth (qw+1)),
    lt (rr "qb_n" 1) (lit p.queueDepth (qw+1)),lt (ref "bt_n") (lit od (ow+1))])
  output "b_rdy" 1 brdy
  let swrdy ← wire "sw_ready" 1 (all [lt (rr "qw_n" 0) (lit p.writeQueueDepth (ww+1)),
    lt (rr "qw_n" 1) (lit p.writeQueueDepth (ww+1))])
  output "sw_rdy" 1 swrdy
  setReg "a_v" 1 true [(ardy,zero),(band (ref "a_req_x") ardyx,one)]
  for (n,w) in [("a_we",1),("a_addr",32),("a_wdata",32),("a_be",4)] do
    unreset n w [(band (ref "a_req_x") ardyx,ref (n++"_x"))]
  let atake ← wire "a_take" 1 (band (ref "a_v") ardy)
  let btake ← wire "b_take" 1 (band (ref "b_req") brdy)
  let swtake ← wire "sw_take" 1 (band (ref "sw_req") swrdy)
  let ach ← wire "a_ch" 1 (chan (ref "a_addr"))
  let swch ← wire "sw_ch" 1 (chan (ref "sw_addr"))
  let swm := slice (ref "sw_addr") 5 25
  let acb := slice (ref "a_addr") 5 25
  let abeat := slice (ref "a_addr") 4 26
  let bsw ← wire "b_sw" 1 (if p.channelHash then ref "b_par" else zero)
  let areuse ← wire "a_reuse" 1 (all [bnot (ref "a_we"),ref "al_v",eq (ref "al_beat") abeat])
  let ahit ← wire "a_hit" 1 (all [bnot (ref "a_we"),bnot areuse,
    choose ach (rr "pv" 0) (rr "pv" 1),eq acb (choose ach (rr "pnx" 0) (rr "pnx" 1)),
    nz (choose ach (rr "pfl" 0) (rr "pfl" 1)) rnw])
  let bpush := band btake (bnot (ref "b_we"))
  let apush := band atake (bnot (ref "a_we"))
  let aoc := bit (ref "aoh") (rnw+5)
  let aoidx := slice (ref "aoh") (rnw+1) 4
  let aoreuse := bit (ref "aoh") rnw
  let aodrop := slice (ref "aoh") 0 rnw
  let aoin ← wire "ao_in" (rnw+6) (.concat [ach,slice (ref "a_addr") 0 4,areuse,
    mux (bor areuse ahit) (lit 0 rnw) (choose ach (rr "pfl" 0) (rr "pfl" 1))])
  let bout ← wire "b_out" 1 (all [nz (ref "bt_n") (ow+1),nz (rr "rb_n" 0) (rw+1),nz (rr "rb_n" 1) (rw+1)])
  let aout ← wire "a_out" 1 (band (nz (ref "ao_n") (ow+1)) (bor aoreuse
    (lt (ext aodrop rnw (aw+1)) (choose aoc (rr "ra_n" 0) (rr "ra_n" 1)))))
  ram "bt_q" ow 2 (slice (add (ref "bt_h") (ref "bt_n")) 0 ow) (.concat [bsw,ref "b_tag"])
    (bnot (bit (ref "bt_n") ow)) (ref "bt_h") "bth"
  ram "ao_q" ow (rnw+6) (slice (add (ref "ao_h") (ref "ao_n")) 0 ow) aoin apush
    (inc (ref "ao_h") ow) "ao_nx1"
  unreset "aoh" (rnw+6) [(eq (ref "ao_n") (lit 0 (ow+1)),aoin),
    (aout,mux (eq (ref "ao_n") (lit 1 (ow+1))) aoin (ref "ao_nx1"))]
  let asrc ← wire "a_src" 512 (mux aoreuse (ref "a_last") (choose aoc (rr "ra_head" 0) (rr "ra_head" 1)))
  let _ ← clocked "a_valid" 1 one (band (bnot (ref "rst")) aout)
  let _ ← clocked "a_data" 32 one (sel asrc aoidx 32)
  let _ ← clocked "a_data2" 32 one (sel asrc (xor aoidx (lit 1 4)) 32)
  output "a_rvalid" 1 (ref "a_valid")
  output "a_rdata" 32 (ref "a_data")
  output "a_rdata2" 32 (ref "a_data2")
  output "b_rvalid" 1 bout
  output "b_rtag" 1 (bit (ref "bth") 0)
  output "b_rdata" 1024 (mux (bit (ref "bth") 1) (.concat [rr "rb_head" 0,rr "rb_head" 1])
    (.concat [rr "rb_head" 1,rr "rb_head" 0]))
  setReg "bt_h" ow true [(bout,inc (ref "bt_h") ow)]
  setReg "ao_h" ow true [(aout,inc (ref "ao_h") ow)]
  setReg "bt_n" (ow+1) true [(one,updn (ref "bt_n") bpush bout (ow+1))]
  setReg "ao_n" (ow+1) true [(one,updn (ref "ao_n") apush aout (ow+1))]
  setReg "a_last" 512 false [(band aout (bnot aoreuse),choose aoc (rr "ra_head" 0) (rr "ra_head" 1))]
  let dropReuse := any [band atake (ref "a_we"),rr "wk_a" 0,rr "wk_a" 1]
  setReg "al_v" 1 true [(apush,one),(bor dropReuse (ref "a_flush"),zero)]
  setReg "al_beat" 26 false [(band apush (bnot dropReuse),abeat)]
  setReg "al_c" 1 false [(band apush (bnot dropReuse),ach)]
  let wacc := pack [all [btake,ref "b_we",nz (slice (ref "b_wmask") 0 16) 16],
    all [btake,ref "b_we",nz (slice (ref "b_wmask") 16 16) 16],band atake (ref "a_we"),rr "qw_push" 0,rr "qw_push" 1]
  setReg "wacc_q" 5 true [(one,wacc)]
  let wqn := (List.range 5).foldl (fun q k => add q (ext (bit (ref "wacc_q") k) 1 pw)) (ref "wq_n")
  setReg "wq_n" pw true [(one,sub (sub wqn (ext (rr "wiss" 0) 1 pw)) (ext (rr "wiss" 1) 1 pw))]
  output "wr_idle" 1 (all [eq (ref "wq_n") (lit 0 pw),eq (ref "wacc_q") (lit 0 5),
    bnot (rr "gv" 0),bnot (rr "gv" 1),bnot (band (ref "a_v") (ref "a_we")),
    eq (rr "iss_w" 0) (slice (ref "n_wdone") 0 16),eq (rr "iss_w" 1) (slice (ref "n_wdone") 16 16)])
  unreset "gw_word" 4 [(one,slice (ref "sw_addr") 0 4)]
  unreset "gw_be" 4 [(one,ref "sw_be")]
  for c in [:2] do
    let r := fun n => rr n c
    let w := fun n width value => namedWire s!"{n}{c}" width value
    let sr := fun n width reset updates => setReg s!"{n}{c}" width reset updates
    let ur := fun n width updates => unreset s!"{n}{c}" width updates
    let swThis := band swtake (eq swch (lit c 1))
    let aThis := eq ach (lit c 1)
    let same := band (r "gv") (eq (r "gb_m") swm)
    let half := xor (lit c 1) bsw
    let qbp ← w "qb_push" 1 (band btake (bor (bnot (ref "b_we"))
      (nz (choose half (slice (ref "b_wmask") 0 16) (slice (ref "b_wmask") 16 16)) 16)))
    let qap ← w "qa_push" 1 (all [atake,aThis,bnot areuse,bnot ahit])
    let qwp ← w "qw_push" 1 (band (r "gv") (mux swThis (bnot (eq (r "gb_m") swm))
      (band (lt (r "qw_n") (lit p.writeQueueDepth (ww+1)))
        (bor (eq (r "gb_strb") (lit (2^64-1) 64)) (bnot (lt (r "gage") (lit (p.gather%8) 3)))))))
    let qbe := .concat [ref "b_we",slice (ref "b_addr") 5 25,
      choose half (slice (ref "b_wdata") 0 512) (slice (ref "b_wdata") 512 512),
      mux (ref "b_we") (choose half (slice (ref "b_wmask") 0 16) (slice (ref "b_wmask") 16 16)) (lit 0 16)]
    let qae := .concat [ref "a_we",acb,slice (ref "a_addr") 0 4,ref "a_wdata",ref "a_be"]
    let qwt := slice (add (r "qw_f") (r "qw_n")) 0 ww
    let room := bnot (bit (r "qw_n") ww)
    ram s!"qbm{c}" (qw+1) 554 (add (r "qb_h") (r "qb_n")) qbe one (r "qb_h") s!"hb{c}"
    ram s!"qam{c}" qw 66 (slice (add (r "qa_h") (r "qa_n")) 0 qw) qae qap (r "qa_h") s!"ha{c}"
    ram s!"qwm{c}" ww 89 qwt (.concat [r "gb_m",r "gb_strb"]) room (r "qw_f") s!"hs{c}"
    ram s!"qwd{c}" ww 512 (r "ql_t") (r "gd") (r "ql_v") (r "qw_f") s!"hw_data{c}"
    ram s!"wam{c}" ww 25 qwt (r "gb_m") room (inc (r "qw_r") ww) s!"wadr_n{c}"
    ram s!"whm{c}" ww 6 qwt (hash (r "gb_m")) room (r "qw_f") s!"wh_f{c}"
      [(inc (r "qw_r") ww,s!"wh_n{c}")]
    let hwM := slice (r "hs") 64 25
    let hwStrb := slice (r "hs") 0 64
    let haWe := bit (r "ha") 65
    let haM := slice (r "ha") 40 25
    let haIdx := slice (r "ha") 36 4
    let haData := slice (r "ha") 4 32
    let haBe := slice (r "ha") 0 4
    let hbWe := bit (r "hb") 553
    let hbM := slice (r "hb") 528 25
    let hbData := slice (r "hb") 16 512
    let hbMask := slice (r "hb") 0 16
    let wblk ← w "w_blk" 1 (sel (r "wnz") (r "wh_r") 1)
    let whold ← w "w_hold" 1 (all [nz (r "qw_rn") (ww+1),r "wp_r",bnot wblk,
      lt (r "qw_n") (lit (p.writeQueueDepth/2) (ww+1))])
    let ea := band (nz (r "qa_n") (qw+1)) (any [haWe,nz (r "a_iss") rnw,
      bnot (lt (lit (p.aDepth-p.prefetch) (aw+1)) (r "ra_res"))])
    let ewr := all [nz (r "qw_rn") (ww+1),r "wp_r",bnot wblk]
    let eww := all [bnot (eq (r "qw_n") (r "qw_rn")),
      bor (bnot (sel (r "wpart") (r "qw_f") 1)) (sel (r "wgot") (r "qw_f") 1),bnot whold]
    let eb := band (nz (r "qb_n") (qw+1)) (bor hbWe (lt (r "rb_res") (lit p.readDepth (rw+1))))
    let sv ← w "sv" 1 (any [r "hv",ea,ewr,eww,eb])
    let src ← w "src" 2 (mux (r "hv") (r "hsrc") (mux ea (lit 0 2) (mux ewr (lit 1 2) (mux eww (lit 2 2) (lit 3 2)))))
    let isa := eq src (lit 0 2)
    let iswr := eq src (lit 1 2)
    let isww := eq src (lit 2 2)
    let isb := eq src (lit 3 2)
    let swr ← w "swr" 1 (any [band isa haWe,isww,band isb hbWe])
    let cv ← w "cvalid" 1 (band sv (bnot (band swr (r "c_done"))))
    let wv ← w "wvalid" 1 (all [sv,swr,bnot (r "d_done")])
    let ca ← w "caddr" 25 (mux isa (add haM (ext (r "a_iss") rnw 25))
      (mux iswr (r "wadr_r") (mux isww hwM hbM)))
    let swData := pack ((List.range 64).map fun k => mux (bit hwStrb k)
      (slice (r "hw_data") (8*k) 8) (slice (r "wr_head") (8*k) 8))
    let aData := Expr.op .shl [ext haData 32 512,.concat [haIdx,lit 0 5]]
    let aMask := Expr.op .shl [ext haBe 4 64,.concat [haIdx,lit 0 2]]
    let bMask := pack ((List.range 64).map fun k => bit hbMask (k/4))
    let _ ← w "wdata" 512 (mux isww swData (mux isa aData hbData))
    let _ ← w "wmask" 64 (mux isww (lit (2^64-1) 64) (mux isa aMask bMask))
    let ctk ← w "ctk" 1 (band cv (bit (ref "n_cready") c))
    let dtk ← w "dtk" 1 (band wv (bit (ref "n_wready") c))
    let wiss ← w "wiss" 1 (all [sv,swr,bor (r "c_done") ctk,bor (r "d_done") dtk])
    let rtk ← w "rtk" 1 (band ctk (bnot swr))
    let tgin ← w "tg_in" (ww+2) (.concat [mux isa (lit 1 2) (mux iswr (lit 2 2) (lit 0 2)),r "qw_r"])
    let hin ← w "h_inc" 1 (bor (band iswr ctk) (band (nz (r "qw_rn") (ww+1)) (bnot (r "wp_r"))))
    let hde ← w "h_dec" 1 (band isww wiss)
    let rvalid := bit (ref "n_rvalid") c
    let rdata := slice (ref "n_rdata") (512*c) 512
    let tgk := slice (r "tgh") ww 2
    let tgs := slice (r "tgh") 0 ww
    let gotb := band rvalid (eq tgk (lit 0 2))
    let gota := band rvalid (eq tgk (lit 1 2))
    let gotw := band rvalid (eq tgk (lit 2 2))
    ram s!"tgm{c}" tw (ww+2) (slice (add (r "tg_h") (r "tg_n")) 0 tw) tgin rtk
      (inc (r "tg_h") tw) s!"tg_nx1{c}"
    ram s!"ram{c}" aw 512 (r "ra_t") rdata gota
      (add (r "ra_h") (ext aodrop rnw aw)) s!"ra_head{c}"
    ram s!"wrm{c}" ww 512 tgs rdata gotw (r "qw_f") s!"wr_head{c}"
    let mut rbPieces := []
    for k in [:8] do
      ram s!"rbm{c}_{k}" rw 64 (r s!"rb_tq{k}_") (slice rdata (64*k) 64) gotb (r "rb_h") s!"rb_piece{c}_{k}"
      sr s!"rb_tq{k}_" rw true [(gotb,inc (r s!"rb_tq{k}_") rw)]
      rbPieces := rbPieces ++ [ref s!"rb_piece{c}_{k}"]
    let _ ← w "rb_head" 512 (pack rbPieces)
    ur "tgh" (ww+2) [(eq (r "tg_n") (lit 0 (tw+1)),tgin),
      (rvalid,mux (eq (r "tg_n") (lit 1 (tw+1))) tgin (r "tg_nx1"))]
    sr "wk_v" 1 true [(one,wiss)]
    ur "wk_m" 25 [(one,ca)]
    let wkr ← w "wk_r" 1 (all [r "wk_v",r "pv",lt (sub (r "wk_m") (r "pnx")) (ext (r "pfl") rnw 25)])
    let _ ← w "wk_a" 1 (all [r "wk_v",ref "al_v",eq (ref "al_c") (lit c 1),eq (slice (ref "al_beat") 1 25) (r "wk_m")])
    let runTake := all [apush,bnot areuse,aThis]
    sr "pnx" 25 false [(runTake,mux ahit (inc (r "pnx") 25) (inc acb 25))]
    sr "pfl" rnw true [(runTake,mux ahit (sub (r "pfl") (lit 1 rnw)) (lit (p.prefetch-1) rnw))]
    sr "pv" 1 true [(band runTake (bnot ahit),one),(any [wkr,band atake (ref "a_we"),ref "a_flush"],zero)]
    sr "hv" 1 true [(one,band sv (mux swr (bnot wiss) (bnot ctk)))]
    sr "hsrc" 2 false [(one,src)]
    sr "c_done" 1 true [(one,all [swr,bnot wiss,bor (r "c_done") ctk])]
    sr "d_done" 1 true [(one,all [swr,bnot wiss,bor (r "d_done") dtk])]
    let lastBeat := eq (r "a_iss") (lit (p.prefetch-1) rnw)
    let popa := band isa (mux swr wiss (band ctk lastBeat))
    let popb := band isb (mux swr wiss ctk)
    let popw := band isww wiss
    sr "a_iss" rnw true [(band isa rtk,mux lastBeat (lit 0 rnw) (inc (r "a_iss") rnw))]
    for (n,width,pop) in [("qb_h",qw+1,popb),("qa_h",qw,popa),("qw_f",ww,popw),("qw_r",ww,hin),
        ("tg_h",tw,rvalid),("rb_t",rw,gotb),("ra_t",aw,gota),("rb_h",rw,bout)] do
      sr n width true [(pop,inc (r n) width)]
    for (n,width,pu,po) in [("qb_n",qw+1,qbp,popb),("qa_n",qw+1,qap,popa),("qw_n",ww+1,qwp,popw),
        ("qw_rn",ww+1,qwp,hin),("tg_n",tw+1,rtk,rvalid),("rb_n",rw+1,gotb,bout),
        ("rb_res",rw+1,band isb rtk,bout)] do sr n width true [(one,updn (r n) pu po width)]
    let popaData := all [aout,bnot aoreuse,eq aoc (lit c 1)]
    let dropped := inc (ext aodrop rnw (aw+1)) (aw+1)
    sr "ra_h" aw true [(popaData,add (r "ra_h") (slice dropped 0 aw))]
    sr "ra_n" (aw+1) true [(one,sub (add (r "ra_n") (ext gota 1 (aw+1))) (mux popaData dropped (lit 0 (aw+1))))]
    sr "ra_res" (aw+1) true [(one,sub (add (r "ra_res")
      (mux (all [isa,rtk,eq (r "a_iss") (lit 0 rnw)]) (lit p.prefetch (aw+1)) (lit 0 (aw+1))))
      (mux popaData dropped (lit 0 (aw+1))))]
    ur "iss_w" 16 [(wiss,inc (r "iss_w") 16),(ref "rst",slice (ref "n_wdone") (16*c) 16)]
    sr "gw_v" 1 true [(one,swThis)]
    ur "gw_same" 1 [(one,same)]
    ur "gw_wdata" 32 [(one,ref "sw_wdata")]
    ur "ql_t" ww [(one,qwt)]
    ur "ql_v" 1 [(one,room)]
    let byteHit := fun k => band (eq (ref "gw_word") (lit (k/4) 4)) (bit (ref "gw_be") (k%4))
    let gathered := pack ((List.range 64).map fun k => mux (byteHit k)
      (slice (r "gw_wdata") (8*(k%4)) 8) (mux (r "gw_same") (slice (r "gd") (8*k) 8) (lit 0 8)))
    ur "gd" 512 [(r "gw_v",gathered)]
    sr "gv" 1 true [(qwp,zero),(swThis,one)]
    sr "gage" 3 true [(all [bnot qwp,r "gv",bnot (eq (r "gage") (lit 7 3))],inc (r "gage") 3),(swThis,lit 0 3)]
    sr "gb_m" 25 false [(swThis,swm)]
    sr "gb_strb" 64 false [(swThis,pack ((List.range 64).map fun k =>
      bor (band (eq (slice (ref "sw_addr") 0 4) (lit (k/4) 4)) (bit (ref "sw_be") (k%4))) (band same (bit (r "gb_strb") k))))]
    -- Per-slot flags share procedural priority: returned fill wins over tail clear.
    let part := bnot (eq (r "gb_strb") (lit (2^64-1) 64))
    let mut parts := []
    let mut gots := []
    for k in [:p.writeQueueDepth] do
      let tailHit := band room (eq qwt (lit k ww))
      parts := parts ++ [mux tailHit part (bit (r "wpart") k)]
      gots := gots ++ [mux (band rvalid (band (bnot (bor (eq tgk (lit 0 2)) (eq tgk (lit 1 2)))) (eq tgs (lit k ww)))) one
        (mux tailHit zero (bit (r "wgot") k))]
    sr "wpart" p.writeQueueDepth false [(one,pack parts)]
    sr "wgot" p.writeQueueDepth false [(one,pack gots)]
    let tailAtRead := band room (eq (r "qw_rn") (mux hin (lit 1 (ww+1)) (lit 0 (ww+1))))
    for (n,width,current,next) in [("wadr_r",25,r "gb_m",r "wadr_n"),("wh_r",6,hash (r "gb_m"),r "wh_n"),
        ("wp_r",1,part,sel (r "wpart") (inc (r "qw_r") ww) 1)] do
      ur n width [(hin,next),(tailAtRead,current)]
    let counts := pack ((List.range 64).map fun k => r s!"whb{k}_")
    let atRead := sel counts (r "wh_r") (ww+1)
    let atWrite := sel counts (r "wh_f") (ww+1)
    let sameBucket := eq (r "wh_f") (r "wh_r")
    let mut live := []
    for k in [:64] do
      let iv := band hin (eq (r "wh_r") (lit k 6))
      let ik := band iv (bnot (band hde sameBucket))
      let dk := all [hde,eq (r "wh_f") (lit k 6),bnot (band hin sameBucket)]
      let update := bor ik dk
      live := live ++ [mux update (bor iv (bnot (eq atWrite (lit 1 (ww+1))))) (bit (r "wnz") k)]
      ur s!"whb{k}_" (ww+1) [(update,mux iv
        (mux (sel (r "wnz") (r "wh_r") 1) (inc atRead (ww+1)) (lit 1 (ww+1)))
        (sub atWrite (lit 1 (ww+1))))]
    sr "wnz" 64 true [(one,pack live)]
  for (n,w,internal) in [("n_cvalid",1,"cvalid"),("n_cwe",1,"swr"),("n_caddr",25,"caddr"),
      ("n_wvalid",1,"wvalid"),("n_wdata",512,"wdata"),("n_wmask",64,"wmask")] do
    output n (2*w) (pack [rr internal 0,rr internal 1])
end OpenTPU.NativeDram
