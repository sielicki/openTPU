import OpenTPU.Backend
import OpenTPU.Float
import OpenTPU.ActRam
import OpenTPU.TMem
import OpenTPU.VTree
import OpenTPU.Seq

/-! Physical register and memory constraints from the original hardware. They accompany
    native IR declarations and do not alter circuit behavior or parse RTL. -/
namespace OpenTPU.Physical
open Backend

def paddingHints (n : Nat) : RegisterHints :=
  if n == 0 then [] else [(s!"pad{n-1}", [.keep, .noShiftRegister])]

def addHints (latency : Nat) (duplicate : Bool) : RegisterHints :=
  paddingHints (latency-4) ++ if duplicate then [("result_copy", [.keep])] else []

def actramHints (c : ActRam.Config) : RegisterHints :=
  (["we", "w_row", "w_idx", "w_data", "w_dup", "w_off", "swe", "s_row", "s_blk", "s_data"].flatMap
    fun name => ["i", "h"].map fun stage => (s!"{name}_{stage}", [.noShiftRegister])) ++
  ((List.range c.columns).flatMap fun j =>
    (List.range (c.depth / min c.depth 32)).flatMap fun p =>
      ["wb", "wsel", "wg"].map fun name => (s!"{name}{j}_{p}", [.keep]))

def tmemHints (c : TMem.Config) : RegisterHints :=
  ((List.range (c.lanes*c.writesPerBank)).flatMap fun i =>
    ["pwv", "pwa", "pwd"].map fun name => (s!"{name}{i}", [.maxFanout 16])) ++
  ((List.range c.readPorts).flatMap fun p =>
    if c.generalRead.testBit p then [] else
      (List.range c.lanes).map fun l => (s!"rot{p*c.lanes+l}", [.keep]))

def vtreeHints (c : VTree.Config) : RegisterHints :=
  (List.range c.lanes).map fun k =>
    (s!"pdd{k}_{64/c.lanes/2-2}", [.keep, .noShiftRegister])

def floatMultiply (latency : Nat) : Except String String :=
  withRegisterHints (Float.multiply latency) (paddingHints (latency-2))

def floatAdd (latency : Nat) (duplicate : Bool := false) : Except String String :=
  withRegisterHints (Float.addition latency duplicate) (addHints latency duplicate)

def actram (c : ActRam.Config) : Except String String :=
  withRegisterHints (ActRam.build c) (actramHints c) true true

def tmem (c : TMem.Config) : Except String String :=
  withRegisterHints (TMem.build c) (tmemHints c)

def vtree (c : VTree.Config) : Except String String := do
  let core ← withRegisterHints (VTree.build c) (vtreeHints c)
  let add ← withRegisterHints { Float.addition c.latency with name := s!"otpu_vtree_add_{c.latency}" }
    (addHints c.latency false)
  let duplicate ← if c.lanes == 8 && c.latency == 4 then
    withRegisterHints { Float.addition 4 true with name := "otpu_vtree_add2" } (addHints 4 true)
    else pure ""
  return core ++ add ++ duplicate

def seqMemoryHints : MemoryHints :=
  (List.range 5).map fun u => (s!"cmd_mem{u}", .distributed)

def seq (c : Seq.Config) : Except String String :=
  withMemoryHints (Seq.build c) seqMemoryHints

end OpenTPU.Physical
