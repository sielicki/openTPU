import OpenTPU.Circuit
import OpenTPU.Float

/-! Folding isum_64 tree, including the eight-lane two-adder schedule and
    the general shared lane-level schedule. All pipeline stages advance on en. -/
namespace OpenTPU.VTree
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

structure Config where
  lanes : Nat := 8
  latency : Nat := 4
  deriving Repr

def Config.validate (c : Config) : Except String Unit := do
  if !powerOfTwo c.lanes || c.lanes > 16 then
    throw "VTREE: LANES must be a power of two in 1..16"
  if c.latency < 4 then throw "VTREE: LA must be >= 4"

def Config.h (c : Config) (j : Nat) : Nat := (64 / c.lanes) / 2^(j+1)
def Config.issue (c : Config) (j : Nat) : Nat :=
  (List.range j).foldl (fun t k => t - c.h (k+1) +
    (64/c.lanes) * ((c.latency + 2*c.h (k+1) + 64/c.lanes - 1) / (64/c.lanes))) (c.h 0)
def Config.da (c : Config) (j : Nat) := c.issue j - c.issue (j-1) - c.latency
def Config.db (c : Config) (j : Nat) := c.da j - c.h j

private def declared (name : String) (width : Nat) : CircuitM Expr := do
  let m ← getModule
  setModule <| m.addWire { name, ty := .bitVector width }
  return ref name

private def delay (name : String) (n width : Nat) (value : Expr) : CircuitM Expr := do
  let mut q := value
  for i in [:n] do q ← clocked s!"{name}_{i}" width (ref "en") q
  return q

private def resetReg (name : String) (width : Nat) (d : Expr) : CircuitM Expr := do
  reg name width true [(ref "en", d)]
  return ref name

private def adder (c : Config) (name : String) (a b y : Expr) (duplicate : Bool := false) : CircuitM Unit :=
  emitInstance (if duplicate then "otpu_vtree_add2" else s!"otpu_vtree_add_{c.latency}") name
    ([ ("clk", ref "clk"), ("en", ref "en"), ("a", a), ("b", b), ("y", y)] ++
      if duplicate then [("yo", ref "root_copy")] else [])

def build (c : Config) : Module := runModule "otpu_vtree_sparkle" do
  clocks
  let en ← input "en" 1
  let pacc ← input "pacc" (32*c.lanes)
  let cap ← input "cap" 1
  let last ← input "row_last" 1
  let subrow ← input "sub" 8
  let rl := 64/c.lanes
  let lr := clog2 rl
  let lw := clog2 c.lanes
  let ln2 := c.lanes == 8 && c.latency == 4
  let sh2 := !ln2 && lw >= 2 && c.latency % rl != 0
  let dmax := if ln2 then 2 else (List.range (lr-1)).foldl (fun m j => max m (c.da (j+1))) 1
  let dl := c.issue (lr-1) - (rl-1)
  let rd := c.issue (lr-1) + c.latency*(1+lw) - (rl-1) + if ln2 then 2 else 0
  let rsr ← resetReg "rsr" rd (pack [band cap last, slice (ref "rsr") 0 (rd-1)])
  let mut levels := Array.replicate lr (lit 0 1)
  let mut early := Array.replicate lr (lit 0 1)
  levels := levels.set! (lr-1) (bit rsr (dl - if ln2 then 2 else 1))
  for j in [1:lr-1] do
    let dj := c.issue j - (rl - c.h j)
    let strobe := band cap (bnot (lt subrow (lit (rl-c.h j) 8)))
    let sr ← resetReg s!"lv{j}" dj (pack [strobe, slice (ref s!"lv{j}") 0 (dj-1)])
    levels := levels.set! j (bit sr (dj-1))
    early := early.set! j (bit sr (if dj >= 2 then dj-2 else 0))
  let mut tr := #[]
  let mut td1 := #[]
  for k in [:c.lanes] do tr := tr.push (← declared s!"tr{k}" 32)
  for k in [:c.lanes] do
    let input := slice pacc (k*32) 32
    let pdd ← delay s!"pdd{k}" (rl/2-1) 32 input
    let mut td := #[tr[k]!]
    for d in [:dmax] do td := td.push (← clocked s!"td{k}_{d+1}" 32 en td[d]!)
    td1 := td1.push td[1]!
    let mut a := input
    let mut b := input
    if ln2 then
      let lv2n := bit rsr (dl-3)
      let la ← resetReg s!"la{k}" 1 (bor early[1]! lv2n)
      let qb ← clocked s!"qb{k}" 32 en (mux lv2n tr[k]! pdd)
      a := mux la td[2]! input
      b := mux levels[1]! tr[k]! qb
    else
      a ← resetReg s!"pd{k}" 32 pdd
      for j in [1:lr] do
        a := mux levels[j]! td[c.da j]! a
        b := mux levels[j]! td[c.db j]! b
    adder c s!"tree{k}" a b tr[k]!
  let mut xs := #[]
  for k in [:c.lanes] do xs := xs.push (← declared s!"xs{k}" 32)
  let rootCopy ← declared "root_copy" 32
  let mut root := tr[0]!
  let mut laneCollision := lit 0 1
  if ln2 then
    let l1a := bit rsr (dl+c.latency-2)
    let l1b := bit rsr (dl+c.latency-1)
    let l2 := bit rsr (dl+2*c.latency)
    let strobes := [l1b, bit rsr (dl+c.latency), l2, bit rsr (dl+2*c.latency+5)]
    for i in [:4] do
      for j in [i+1:4] do laneCollision := bor laneCollision (band strobes[i]! strobes[j]!)
    for m in [:2] do
      let qa ← clocked s!"ln_qa{m}" 32 en (mux l1a tr[m]! (mux l1b td1[m+2]! xs[m]!))
      let qb ← clocked s!"ln_qb{m}" 32 en (mux l1a tr[m+4]! (mux l1b td1[m+6]! xs[1]!))
      adder c s!"ln{m}" qa (mux l2 xs[m]! qb) xs[m]! (m == 0)
    root := xs[0]!
  else
    let l2 := bit rsr (dl+2*c.latency-1)
    if sh2 then laneCollision := band l2 (bit rsr (dl+c.latency-1))
    let mut xl := #[tr]
    for q in [1:lw+1] do
      let mut row := #[]
      for k in [:c.lanes / 2^q] do
        if sh2 && q == 2 then row := row.push xs[k]!
        else if sh2 && q == 1 && k < c.lanes/4 then
          -- The second operand comes from a later lane of this same level.
          let later := ref s!"xl1_{k+c.lanes/4}"
          adder c s!"lane{q}_{k}" (mux l2 xs[k]! tr[k]!)
            (mux l2 later tr[k+c.lanes/2]!) xs[k]!
          row := row.push xs[k]!
        else
          let y ← declared s!"xl{q}_{k}" 32
          adder c s!"lane{q}_{k}" xl[q-1]![k]! xl[q-1]![k+c.lanes/2^q]! y
          row := row.push y
      xl := xl.push row
    root := xl[lw]![0]!
    emitAssign "root_copy" root
  let rowCollision := band (band cap (bnot (lt subrow (lit (rl/2) 8))))
    (levels.toList.foldl bor (lit 0 1))
  output "schedule_collision" 1 (band (band en (bnot (ref "rst"))) (bor rowCollision laneCollision))
  output "root" 32 root
  output "root_o" 32 rootCopy
  output "root_v" 1 (bit rsr (rd-1))

def wrapper (c : Config) : String := s!"
module otpu_vtree #(parameter int LANES={c.lanes}, LA={c.latency})(
  input logic clk,rst,en, input logic [31:0] pacc [LANES],
  input logic cap,row_last, input logic [7:0] sub,
  output wire [31:0] root,root_o, output wire root_v
);
  initial if(LANES!={c.lanes} || LA!={c.latency}) $fatal(1, \"Sparkle VTREE configuration mismatch\");
  wire [LANES*32-1:0] flat_pacc;
  for(genvar k=0;k<LANES;k++) assign flat_pacc[k*32 +: 32]=pacc[k];
  wire schedule_collision;
  otpu_vtree_sparkle impl(.clk,.rst,.en,.pacc(flat_pacc),.cap,.row_last,.sub,.root,.root_o,.root_v,.schedule_collision);
`ifndef SYNTHESIS
  always @(posedge clk) if(schedule_collision) $fatal(1, \"Sparkle VTREE schedule collision\");
`endif
endmodule
"

end OpenTPU.VTree
