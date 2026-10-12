import OpenTPU.MxuControlFields

/-! Native MXU issuer, replay, command-overlap and drain combinational logic. -/
namespace OpenTPU.MxuControlLogic
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.SeqLogic
open OpenTPU.Mxu OpenTPU.MxuControlFields

def key (x : Expr) : Expr :=
  let clean := mux (eq (slice x 23 8) (lit 0 8)) (pack [lit 0 31,bit x 31]) x
  mux (bit clean 31) (bnot clean) (pack [slice clean 0 31,lit 1 1])

def unkey (x : Expr) : Expr := mux (bit x 31) (pack [slice x 0 31,lit 0 1]) (bnot x)

def build (c : Config) : CircuitM Unit := do
  let one := lit 1 1
  let zero := lit 0 1
  let pw := clog2 c.depth
  let rw := rfw c
  let mw := MxuControlFields.mw c
  let qfs := queueFields c
  let rfs := rmwFields c
  let hf := MxuControlFields.get qfs (ref "h")
  let nf := MxuControlFields.get qfs (ref "n")
  let pf := MxuControlFields.get qfs (ref "pop_e")
  let rfield := MxuControlFields.get rfs
  let cmd ← command c (ref "cmd")
  let _ ← signal "cmd_e" (width qfs) cmd
  let _ ← signal "pop_e" (width qfs) (if c.implementation == 2 then ref "pop_q" else ref "h")
  for (name,field,w,popField) in [("c_out","out",32,false),("c_tz","tz",1,false),
      ("c_KB","KB",16,true),("c_KBa","KBa",16,true),("c_pair","pair",1,true),
      ("c_hi","hi",c.columns,true),("c_M","M",8,false),("c_ab","ab",8,true),
      ("p_M","M",8,true),("p_G","G",8,true),("c_run","run",mw,false),
      ("c_unit","unit",1,true),("c_acc","acc",1,false),("c_rmax","rmax",1,false),
      ("c_asc","asc",1,false),("c_wf","wf",2,true),("c_asa","asa",32,false),("c_G","G",8,false)] do
    let _ ← signal name w ((if popField then pf else hf) field)
  let _ ← signal "p_act" 1 (band (nz (ref "q_n") 2) (pf "go"))
  let _ ← signal "c_act" 1 (band (nz (ref "q_n") 2) (hf "go"))
  let _ ← signal "c_w4" 1 (nz (ref "c_wf") 2)
  let _ ← signal "last_k" 1 (eq (add (zext (ref "ck") 16 32) (lit 1)) (zext (ref "c_KBa") 16 32))
  let _ ← signal "last_g" 1 (eq (add (zext (ref "cg") 8 32) (lit 1)) (zext (ref "p_G") 8 32))
  let _ ← signal "more" 1 (band (ref "p_act") (nz (ref "c_left")))
  let _ ← signal "ckc" 16 (mux (band (ref "c_w4") (bnot (ref "c_pair")))
    (pack [slice (ref "ck") 1 15,zero]) (ref "ck"))
  let _ ← signal "cdone" 1 (any [bnot (ref "c_w4"),ref "c_pair",bit (ref "ck") 0,ref "last_k"])
  let _ ← signal "f_av" 1 (mux (eq (ref "p_G") (lit 1 8)) (nz (ref "f_count") (pw+1))
    (bor (nz (ref "cg") 8) (lt (zext (ref "ckc") 16 32) (zext (ref "f_count") (pw+1) 32))))
  let _ ← signal "s_av" 1 (mux (eq (ref "p_G") (lit 1 8)) (nz (ref "s_count") (pw+2))
    (bor (nz (ref "cg") 8) (lt (zext (ref "ck") 16 32) (zext (ref "s_count") (pw+2) 32))))
  let _ ← signal "c_rch" 16 (mux (band (ref "c_w4") (bnot (ref "c_pair")))
    (.op .shr [add (zext (ref "c_KBa") 16 32) (lit 1),lit 1]) (ref "c_KBa"))
  let _ ← signal "row_in" 1 (if c.implementation != 2 then one else any [nz (ref "cg") 8,
    every [le (zext (ref "c_rch") 16 32) (zext (ref "f_count") (pw+1) 32),
      bor (ref "c_unit") (le (zext (ref "c_KBa") 16 32) (zext (ref "s_count") (pw+2) 32))]])
  let liveRoom := if c.implementation == 2 then
    lt (add (zext (ref "rows_live") (rw+1) (rw+2)) (zext (ref "rows_p") (rw+1) (rw+2))) (lit (rf c) (rw+2))
    else lt (zext (ref "rows_live") (rw+1) 32) (lit (rf c))
  let pop ← signal "pop" 1 (every [ref "more",ref "f_av",bor (ref "c_unit") (ref "s_av"),
    bor (nz (ref "ck") 16) (band (ref "row_in") liveRoom)])
  let _ ← signal "fpop" 1 (every [pop,ref "last_g",ref "cdone"])
  let _ ← signal "en_c" 1 (if c.implementation == 2 then one else
    bor pop (bnot (band (ref "more") (nz (ref "ck") 16))))
  let _ ← signal "need_b" 1 (any [bnot (ref "i_w4"),ref "i_pair",bnot (bit (ref "i_k") 0)])
  let _ ← signal "want_iss" 1 (band (ref "i_act")
    (bor (bnot (ref "need_b")) (lt (ref "occ") (lit c.depth (pw+1)))))
  let _ ← signal "go_iss" 1 (every [ref "want_iss",bor (bnot (ref "need_b")) (ref "b_gnt"),
    bor (ref "i_unit") (ref "a_gnt")])
  let _ ← signal "rdy" 1 (band (bnot (ref "i_act")) (lt (ref "q_n") (lit 2 2)))
  let _ ← signal "computing" 1 pop
  let _ ← signal "pf_level" (pw+1) (ref "f_count")
  let _ ← signal "pf_starve" 1 (band (ref "more") (eq (ref "f_count") (lit 0 (pw+1))))
  let _ ← signal "pf_block" 1 (every [ref "more",nz (ref "f_count") (pw+1),bnot pop])
  let _ ← signal "b_req" 1 (band (ref "go_iss") (ref "need_b"))
  let _ ← signal "b_addr" 32 (.op .shr [ref "chunk_addr",lit 2])
  let _ ← signal "a_req" 1 (band (ref "go_iss") (bnot (ref "i_unit")))
  let _ ← signal "a_addr" 32 (mux (ref "a_req") (.op .shr [ref "scale_addr",lit 2]) (lit 0))
  let _ ← signal "act_blk" 16 (add (zext (ref "c_ab") 8 16)
    (mux (ref "c_pair") (pack [zero,slice (ref "ck") 0 15]) (ref "ck")))
  let _ ← signal "act_blk2" 16 (add (zext (ref "c_ab") 8 16) (pack [one,slice (ref "ck") 0 15]))
  let _ ← signal "act_hi" c.columns (ref "c_hi")
  let _ ← signal "act_grp" 8 (ref "cg")
  let _ ← signal "act_ren" 1 (ref "en_c")
  let _ ← signal "rf_push" 1 (band (ref "en_c") (ref "lv2"))
  let _ ← signal "c_Mn" mw (mux (ref "d_last") (hf "Ml") (lit c.columns mw))
  let _ ← signal "drain_go" 1 (every [ref "rf_nz",if c.implementation == 2 then ref "rl_nz" else one,
    bor (bnot (ref "c_asc")) (eq (ref "al_st") (lit 2 2))])
  let _ ← signal "drain_row_done" 1 (band (ref "drain_go") (ref "d_fin"))
  let _ ← signal "d_rest" mw (sub (sub (ref "c_Mn") (ref "dj")) (ref "ncnt"))
  let dg2 ← signal "dg2" 8 (add (ref "dg1") (lit 1 8))
  let _ ← signal "d_nl" 1 (mux (ref "d_last") (hf "g1") (eq dg2 (ref "c_G")))
  let _ ← signal "st_mid" (mw+1) (drainStep c (ref "d_rest") (ref "c_run"))
  let _ ← signal "st_grp" (mw+1) (mux (ref "d_nl") (pack [hf "dnl",hf "dfl"])
    (drainStep c (lit c.columns mw) (ref "c_run")))
  for (name,st) in [("ln_mid","st_mid"),("ln_grp","st_grp")] do
    let _ ← signal name (nl c) (lanes c (slice (ref st) 0 mw))
  let _ ← signal "d_pop" 1 (band (ref "t_gnt") (ref "drain_row_done"))
  let _ ← signal "next_dj" mw (add (ref "dj") (ref "ncnt"))
  let _ ← signal "daddr_l" (c.lanes*32) (pack ((List.range c.lanes).map fun k =>
    if k < nl c then ref s!"dal{k}" else lit 0))
  let mut dvals : List Expr := []
  let mut dcols : List Expr := []
  for k in [:c.lanes] do
    if k < nl c then
      let valid := lt (add (zext (ref "dj") mw 32) (lit k)) (lit c.columns)
      let idx ← signal s!"drain_index{k}" mw (add (ref "dj") (lit k mw))
      dvals := dvals ++ [mux valid (selectArray ((List.range c.columns).map fun j => slice (ref "rfh") (j*32) 32) idx mw 32) (lit 0)]
      dcols := dcols ++ [mux valid (add (zext (ref "dj") mw 8) (lit k 8)) (lit 0 8)]
    else
      dvals := dvals ++ [lit 0]
      dcols := dcols ++ [lit 0 8]
  let _ ← signal "dval_l" (c.lanes*32) (pack dvals)
  let _ ← signal "dcol_l" (c.lanes*8) (pack dcols)
  let _ ← signal "mxm_nx" c.lanes (pack ((List.range c.lanes).map fun k =>
    lt (add (add (zext (ref "mx_i") 8 32) (lit c.lanes)) (lit k)) (zext (ref "c_M") 8 32)))
  let _ ← signal "c_drained" 1 (every [ref "c_act",bnot (ref "cl_ld"),
    bor (ref "pn") (eq (ref "c_left") (lit 0)),eq (ref "rows_live") (lit 0 (rw+1)),
    eq (ref "rmw_n") (lit 0 4),bnot (rfield (ref "r0") "v"),bnot (rfield (ref "r1") "v"),bnot (rfield (ref "rx") "v")])
  let _ ← signal "mx_go" 1 (band (ref "mx_q") (bnot (ref "mx_done")))
  let _ ← signal "c_fin" 1 (band (ref "c_drained") (any [bnot (ref "c_rmax"),ref "mx_done",ref "c_tz"]))
  let done ← signal "c_done" 1 (band (ref "c_fin") (if c.implementation == 2 then one else bnot pop))
  let _ ← signal "al_go" 1 (every [ref "c_act",ref "c_asc",eq (ref "al_st") (lit 0 2)])
  let _ ← signal "st_g" 4 (mux (ref "st_f") (lit 0 4) (ref "st_c"))
  let _ ← signal "new_head_row" 1 (every [pop,eq (ref "ck") (lit 0 16),if c.implementation == 2 then bnot (ref "pn") else one])
  let _ ← signal "rn" (rw+1) (sub (add (ref "rf_n") (zext (ref "rf_push") 1 (rw+1))) (zext (ref "d_pop") 1 (rw+1)))
  let _ ← signal "rl" (rw+1) (sub (add (ref "rows_live") (zext (ref "new_head_row") 1 (rw+1))) (zext (ref "d_pop") 1 (rw+1)))
  let _ ← signal "rp" (rw+1) (add (ref "rows_p") (zext (if c.implementation == 2 then
    every [pop,eq (ref "ck") (lit 0 16),ref "pn"] else zero) 1 (rw+1)))
  let _ ← signal "advance_pop_head" 1 (if c.implementation != 2 then zero else every [
    bnot (ref "pn"),bnot (ref "cl_ld"),eq (ref "c_left") (lit 0),eq (ref "q_n") (lit 2 2),
    nf "go",bnot done,eq (nf "pair") (hf "pair"),bor (bnot (hf "pair")) (eq (nf "M") (hf "M"))])
  let pnx ← signal "pnx" 1 (mux done zero (bor (ref "pn") (ref "advance_pop_head")))
  let _ := pnx
  let _ ← signal "qn" 2 (sub (add (ref "q_n") (zext (ref "start") 1 2)) (zext done 1 2))
  let hAccept := band (ref "start") (eq (ref "q_n") (lit 0 2))
  let nAccept := band (ref "start") (nz (ref "q_n") 2)
  let releaseHead := every [ref "go",nz (ref "q_n") 2,bnot (hf "go")]
  let releaseNext := band (ref "go") (bnot (band (nz (ref "q_n") 2) (bnot (hf "go"))))
  let hn0 ← signal "hn0" (width qfs) (mux hAccept (ref "cmd_e") (ref "h"))
  let nn0 ← signal "nn0" (width qfs) (mux nAccept (ref "cmd_e") (ref "n"))
  let hn ← signal "hn" (width qfs) (mux releaseHead (put qfs hn0 "go" one) hn0)
  let nn ← signal "nn" (width qfs) (mux releaseNext (put qfs nn0 "go" one) nn0)
  let hp ← signal "hp" (width qfs) (mux releaseHead (put qfs (ref "h") "go" one) (ref "h"))
  let np ← signal "np" (width qfs) (mux releaseNext (put qfs (ref "n") "go" one) (ref "n"))
  for (name,a,b) in [("hx",nn,hn),("nx",hn,nn),("hpx",np,hp),("npx",hp,np)] do
    let _ ← signal name (width qfs) (mux done a b)

end OpenTPU.MxuControlLogic
