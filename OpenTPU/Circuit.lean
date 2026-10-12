import Sparkle.IR.Builder
import Sparkle.Backend.Verilog

/-! Small native Sparkle netlist combinators. Configuration loops run in Lean at
    elaboration time; the result consists only of gates, registers, and RAMs. -/
namespace OpenTPU.Circuit
open Sparkle.IR.Type Sparkle.IR.AST Sparkle.IR.Builder
open CircuitM

abbrev ref := Expr.ref
def lit (v : Nat) (w : Nat := 32) : Expr := .const v w
def eq (a b : Expr) := Expr.eq a b
def add (a b : Expr) := Expr.add a b
def sub (a b : Expr) := Expr.sub a b
def band (a b : Expr) := Expr.and a b
def bor (a b : Expr) := Expr.or a b
def bnot (a : Expr) := Expr.not a
def lt (a b : Expr) := Expr.lt_u a b
def mux (p a b : Expr) := Expr.mux p a b
def bit (e : Expr) (n : Nat) := Expr.slice e n n
def slice (e : Expr) (lo width : Nat) := Expr.slice e (lo + width - 1) lo
/-- Pack least-significant field first. -/
def pack (xs : List Expr) : Expr := .concat xs.reverse

def wire (name : String) (width : Nat) (value : Expr) : CircuitM Expr := do
  let w ← makeWire name (.bitVector width) (named := true)
  emitAssign w value
  return .ref w

def input (name : String) (width : Nat) : CircuitM Expr := do
  addInput name (.bitVector width)
  -- The backend uses m.wires for expression-width lookup, including scalar
  -- part-select elimination; port declarations are filtered from internal wires.
  let m ← getModule
  setModule (m.addWire { name, ty := .bitVector width })
  return .ref name

def output (name : String) (width : Nat) (value : Expr) : CircuitM Unit := do
  addOutput name (.bitVector width)
  emitAssign name value

/-- Fixed names allow register feedback. Later enabled updates take priority.
    Non-reset registers hold during reset, matching openTPU's clocked RTL. -/
def reg (name : String) (width : Nat) (reset : Bool)
    (updates : List (Expr × Expr)) (initial : Int := 0) : CircuitM Unit := do
  let next := updates.foldl (fun old (enable, value) => mux enable value old) (ref name)
  let next := if reset then next else mux (ref "rst") (ref name) next
  let m ← getModule
  setModule <| (m.addWire { name, ty := .bitVector width }).addStmt
    (.register name "clk" ((if reset then "rst" else "no_reset"), .synchronous) next initial)

def clocks : CircuitM Unit := do
  addInput "clk" .bit
  addInput "rst" .bit
  let m ← getModule
  setModule <| (m.addWire { name := "no_reset", ty := .bit }).addStmt (.assign "no_reset" (lit 0 1))

/-- A clock domain with no reset pin, as used by the arithmetic and RAM pipelines. -/
def clockOnly : CircuitM Unit := do
  addInput "clk" .bit
  let m ← getModule
  setModule <| (m.addWire { name := "no_reset", ty := .bit }).addStmt (.assign "no_reset" (lit 0 1))

/-- An unreset clock-enabled register. Inputs are sampled on the edge, so a RAM
    read feeding this register observes the memory before that edge's writes. -/
def clocked (name : String) (width : Nat) (enable value : Expr) : CircuitM Expr := do
  let m ← getModule
  setModule <| (m.addWire { name, ty := .bitVector width }).addStmt
    (.register name "clk" ("no_reset", .synchronous)
      (mux enable value (ref name)) 0)
  return ref name

/-- Verilog's $clog2 for positive configuration values. -/
def clog2 (n : Nat) : Nat := (n - 1).log2 + if n > 1 then 1 else 0

def powerOfTwo (n : Nat) : Bool := n > 0 && n &&& (n - 1) == 0

end OpenTPU.Circuit
