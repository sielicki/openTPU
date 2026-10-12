import OpenTPU.MxuControlLogic
import OpenTPU.MxuHelpers

/-! MXU chunk/scale/result storage and drain-side floating-point composition.
    FIFO reads retain old-data behavior; result FIFO bypass is explicit. -/
namespace OpenTPU.MxuControlDatapath
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.SeqLogic
open OpenTPU.Mxu OpenTPU.MxuControlFields OpenTPU.MxuControlLogic

private def declared (name : String) (bits : Nat) : CircuitM Expr := do
  let m ← getModule
  setModule <| m.addWire {name,ty := .bitVector bits}
  return ref name

private def delay (stem : String) (bits n : Nat) (en value : Expr) : CircuitM Expr := do
  let mut x := value
  for k in [:n] do x ← clocked s!"{stem}{k}" bits en x
  return x

def fifoModuleName (g : Nat) := s!"otpu_mxu_fifo_group{g}"

/-- Preserve each 36-bit-column group's synchronous RAM boundary. -/
def fifoModule (c : Config) (g : Nat) : Module :=
  { MxuHelpers.ram (fgLo c (g+1)-fgLo c g) c.depth with name := fifoModuleName g }

def fifoModules (c : Config) := (List.range (fg c)).map (fifoModule c)

def build (c : Config) : CircuitM Unit := do
  let one := lit 1 1
  let zero := lit 0 1
  let en := ref "en_c"
  let grant := ref "t_gnt"
  let pw := clog2 c.depth
  let rw := rfw c
  let mw := MxuControlFields.mw c
  let rfs := rmwFields c
  let rfield := MxuControlFields.get rfs
  let mut chunks : List Expr := []
  for g in [:fg c] do
    let lo := fgLo c g
    let w := fgLo c (g+1)-lo
    let data ← declared s!"w0_piece{g}" w
    emitInstance (fifoModuleName g) s!"fifo_group{g}"
      [("clk",ref "clk"),("we",ref "b_rvalid"),("wa",ref s!"f_tl{g}"),
       ("wd",slice (ref "b_rdata") lo w),("re",en),("ra",ref s!"f_rdl{g}"),("rd",data)]
    chunks := chunks ++ [data]
  let _ ← signal "w0" (c.d*8) (pack chunks)
  let scales ← emitMemoryComboRead "fifo_scale" (pw+1) 64 "clk" (ref "s_tail")
    (pack [ref "a_rdata",ref "a_rdata2"]) (ref "a_rvalid") (ref "s_rd")
  let ws0r ← clocked "ws0r" 64 en (ref scales)
  let _ ← clocked "m0" 7 en (mux (ref "pop") (pack [
    band (ref "c_pair") (bnot (band (ref "last_k") (bit (ref "c_KB") 0))),
    every [ref "c_w4",bnot (ref "c_pair"),bit (ref "ck") 0],slice (ref "ck") 0 2,
    lt (ref "ck") (lit 4 16),ref "last_k",one]) (lit 0 7))
  for (name,w,value) in [("cu0",1,ref "c_unit"),("wf0",2,ref "c_wf"),
      ("pr0",1,ref "c_pair"),("hi0",c.columns,ref "c_hi")] do
    let _ ← clocked name w en value
  let w40 := nz (ref "wf0") 2
  let _ ← signal "ws0" 32 (mux (ref "cu0") (lit 0x3f800000)
    (mux w40 (pack [lit 0 16,slice ws0r 0 16]) (slice ws0r 0 32)))
  let _ ← signal "mb0" 16 (mux (bor (ref "cu0") (bnot w40)) (lit 0x1111 16) (slice ws0r 16 16))
  let _ ← signal "ws0h" 32 (mux (ref "cu0") (lit 0x3f800000) (pack [lit 0 16,slice ws0r 32 16]))
  let _ ← signal "mb0h" 16 (mux (ref "cu0") (lit 0x1111 16) (slice ws0r 48 16))

  let mut rq : List Expr := []
  for k in [:3] do
    let addr ← signal s!"rf_qc{k}" rw (add (ref "rf_q") (lit k rw))
    let mem ← emitMemoryComboRead s!"result_fifo{k}" rw (c.columns*32) "clk" (ref "rf_t") (ref "rowr")
      (band (bnot (ref "rst")) (ref "rf_push")) addr
    rq := rq ++ [← signal s!"rq{k}" (c.columns*32)
      (mux (band (ref "rf_push") (eq (ref "rf_t") addr)) (ref "rowr") (ref mem))]
  let rh0 ← clocked "rh0" (c.columns*32) one (mux (ref "rf_hs") rq[1]! rq[0]!)
  let rh1 ← clocked "rh1" (c.columns*32) one (mux (ref "rf_hs") rq[2]! rq[1]!)
  let _ ← signal "rfh" (c.columns*32) (mux (ref "rf_hs") rh1 rh0)

  reg "r1" (width rfs) true [(grant,ref "r0")]
  for k in [:nl c] do
    let col := slice (rfield (ref "r0") "col") (k*8) 8
    let alpha := readArray ((List.range c.columns).map fun j => ref s!"alpha{j}") col (mw-1) 32
    reg s!"xo{k}" 32 false [(grant,slice (ref "t_rdata") (k*32) 32)]
    reg s!"alr{k}" 32 false [(grant,mux (ref "c_asc") alpha (lit 0x3f800000))]
    let product ← declared s!"rmw_product{k}" 32
    let result ← declared s!"ry{k}" 32
    let delayed ← delay s!"rmw_c{k}_" 32 2 grant (slice (rfield (ref "r1") "nv") (k*32) 32)
    emitInstance "otpu_mxu_fmul" s!"rmw_mul{k}"
      [("clk",ref "clk"),("en",grant),("a",ref s!"xo{k}"),("b",ref s!"alr{k}"),("y",product)]
    emitInstance "otpu_mxu_fadd" s!"rmw_add{k}"
      [("clk",ref "clk"),("en",grant),("a",product),("b",delayed),("y",result)]
  let rwValue ← delay "rw_pipe" (width rfs) 6 grant (ref "r1")
  let _ ← signal "rw" (width rfs) rwValue
  let mut rh : List Expr := []
  let mut rxh : List Expr := []
  for k in [:nl c] do
    for j in [:c.columns] do
      let col1 := slice (rfield (ref "r1") "col") (k*8) (max 1 (mw-1))
      let colx := slice (rfield (ref "rx") "col") (k*8) (max 1 (mw-1))
      rh := rh ++ [every [rfield (ref "r1") "v",ref "c_rmax",bit (rfield (ref "r1") "m") k,
        eq col1 (lit j (max 1 (mw-1)))]]
      rxh := rxh ++ [every [rfield (ref "rx") "v",bit (rfield (ref "rx") "m") k,
        eq colx (lit j (max 1 (mw-1)))]]
  let hits ← delay "rwh_pipe" (nl c*c.columns) 5 grant (pack rh)
  reg "rwh" (nl c*c.columns) true [(grant,hits)]
  let _ ← signal "rxh" (nl c*c.columns) (pack rxh)
  let mut hitList : List Expr := []
  let mut updateList : List Expr := []
  for j in [:c.columns] do
    let mut candidates := lit 0
    let mut hit := zero
    let mut upd := zero
    for k in [:nl c] do
      for (which,value) in [(bit (ref "rxh") (k*c.columns+j),slice (rfield (ref "rx") "nv") (k*32) 32),
          (bit (ref "rwh") (k*c.columns+j),ref s!"ry{k}")] do
        let candidate := key value
        hit := bor hit which
        candidates := bor candidates (mux which candidate (lit 0))
        upd := bor upd (band which (bor (bnot (bit (ref "mx_have") j)) (lt (ref s!"mk{j}") candidate)))
    let _ ← signal s!"mx_cand{j}" 32 candidates
    hitList := hitList ++ [hit]
    updateList := updateList ++ [upd]
  let _ ← signal "mx_hit" c.columns (pack hitList)
  let _ ← signal "mx_upd" c.columns (pack updateList)

  let mut ren : List Expr := []
  let mut raddr : List Expr := []
  let mut wen : List Expr := []
  let mut waddr : List Expr := []
  let mut wdata : List Expr := []
  for k in [:c.lanes] do
    let dr := if k < nl c then band (ref "drain_go") (bit (ref "dln") k) else zero
    let ar := band (ref "al_go") (lt (add (zext (ref "al_i") 8 32) (lit k)) (zext (ref "c_M") 8 32))
    let wr := if k < nl c then band (rfield (ref "rw") "v") (bit (rfield (ref "rw") "m") k) else zero
    let mx := band (ref "mx_go") (bit (ref "mxm") k)
    ren := ren ++ [bor (band dr (ref "c_acc")) ar]
    raddr := raddr ++ [mux ar (add (add (ref "c_asa") (zext (ref "al_i") 8 32)) (lit k))
      (mux (band (ref "drain_go") (ref "c_acc")) (slice (ref "daddr_l") (k*32) 32) (lit 0))]
    wen := wen ++ [any [band dr (bnot (ref "c_acc")),wr,mx]]
    let da := mux (band (ref "drain_go") (bnot (ref "c_acc"))) (slice (ref "daddr_l") (k*32) 32) (lit 0)
    let dv := mux (band (ref "drain_go") (bnot (ref "c_acc"))) (slice (ref "dval_l") (k*32) 32) (lit 0)
    let wa := if k < nl c then mux wr (slice (rfield (ref "rw") "ad") (k*32) 32) da else da
    let wv := if k < nl c then mux wr (ref s!"ry{k}") dv else dv
    let index ← signal s!"mx_index{k}" mw (add (zext (ref "mx_i") 8 32) (lit k))
    -- The unpacked reference RAM has clog2(MCOLS) address bits. Retain that
    -- truncation even for arbitrary controller states outside valid drain runs.
    let maxValue := unkey (readArray ((List.range c.columns).map fun j => ref s!"mk{j}") index (clog2 c.columns) 32)
    waddr := waddr ++ [mux mx (ref s!"mxl{k}") wa]
    wdata := wdata ++ [mux mx maxValue wv]
  for (name,w,value) in [("t_ren",c.lanes,pack ren),("t_raddr",c.lanes*32,pack raddr),
      ("t_wen",c.lanes,pack wen),("t_waddr",c.lanes*32,pack waddr),("t_wdata",c.lanes*32,pack wdata)] do
    let _ ← signal name w value

end OpenTPU.MxuControlDatapath
