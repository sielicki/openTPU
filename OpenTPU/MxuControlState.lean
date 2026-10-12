import OpenTPU.MxuControlFields

/-! Ordered next-state updates for the MXU outer controller. The ordering follows
    nonblocking-assignment priority: command completion overrides normal drain
    updates, and accepting an empty-queue head supplies its address last. -/
namespace OpenTPU.MxuControlState
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.SeqLogic
open OpenTPU.Mxu OpenTPU.MxuControlFields

private structure Register where
  name : String
  bits : Nat
  reset : Bool
  initial : Int := 0
  updates : List (Expr × Expr) := []

private def update (rs : List Register) (name : String) (en value : Expr) : List Register :=
  rs.map fun r => if r.name == name then {r with updates := r.updates ++ [(en,value)]} else r

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
  let cmd := ref "cmd"
  let start := ref "start"
  let pop := ref "pop"
  let grant := ref "t_gnt"
  let done := ref "c_done"
  let empty := eq (ref "q_n") (lit 0 2)
  let accepting := band start empty
  let draining := band grant (ref "drain_go")
  let rowDone := band draining (ref "drain_row_done")
  let newRow := band rowDone (ref "d_last")
  let newGroup := band rowDone (bnot (ref "d_last"))
  let newStep := band draining (bnot (ref "drain_row_done"))
  let issue := ref "go_iss"
  let issuerLast := eq (add (zext (ref "i_k") 16 32) (lit 1)) (zext (ref "i_KB") 16 32)
  let acceptIssue := every [start,nz (slice (word cmd 4) 0 16) 16,nz (slice (word cmd 4) 16 16) 16]
  let mut rs : List Register := []
  for (name,w) in [("done",1),("pf_u",1),("i_act",1),("q_n",2),("pn",1),("rows_p",rw+1),
      ("occ",pw+1),("f_head",pw),("f_tail",pw),("f_count",pw+1),("f_rd",pw),
      ("s_head",pw+1),("s_tail",pw+1),("s_count",pw+2),("s_rd",pw+1),
      ("ck",16),("cg",8),("dg",8),("c_left",32),("cl_ld",1),("rows_live",rw+1),
      ("rf_q",rw),("rf_hs",1),("rf_t",rw),("rf_n",rw+1),("rf_nz",1),("rl_nz",1),
      ("dj",mw),("mx_done",1),("mx_have",c.columns),("d_last",1),("d_fin",1),("ncnt",mw),
      ("dln",nl c),("mxm",c.lanes),("al_st",2),("al_i",8),("mx_i",8),
      ("r0",width rfs),("rx",width rfs),("rmw_n",4),("st_starve",32),("st_bp",32),
      ("st_frz",32),("st_deny",32),("st_c",4),("st_f",1),("mx_q",1)] do
    rs := rs ++ [{name,bits := w,reset := true}]
  rs := rs ++ [{name := "dg1",bits := 8,reset := true,initial := 1}]
  for (name,w) in [("i_left",32),("i_KB",16),("i_k",16),("i_rs",32),("i_srs",32),
      ("i_unit",1),("i_w4",1),("i_pair",1),("row_addr",32),("chunk_addr",32),
      ("srow_addr",32),("scale_addr",32),("h",width qfs),("n",width qfs),
      ("pop_q",width qfs),("pf_uv",128)] do
    rs := rs ++ [{name,bits := w,reset := false}]
  for g in [:fg c] do
    for stem in ["f_tl","f_rdl"] do rs := rs ++ [{name := s!"{stem}{g}",bits := pw,reset := true}]
  for j in [:c.columns] do
    for stem in ["dad","drow","alpha","mk"] do rs := rs ++ [{name := s!"{stem}{j}",bits := 32,reset := false}]
  for j in [:nl c] do rs := rs ++ [{name := s!"dal{j}",bits := 32,reset := false}]
  for k in [:c.lanes] do rs := rs ++ [{name := s!"mxl{k}",bits := 32,reset := false}]

  rs := update rs "done" one zero
  rs := update rs "pf_u" one zero
  rs := update rs "cl_ld" one zero
  rs := update rs "c_left" (ref "cl_ld") (hf "total")
  rs := update rs "cl_ld" accepting one
  for (name,value) in [("i_act",one),("i_left",ref "cmd_total"),("i_KB",ref "cmd_KBa"),
      ("i_k",lit 0 16),("i_rs",word cmd 5),("i_srs",word cmd 7),("i_unit",flag cmd 0),
      ("i_w4",nz (slice cmd 228 2) 2),("i_pair",ref "cmd_pair"),
      ("row_addr",word cmd 1),("chunk_addr",word cmd 1),
      ("srow_addr",word cmd 2),("scale_addr",word cmd 2)] do
    rs := update rs name acceptIssue value
  rs := update rs "i_left" issue (sub (ref "i_left") (lit 1))
  rs := update rs "i_act" (band issue (eq (ref "i_left") (lit 1))) zero
  rs := update rs "i_k" issue (mux issuerLast (lit 0 16) (add (ref "i_k") (lit 1 16)))
  for name in ["row_addr","chunk_addr"] do
    rs := update rs name (band issue issuerLast) (add (ref "row_addr") (ref "i_rs"))
  for name in ["srow_addr","scale_addr"] do
    rs := update rs name (band issue issuerLast) (add (ref "srow_addr") (ref "i_srs"))
  rs := update rs "chunk_addr" (every [issue,bnot issuerLast,any [bnot (ref "i_w4"),ref "i_pair",bit (ref "i_k") 0]])
    (add (ref "chunk_addr") (lit c.d))
  rs := update rs "scale_addr" (band issue (bnot issuerLast))
    (add (ref "scale_addr") (mux (ref "i_pair") (lit 8) (lit 4)))
  for name in ["f_tail"] ++ ((List.range (fg c)).map fun g => s!"f_tl{g}") do
    rs := update rs name (ref "b_rvalid") (add (ref name) (lit 1 pw))
  rs := update rs "s_tail" (ref "a_rvalid") (add (ref "s_tail") (lit 1 (pw+1)))
  for (name,w,inc,dec) in [("f_count",pw+1,ref "b_rvalid",ref "fpop"),
      ("occ",pw+1,ref "b_req",ref "fpop"),
      ("s_count",pw+2,ref "a_rvalid",every [pop,ref "last_g",bnot (ref "c_unit")])] do
    rs := update rs name one (sub (add (ref name) (zext inc 1 w)) (zext dec 1 w))
  rs := update rs "f_head" (ref "fpop") (add (ref "f_head") (lit 1 pw))
  rs := update rs "s_head" (every [pop,ref "last_g",bnot (ref "c_unit")]) (add (ref "s_head") (lit 1 (pw+1)))
  rs := update rs "c_left" (band pop (ref "last_g")) (sub (ref "c_left") (lit 1))
  let replay := band (ref "last_k") (bnot (ref "last_g"))
  for name in ["f_rd"] ++ ((List.range (fg c)).map fun g => s!"f_rdl{g}") do
    rs := update rs name (band pop replay) (ref "f_head")
    rs := update rs name (every [pop,bnot replay,ref "cdone"]) (add (ref name) (lit 1 pw))
  rs := update rs "s_rd" (band pop (bnot (ref "c_unit")))
    (mux replay (ref "s_head") (add (ref "s_rd") (lit 1 (pw+1))))
  rs := update rs "ck" pop (mux (ref "last_k") (lit 0 16) (add (ref "ck") (lit 1 16)))
  rs := update rs "cg" (band pop (ref "last_k")) (mux (ref "last_g") (lit 0 8) (add (ref "cg") (lit 1 8)))
  rs := update rs "rf_t" (ref "rf_push") (add (ref "rf_t") (lit 1 rw))
  rs := update rs "r0" grant (lit 0 (width rfs))
  rs := update rs "rx" grant (lit 0 (width rfs))
  let rmwEntry := construct rfs [("v",one),("m",ref "dln"),("ad",slice (ref "daddr_l") 0 (nl c*32)),
    ("nv",slice (ref "dval_l") 0 (nl c*32)),("col",slice (ref "dcol_l") 0 (nl c*8))]
  rs := update rs "r0" (band draining (ref "c_acc")) rmwEntry
  rs := update rs "rx" (every [draining,ref "c_rmax",bnot (ref "c_acc")])
    (put rfs rmwEntry "ad" (lit 0 (nl c*32)))
  rs := update rs "dj" rowDone (lit 0 mw)
  rs := update rs "dg" newRow (lit 0 8)
  rs := update rs "dg1" newRow (lit 1 8)
  rs := update rs "dg" newGroup (add (ref "dg") (lit 1 8))
  rs := update rs "dg1" newGroup (add (ref "dg1") (lit 1 8))
  rs := update rs "dj" newStep (add (ref "dj") (ref "ncnt"))
  let nextDal ← drainAddresses c "next_dal" (ref "next_dj")
  for j in [:c.columns] do
    let nextRow := add (ref s!"drow{j}") (lit 1)
    let nextGroup := add (ref s!"dad{j}") (hf "gs")
    rs := update rs s!"dad{j}" newRow nextRow
    rs := update rs s!"drow{j}" newRow nextRow
    rs := update rs s!"dad{j}" newGroup nextGroup
    if j < nl c then
      rs := update rs s!"dal{j}" newRow nextRow
      rs := update rs s!"dal{j}" newGroup nextGroup
      rs := update rs s!"dal{j}" newStep (slice nextDal (j*32) 32)
    rs := update rs s!"mk{j}" (band grant (bit (ref "mx_upd") j)) (ref s!"mx_cand{j}")
    let alphaEn := every [grant,eq (ref "al_st") (lit 1 2),le (zext (ref "al_i") 8 32) (lit j),
      lt (lit j) (add (zext (ref "al_i") 8 32) (lit c.lanes))]
    let ai ← signal s!"alpha_index{j}" (max 1 (clog2 c.lanes)) (sub (lit j) (zext (ref "al_i") 8 32))
    rs := update rs s!"alpha{j}" alphaEn (selectArray ((List.range c.lanes).map fun k => slice (ref "t_rdata") (k*32) 32)
      ai (clog2 c.lanes) 32)
  rs := update rs "mx_have" grant (bor (ref "mx_have") (ref "mx_hit"))
  rs := update rs "rmw_n" grant (sub (add (ref "rmw_n") (zext (band (ref "drain_go") (ref "c_acc")) 1 4))
    (zext (MxuControlFields.get rfs (ref "rw") "v") 1 4))
  let mxMore := lt (add (zext (ref "mx_i") 8 32) (lit c.lanes)) (zext (ref "c_M") 8 32)
  rs := update rs "mx_done" (every [grant,ref "mx_go",bnot mxMore]) one
  rs := update rs "mx_i" (every [grant,ref "mx_go",mxMore]) (add (ref "mx_i") (lit c.lanes 8))
  rs := update rs "al_st" (band grant (ref "al_go")) (lit 1 2)
  let alphaMore := lt (add (zext (ref "al_i") 8 32) (lit c.lanes)) (zext (ref "c_M") 8 32)
  let loading := band grant (eq (ref "al_st") (lit 1 2))
  rs := update rs "al_st" loading (mux alphaMore (lit 0 2) (lit 2 2))
  rs := update rs "al_i" (band loading alphaMore) (add (ref "al_i") (lit c.lanes 8))
  rs := update rs "rf_n" one (ref "rn")
  rs := update rs "rf_q" one (add (ref "rf_q") (zext (ref "rf_hs") 1 rw))
  rs := update rs "rf_hs" one (ref "d_pop")
  for k in [:c.lanes] do
    rs := update rs s!"mxl{k}" (bnot (ref "mx_go")) (add (hf "mxo") (lit k))
    rs := update rs s!"mxl{k}" (every [ref "mx_go",grant,mxMore]) (add (ref s!"mxl{k}") (lit c.lanes))
  rs := update rs "rows_live" one (ref "rl")
  rs := update rs "rows_p" one (ref "rp")
  rs := update rs "rf_nz" one (bor (ref "rf_push") (band (ref "rf_nz")
    (bnot (band (eq (ref "rf_n") (lit 1 (rw+1))) (ref "d_pop")))))
  rs := update rs "rl_nz" one (bor (ref "new_head_row") (band (ref "rl_nz")
    (bnot (band (eq (ref "rows_live") (lit 1 (rw+1))) (ref "d_pop")))))
  rs := update rs "c_left" (ref "advance_pop_head") (nf "total")
  rs := update rs "st_c" one (pack [band (ref "more") (eq (ref "f_count") (lit 0 (pw+1))),
    every [ref "more",nz (ref "f_count") (pw+1),bnot pop],
    band (bnot grant) (any [ref "drain_go",MxuControlFields.get rfs (ref "rw") "v",ref "mx_go",ref "al_go"]),
    band (ref "want_iss") (bnot issue)])
  rs := update rs "st_f" one done
  rs := update rs "mx_q" one (every [ref "c_drained",ref "c_rmax",bnot (ref "mx_done"),bnot (ref "c_tz")])
  for (name,k) in [("st_starve",0),("st_bp",1),("st_frz",2),("st_deny",3)] do
    rs := update rs name one (add (ref name) (zext (bit (ref "st_g") k) 1 32))
    rs := update rs name done (lit 0)
  rs := update rs "done" done one
  rs := update rs "pf_u" done one
  rs := update rs "pf_uv" done (pack ((["st_starve","st_bp","st_frz","st_deny"].zipIdx).map fun (name,k) =>
    add (ref name) (zext (bit (ref "st_g") k) 1 32)))
  rs := update rs "dg" done (lit 0 8)
  rs := update rs "dg1" done (lit 1 8)
  for name in ["ck","cg"] do rs := update rs name (band done (bnot (ref "pn"))) (lit 0 (if name == "ck" then 16 else 8))
  rs := update rs "c_left" (band done (bnot (ref "pn"))) (mux (eq (ref "q_n") (lit 2 2)) (nf "total") (lit 0))
  rs := update rs "cl_ld" (every [done,bnot (ref "pn"),start,eq (ref "q_n") (lit 1 2)]) one
  rs := update rs "rows_live" (band done (ref "pn")) (ref "rp")
  rs := update rs "rl_nz" (band done (ref "pn")) (nz (ref "rp") (rw+1))
  rs := update rs "rows_p" (band done (ref "pn")) (lit 0 (rw+1))
  for (name,w) in [("dj",mw),("mx_done",1),("mx_have",c.columns),("al_st",2),("al_i",8),("mx_i",8)] do
    rs := update rs name done (lit 0 w)
  for j in [:c.columns] do
    let cmdAddr := add (word cmd 3) (.op .mul [lit j,zext (slice (word cmd 6) 0 16) 16 32])
    let nextAddr := mux (band start (eq (ref "q_n") (lit 1 2))) cmdAddr
      (add (nf "out") (slice (nf "jo") (j*32) 32))
    for name in [s!"dad{j}",s!"drow{j}"] ++ (if j < nl c then [s!"dal{j}"] else []) do
      rs := update rs name done nextAddr
      rs := update rs name accepting cmdAddr
  rs := update rs "h" one (ref "hx")
  rs := update rs "n" one (ref "nx")
  rs := update rs "pop_q" one (mux (ref "pnx") (ref "npx") (ref "hpx"))
  rs := update rs "pn" one (ref "pnx")
  rs := update rs "q_n" one (ref "qn")
  let headChange := bor done accepting
  let hx := MxuControlFields.get qfs (ref "hx")
  let st ← signal "new_head_step" (mw+1) (mux (hx "g1") (pack [hx "dnl",hx "dfl"])
    (drainStep c (lit c.columns mw) (hx "run")))
  for (name,w,value) in [("d_last",1,hx "g1"),("d_fin",1,bit st mw),("ncnt",mw,slice st 0 mw),
      ("dln",nl c,lanes c (slice st 0 mw)),
      ("mxm",c.lanes,pack ((List.range c.lanes).map fun k => lt (lit k) (zext (hx "M") 8 32)))] do
    let _ := w
    rs := update rs name headChange value
  let mid := every [bnot headChange,draining,bnot (ref "d_fin")]
  let group := every [bnot headChange,draining,ref "d_fin"]
  for (en,st,ln) in [(mid,ref "st_mid",ref "ln_mid"),(group,ref "st_grp",ref "ln_grp")] do
    rs := update rs "d_fin" en (bit st mw)
    rs := update rs "ncnt" en (slice st 0 mw)
    rs := update rs "dln" en ln
  rs := update rs "d_last" group (ref "d_nl")
  rs := update rs "mxm" (every [bnot headChange,grant,ref "mx_go",mxMore]) (ref "mxm_nx")
  for r in rs do reg r.name r.bits r.reset r.updates r.initial

end OpenTPU.MxuControlState
