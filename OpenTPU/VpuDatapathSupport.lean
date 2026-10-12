import OpenTPU.VpuIssue
import OpenTPU.FloatConvert
import OpenTPU.Float

namespace OpenTPU.VpuDatapathSupport
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit
abbrev Config := VpuIssue.Config

def validate (c : Config) : Except String Unit := do
  if !powerOfTwo c.lanes || c.lanes < 2 || c.lanes > 16 || c.compositeLanes == 0 then
    throw "VPU datapath requires power-of-two LANES in 2..16 and positive CL (reference max tree requires LANES >= 2)"
def cbw (c : Config) := clog2 (256/c.lanes)
def mw (c : Config) := 102+c.lanes+cbw c
def rma (c : Config) : Bool := 64/c.lanes >= 8
def nll (c : Config) := if c.comp8 then 0 else c.issueLanes
def nsx (c : Config) := if c.comp8 then 1 else 10

def declared (name : String) (width : Nat) : CircuitM Expr := do
  let m ← getModule
  setModule <| m.addWire {name,ty := .bitVector width}
  return ref name

def signal (name : String) (width : Nat) (value : Expr) : CircuitM Expr := do
  let q ← declared name width
  emitAssign name value
  return q

def delay (name : String) (cycles width : Nat) (value : Expr) : CircuitM Expr := do
  let mut q := value
  for i in [:cycles] do q ← clocked s!"{name}_{i}" width (ref "en") q
  return q

def ext (x : Expr) (extra : Nat) := if extra == 0 then x else pack [x,lit 0 extra]
def every (xs : List Expr) := xs.foldl band (lit 1 1)
def any (xs : List Expr) := xs.foldl bor (lit 0 1)
def word (x : Expr) (l : Nat) := slice x (32*l) 32

def field (c : Config) (x : Expr) (f : String) : Expr :=
  let b := cbw c
  let (lo,w) := match f with
    | "col" => (0,16) | "cb" => (16,b) | "fill" => (16+b,1)
    | "dot" => (17+b,1) | "sq" => (18+b,1) | "sub" => (19+b,8)
    | "final" => (27+b,1) | "first" => (28+b,1) | "all_last" => (29+b,1)
    | "row_last" => (30+b,1) | "waddr" => (31+b,20) | "mask" => (51+b,c.lanes)
    | "imm" => (51+b+c.lanes,32) | "bmode" => (83+b+c.lanes,2)
    | "func" => (85+b+c.lanes,8) | "tag" => (93+b+c.lanes,8)
    | _ => (101+b+c.lanes,1)
  slice x lo w

def reductionMeta (c : Config) (x : Expr) := pack
  (["sub","final","first","all_last","row_last","waddr","tag","v"].map (field c x))
def rm (x : Expr) (f : String) :=
  let (lo,w) := match f with
    | "sub" => (0,8) | "final" => (8,1) | "first" => (9,1)
    | "all_last" => (10,1) | "row_last" => (11,1) | "waddr" => (12,20)
    | "tag" => (32,8) | _ => (40,1)
  slice x lo w

def live (x tag : Expr) := band (rm x "v") (eq (rm x "tag") tag)
def laneY (c : Config) (m xb : Expr) (l : Nat) :=
  mux (eq (field c m "bmode") (lit 3 2)) (field c m "imm")
    (mux (eq (field c m "bmode") (lit 1 2)) (word xb 0) (word xb l))

def arithmetic (name : String) (multiply : Bool) (a b : Expr) : CircuitM Expr := do
  let y ← declared s!"{name}_y" 32
  emitInstance (if multiply then "otpu_vpu_datapath_mul" else "otpu_vpu_datapath_add") name
    [("clk",ref "clk"),("en",ref "en"),("a",a),("b",b),("y",y)]
  return y

def mma (name : String) (a b c e : Expr) (dual : Bool) : CircuitM Expr := do
  let ab ← arithmetic s!"{name}_ab" true a b
  let cd ← if dual then arithmetic s!"{name}_ce" true c e else delay s!"{name}_c" 2 32 c
  arithmetic s!"{name}_sum" false ab cd

end OpenTPU.VpuDatapathSupport
