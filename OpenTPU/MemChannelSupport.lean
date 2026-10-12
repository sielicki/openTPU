import OpenTPU.AsyncFifo
import OpenTPU.BoardFifo

namespace OpenTPU.MemChannelSupport
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

structure Config where
  idWidth : Nat := 4
  acceleratorDepth : Nat := 64
  xdmaDepth : Nat := 16
  runLength : Nat := 32
  commandDepth : Nat := 32
  dataDepth : Nat := 32
  deriving Repr

def asw (c : Config) := clog2 c.acceleratorDepth
def xsw (c : Config) := clog2 c.xdmaDepth
def aow (c : Config) := asw c + 1
def xow (c : Config) := xsw c + 1
def tw (c : Config) := asw c + 2

def validate (c : Config) : Except String Unit := do
  if c.idWidth == 0 then throw "Memory channel requires positive XDMA ID width"
  if c.acceleratorDepth < 4 || !powerOfTwo c.acceleratorDepth ||
      c.xdmaDepth < 4 || !powerOfTwo c.xdmaDepth then
    throw "Memory channel read FIFOs require power-of-two depths >= 4"
  if c.xdmaDepth > c.acceleratorDepth || c.acceleratorDepth + c.xdmaDepth + 1 > 128 then
    throw "Memory channel requires XRD <= ARD and ARD + XRD + 1 <= 128"
  if c.commandDepth < 2 || !powerOfTwo c.commandDepth || c.dataDepth < 2 || !powerOfTwo c.dataDepth then
    throw "Memory channel output queues require power-of-two depths >= 2"

def declared (name : String) (width : Nat) : CircuitM Unit := do
  let m ← getModule
  setModule (m.addWire {name,ty := .bitVector width})

def signal (name : String) (width : Nat) (value : Expr) : CircuitM Unit := do
  declared name width
  emitAssign name value

def setup (ports : List (String × Nat)) : CircuitM Unit := do
  for (n,w) in ports do let _ ← input n w
  signal "no_reset" 1 (lit 0 1)

/-- A real edge in the named domain; reset is explicit and never gates another domain. -/
def register (name : String) (width : Nat) (clock reset : String)
    (updates : List (Expr × Expr)) (initial : Int := 0) : CircuitM Unit := do
  let value := updates.foldl (fun old (enable,next) => mux enable next old) (ref name)
  declared name width
  let m ← getModule
  setModule (m.addStmt (.register name clock (reset,.synchronous) value initial))

def sample (name : String) (width : Nat) (clock : String) (value : Expr) (initial : Int := 0) :=
  register name width clock "no_reset" [(lit 1 1,value)] initial

def outputs (ports : List (String × Nat)) : CircuitM Unit :=
  for (n,w) in ports do output s!"o_{n}" w (ref n)

def all (xs : List Expr) : Expr := xs.foldl band (lit 1 1)
def any (xs : List Expr) : Expr := xs.foldl bor (lit 0 1)
def nonzero (x : Expr) (w : Nat) := bnot (eq x (lit 0 w))
def extend (x : Expr) (sourceWidth targetWidth : Nat) :=
  if targetWidth == sourceWidth then x else pack [x,lit 0 (targetWidth-sourceWidth)]
def truncAdd (a b : Expr) (w : Nat) := slice (add a b) 0 w
def truncSub (a b : Expr) (w : Nat) := slice (sub a b) 0 w
def gray (x : Expr) (w : Nat) := Expr.xor x (.op .shr [x,lit 1 w])
def binary (x : Expr) (w : Nat) := pack ((List.range w).map fun i =>
  (List.range (w-i)).foldl (fun q j => Expr.xor q (bit x (i+j))) (lit 0 1))
def choose2 (x : Expr) (w : Nat) (index : Expr) := mux index (slice x w w) (slice x 0 w)

end OpenTPU.MemChannelSupport
