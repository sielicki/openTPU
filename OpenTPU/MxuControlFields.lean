import OpenTPU.MxuConfig
import OpenTPU.SeqLogic
import OpenTPU.SeqWindow

/-! Packed fields shared by the native MXU command queue and drain. Field lists
    run from least-significant to most-significant, matching the reference structs. -/
namespace OpenTPU.MxuControlFields
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.SeqLogic
open OpenTPU.Mxu

abbrev Fields := List (String × Nat)

/-- Stable cross-builder names for the controller's combinational signals. -/
def signal (name : String) (bits : Nat) (value : Expr) : CircuitM Expr := do
  let m ← getModule
  setModule <| (m.addWire {name,ty := .bitVector bits}).addStmt (.assign name value)
  return ref name

def mw (c : Config) := clog2 c.columns + 1
def nl (c : Config) := min c.lanes c.columns
def rf (c : Config) := if c.implementation == 2 then 64 else 32
def rfw (c : Config) := clog2 (rf c)
def fg (c : Config) := min ((c.d * 8 + 35) / 36) 4
def fgLo (c : Config) (g : Nat) : Nat :=
  let fc := (c.d * 8 + 35) / 36
  min (36 * (g * (fc / fg c) + min g (fc % fg c))) (c.d * 8)

def queueFields (c : Config) : Fields :=
  [("dfl",1),("dnl",mw c),("g1",1),("gs",32),("Ml",mw c),("G",8),
   ("jo",c.columns*32),("asa",32),("wf",2),("go",1),("asc",1),("rmax",1),
   ("acc",1),("unit",1),("run",mw c),("ab",8),("M",8),("mxo",32),
   ("hi",c.columns),("pair",1),("KBa",16),("KB",16),("tz",1),("total",32),("out",32)]

def rmwFields (c : Config) : Fields :=
  [("col",nl c*8),("nv",nl c*32),("ad",nl c*32),("m",nl c),("v",1)]

def width (fs : Fields) : Nat := fs.foldl (fun n f => n+f.2) 0

def get (fs : Fields) (x : Expr) (field : String) : Expr := Id.run do
  let mut offset := 0
  for (name,w) in fs do
    if name == field then return slice x offset w
    offset := offset+w
  return lit 0 1

def put (fs : Fields) (x : Expr) (field : String) (value : Expr) : Expr :=
  pack (fs.map fun (name,_) => if name == field then value else get fs x name)

def construct (fs : Fields) (values : List (String × Expr)) : Expr :=
  pack (fs.map fun (name,w) => ((values.find? fun item => item.1 == name).map Prod.snd).getD (lit 0 w))

def selectArray (values : List Expr) (idx : Expr) (iw w : Nat) :=
  SeqWindow.select values idx iw w

/-- Unpacked memory reads retain the reference synthesis mux tree: a missing
    branch collapses to its populated sibling. Valid addresses select exactly
    their element; this also preserves the chosen out-of-range lowering for
    non-power-of-two arrays without constraining the controller state. -/
def readArray (values : List Expr) (idx : Expr) (iw w : Nat) : Expr := Id.run do
  let mut level := (List.range (2^iw)).map fun i => values[i]?
  for k in [:iw] do
    let a := level.toArray
    level := (List.range (a.size/2)).map fun i =>
      match a[2*i]!,a[2*i+1]! with
      | some lo,some hi => some (mux (bit idx k) hi lo)
      | some lo,none => some lo
      | none,some hi => some hi
      | none,none => none
  return level.head!.getD (lit 0 w)

def minimum (a b : Expr) := mux (lt a b) a b
def le (a b : Expr) := bnot (lt b a)

def lanes (c : Config) (count : Expr) : Expr :=
  pack ((List.range (nl c)).map fun k => lt (lit k (mw c)) count)

def drainStep (_c : Config) (left run : Expr) : Expr :=
  pack [minimum run left,le left run]

def drainAddresses (c : Config) (name : String) (j : Expr) : CircuitM Expr := do
  let mut values : List Expr := []
  for k in [:nl c] do
    let sum ← signal s!"{name}_index{k}" (mw c) (add j (lit k (mw c)))
    let valid := lt (add (zext j (mw c) 32) (lit k)) (lit c.columns)
    values := values ++ [mux valid (selectArray ((List.range c.columns).map fun i => ref s!"dad{i}")
      sum (mw c) 32) (lit 0)]
  return pack values

def command (c : Config) (cmd : Expr) : CircuitM Expr := do
  let pair ← signal "cmd_pair" 1 (band (flag cmd 6) (nz (slice cmd 228 2) 2))
  let kb := slice (word cmd 4) 16 16
  let kb1 ← signal "cmd_kb1" 16 (add kb (lit 1 16))
  let kba ← signal "cmd_KBa" 16 (mux pair (.op .shr [kb1,lit 1]) kb)
  let total ← signal "cmd_total" 32 (.op .mul [zext (slice (word cmd 4) 0 16) 16 32,zext kba 16 32])
  let tz ← signal "cmd_tz" 1 (any [eq (slice (word cmd 4) 0 16) (lit 0 16),
    eq kb (lit 0 16),band pair (eq kb (lit 65535 16))])
  let m := slice (word cmd 6) 16 8
  let ors := slice (word cmd 6) 0 16
  let mut runExpr := lit 1 (mw c)
  for t in (List.range (clog2 c.lanes)).reverse do
    runExpr := mux (bit ors t) (lit (min (c.lanes / 2^t) (nl c)) (mw c)) runExpr
  let run ← signal "cmd_run" (mw c) runExpr
  -- M is byte-sized. This constant table handles arbitrary column counts without
  -- adding a division primitive or silently imposing power-of-two columns.
  let mut groupExpr := lit 1 8
  for g in [2:(255+c.columns-1)/c.columns+1] do
    groupExpr := mux (lt (lit ((g-1)*c.columns) 8) m) (lit g 8) groupExpr
  let groups ← signal "cmd_groups" 8 groupExpr
  let offset ← signal "cmd_group_offset" 32 (.op .mul [sub (zext groups 8 32) (lit 1),lit c.columns])
  let ml ← signal "cmd_Ml" (mw c) (sub (zext m 8 32) offset)
  let jo := (List.range c.columns).map fun j => Expr.op .mul [lit j,zext ors 16 32]
  return construct (queueFields c)
    [("out",word cmd 3),("total",total),("tz",tz),("KB",kb),("KBa",kba),("pair",pair),
     ("hi",pack ((List.range c.columns).map fun j => band pair (le (zext m 8 32) (lit j)))),
     ("mxo",add (word cmd 3) (.op .mul [zext m 8 32,zext ors 16 32])),("M",m),("run",run),
     ("ab",slice (word cmd 6) 24 8),("unit",flag cmd 0),("wf",slice cmd 228 2),
     ("acc",flag cmd 1),("rmax",flag cmd 2),("asc",flag cmd 3),("asa",word cmd 2),
     ("jo",pack jo),("G",groups),("Ml",ml),("gs",.op .mul [lit c.columns,zext ors 16 32]),
     ("g1",eq groups (lit 1 8)),("dnl",minimum run ml),("dfl",le ml run)]

end OpenTPU.MxuControlFields
