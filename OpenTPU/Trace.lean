import OpenTPU.Circuit
import OpenTPU.Backend

namespace OpenTPU.Trace
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

structure Config where
  depth : Nat := 16384
  queueDepth : Nat := 32
  window : Nat := 16
  deriving Repr

-- Packed fields in declaration order (most significant first), from otpu_pkg.
def perfFields : List (String × Nat) :=
  [("cyc",32),("d",1),("d_slot",5),("d_pc",32),("d_op",8),
   ("d_w1",32),("d_w2",32),("d_w3",32),("s",5),("s_slot",25),("s_rdy",160),
   ("g",1),("g_slot",5),("e",32),("busy",5),("ret",2),
   ("mac",1),("starve",1),("deny",1),("u_mxu",1),("u_mxu_v",128),
   ("u_q",1),("u_q_frz",32),("u_vpu",1),("u_vpu_frz",32),
   ("w",1),("w_n",32),("w_p",288),("w_q",192),("h",1),("h_v",128)]

def bundleFields : List (String × Nat) :=
  [("cyc",32),("g",1),("g_slot",4),("e",16),("s",5),("s_slot",20),
   ("s_dt",80),("s_x",5),("s_rdy",160),("d",1),("d_slot",4),("d_pc",16),
   ("d_ow",104),("u_mxu",1),("u_mxu_v",128),("u_q",1),("u_q_v",32),
   ("u_vpu",1),("u_vpu_v",32),("h",1),("h_v",128),("w",1),("w_n",24),
   ("w_p",288),("w_q",192)]

def width (fs : List (String × Nat)) : Nat := fs.foldl (fun n f => n+f.2) 0

def field (fs : List (String × Nat)) (e : Expr) (name : String) : Expr :=
  let offset := (fs.reverse.takeWhile (fun f => f.1 != name)).foldl (fun n f => n+f.2) 0
  let w := ((fs.find? (fun f => f.1 == name)).getD ("",0)).2
  slice e offset w

private def anyEvent (e : Expr) : Expr :=
  ["d","s","g","e","u_mxu","u_q","u_vpu","h","w"].foldl
    (fun a n => bor a (bnot (eq (field perfFields e n) (lit 0 (((perfFields.find? (fun f => f.1 == n)).getD ("",1)).2))))) (lit 0 1)

private def items (e : Expr) : Expr := Id.run do
  let f := field bundleFields e
  let mut xs := [f "g"]
  xs := xs ++ (List.range 16).map (bit (f "e"))
  for u in List.range 5 do
    xs := xs ++ [bit (f "s") u,band (bit (f "s") u) (bit (f "s_x") u)]
  for (n,k) in [("d",3),("u_mxu",5),("u_q",2),("u_vpu",2),("h",5),("w",10),("w",7)] do
    xs := xs ++ List.replicate k (f n)
  return pack xs

private def record (cur : Expr) (i : Nat) : Expr := Id.run do
  let f := field bundleFields cur
  let cyc := f "cyc"
  let val := fun j v => pack [v,lit 0 24,lit j 4,lit 11 4]
  if i == 0 then return pack [cyc,lit 0 20,f "g_slot",lit 0 4,lit 3 4]
  if i < 17 then return pack [cyc,lit 0 20,lit (i-1) 4,lit 0 4,lit 4 4]
  if i < 27 then
    let u := (i-17)/2
    if (i-17)%2 == 1 then return pack [slice (f "s_rdy") (32*u) 32,lit 0 28,lit 10 4]
    return pack [cyc,slice (f "s_dt") (16*u) 16,lit u 4,slice (f "s_slot") (4*u) 4,lit 0 4,lit 2 4]
  if i == 27 then return pack [cyc,f "d_pc",lit 0 4,f "d_slot",lit 0 4,lit 1 4]
  if i < 30 then return pack [slice (f "d_ow") (52*(i-28)) 52,lit (i-28) 1,lit 0 7,lit 9 4]
  if i == 30 || i == 35 || i == 37 then
    return pack [cyc,lit 0 16,lit (if i == 30 then 1 else if i == 35 then 2 else 3) 4,lit 0 8,lit 5 4]
  if i < 35 then return val (i-31) (slice (f "u_mxu_v") (32*(i-31)) 32)
  if i == 36 then return val 0 (f "u_q_v")
  if i == 38 then return val 0 (f "u_vpu_v")
  if i == 39 then return pack [cyc,lit 0 28,lit 8 4]
  if i < 44 then return val (i-40) (slice (f "h_v") (32*(i-40)) 32)
  if i == 44 || i == 54 then return pack [cyc,f "w_n",lit 0 4,lit (if i == 44 then 6 else 7) 4]
  if i < 54 then return val (i-45) (slice (f "w_p") (32*(i-45)) 32)
  return val (i-55) (slice (f "w_q") (32*(i-55)) 32)

-- Match the reference's balanced per-bit AND/OR reduction.
private def orTree : Nat → List Expr → Expr
  | 0, xs => xs.foldl bor (lit 0 64)
  | fuel+1, xs =>
    if xs.length <= 1 then xs.headD (lit 0 64)
    else orTree fuel ((List.range ((xs.length+1)/2)).map fun i =>
      bor (xs[2*i]?.getD (lit 0 64)) (xs[2*i+1]?.getD (lit 0 64)))

private def memory (name : String) (aw dw : Nat) (wa wd we ra : Expr) (rd : String) : CircuitM Unit := do
  let m ← getModule
  setModule <| (m.addWire {name := rd,ty := .bitVector dw}).addStmt
    (.memory name aw dw "clk" wa wd we ra rd true)

def build (c : Config) : Except String Module := do
  if c.depth < 2 || c.queueDepth < 2 || !powerOfTwo c.depth || !powerOfTwo c.queueDepth || c.window > 16 then
    throw "trace requires power-of-two DEPTH/QD >= 2 and WIN <= 16"
  return runModule "otpu_trace_sparkle" do
    clocks
    let pw := width perfFields
    let bw := width bundleFields
    let ld := clog2 c.depth
    let qw := clog2 c.queueDepth
    for (n,w) in [("pf",pw),("en",1),("stop",1),("clear",1),("raddr",32)] do
      let _ ← input n w
    let stopped ← wire "stopped" 1 (band (ref "stop") (bnot (eq (slice (ref "count") ld (32-ld)) (lit 0 (32-ld)))))
    let _ ← clocked "pr" pw (lit 1 1) (ref "pf")
    let _ ← clocked "pr_en" 1 (lit 1 1) (ref "en")
    let _ ← clocked "pr_any" 1 (lit 1 1) (band (bnot (ref "rst")) (anyEvent (ref "pf")))
    let p := field perfFields (ref "pr")
    let mut n := ["d","g","u_mxu","u_q","u_vpu","h"].foldl
      (fun a k => add a (pack [p k,lit 0 5])) (lit 0 6)
    n := add n (pack [lit 0 1,p "w",lit 0 4])
    for i in List.range 5 do n := add n (pack [bit (p "s") i,lit 0 5])
    for i in List.range 16 do n := add n (pack [bit (p "e") i,lit 0 5])
    let _ ← clocked "ev_n" 6 (lit 1 1) n
    let discard := bor (ref "rst") (bor (ref "clear") (bor (bnot (ref "pr_en")) stopped))
    let ev := Expr.concat (perfFields.map fun (k,w) =>
      if ["d","s","g","e","u_mxu","u_q","u_vpu","h","w"].contains k then mux discard (lit 0 w) (p k) else p k)
    let _ ← clocked "ev" pw (lit 1 1) ev
    let e := field perfFields (ref "ev")
    let evAny ← wire "ev_any" 1 (anyEvent (ref "ev"))
    let mut dt := []
    let mut sx := []
    for u in List.range 5 do
      let delta ← wire s!"dt{u}" 32 (sub (e "cyc") (slice (e "s_rdy") (32*u) 32))
      let sat := bnot (lt delta (lit 65535 32))
      dt := dt ++ [mux sat (lit 65535 16) (slice delta 0 16)]
      sx := sx ++ [sat]
    let nb ← wire "nb" bw (.concat (bundleFields.map fun (k,_) =>
      match k with
      | "g_slot" | "d_slot" => slice (e k) 0 4
      | "e" | "d_pc" => slice (e k) 0 16
      | "s_slot" => pack ((List.range 5).map fun u => slice (e k) (5*u) 4)
      | "s_dt" => pack dt
      | "s_x" => pack sx
      | "d_ow" => pack [e "d_w1",e "d_w2",e "d_w3",e "d_op"]
      | "u_q_v" => e "u_q_frz"
      | "u_vpu_v" => e "u_vpu_frz"
      | "w_n" => slice (e k) 0 24
      | _ => e k))
    let push ← wire "push" 1 (band evAny (lt (ref "q_n") (lit c.queueDepth (qw+1))))
    memory "qm" qw bw (ref "q_t") nb push (ref "q_hd") "qh"
    let first ← wire "first" 61 (band (ref "pend") (add (bnot (ref "pend")) (lit 1 61)))
    let last ← wire "last" 1 (eq (band (ref "pend") (sub (ref "pend") (lit 1 61))) (lit 0 61))
    let load ← wire "load" 1 (band last (bnot (eq (ref "q_n") (lit 0 (qw+1)))))
    let rec ← wire "rec" 64 (orTree 6 ((List.range 61).map fun i => mux (bit first i) (record (ref "cur") i) (lit 0 64)))
    let wr ← wire "wr" 1 (band (ref "r_v") (bnot stopped))
    memory "mem" ld 64 (ref "wp") (ref "r_rec") wr (slice (ref "raddr") 0 ld) "rd"
    let _ ← clocked "rd_q" 64 (lit 1 1) (ref "rd")
    let _ ← clocked "rdata_q" 64 (lit 1 1) (ref "rd_q")
    let active := bnot (bor (ref "rst") (ref "clear"))
    let _ ← clocked "cur" bw (band active load) (ref "qh")
    let _ ← clocked "r_rec" 64 active rec
    let reset := bor (ref "rst") (ref "clear")
    for (name,w,v) in [
      ("q_t",qw,mux push (add (ref "q_t") (lit 1 qw)) (ref "q_t")),
      ("q_hd",qw,mux load (add (ref "q_hd") (lit 1 qw)) (ref "q_hd")),
      ("q_n",qw+1,sub (add (ref "q_n") (pack [push,lit 0 qw])) (pack [load,lit 0 qw])),
      ("pend",61,mux load (items (ref "qh")) (band (ref "pend") (bnot first))),
      ("r_v",1,bnot (eq (ref "pend") (lit 0 61))),
      ("wp",ld,mux wr (add (ref "wp") (lit 1 ld)) (ref "wp")),
      ("count",32,mux (band wr (bnot (eq (ref "count") (lit 4294967295 32)))) (add (ref "count") (lit 1 32)) (ref "count")),
      ("drop",32,mux (band evAny (bnot push))
        (mux (lt (bnot (pack [ref "ev_n",lit 0 26])) (ref "drop")) (lit 4294967295 32) (add (ref "drop") (pack [ref "ev_n",lit 0 26]))) (ref "drop"))] do
      let _ ← clocked name w (lit 1 1) (mux reset (lit 0 w) v)
    output "rdata" 64 (ref "rdata_q")
    addOutput "count" (.bitVector 32)
    addOutput "drop" (.bitVector 32)
    output "busy" 1 ([band (ref "pr_any") (ref "pr_en"),evAny,bnot (eq (ref "q_n") (lit 0 (qw+1))),bnot (eq (ref "pend") (lit 0 61)),ref "r_v"].foldl bor (lit 0 1))

def toVerilog (c : Config) : Except String String := do
  Backend.withRegisterHints (← build c) [] false false [("qm",.distributed),("mem",.block)]
end OpenTPU.Trace
