import Std

/-! Storage-map justification for Backend's byte-bank coalescing. Each original
    bank stores one byte at each address. The physical wide RAM stores all lanes
    at each address. The write step commutes with that transposition for arbitrary
    addresses, byte values, and independent enables; reads commute as well.
    These lemmas specify the lowering's semantic obligation. They do not claim
    to verify the Verilog emitter or the complete activation RAM controller. -/
namespace OpenTPU.MemoryProofs

abbrev Banks (Lane Address : Type) := Lane → Address → BitVec 8
abbrev Wide (Lane Address : Type) := Address → Lane → BitVec 8

def pack (memory : Banks Lane Address) : Wide Lane Address :=
  fun address lane => memory lane address

def writeBanks [DecidableEq Address] (memory : Banks Lane Address)
    (address : Address) (enable : Lane → Bool) (data : Lane → BitVec 8) : Banks Lane Address :=
  fun lane a => if enable lane && decide (a = address) then data lane else memory lane a

def writeWide [DecidableEq Address] (memory : Wide Lane Address)
    (address : Address) (enable : Lane → Bool) (data : Lane → BitVec 8) : Wide Lane Address :=
  fun a lane => if a = address then
    if enable lane then data lane else memory a lane
  else memory a lane

/-- Simultaneous independently masked bank writes equal one wide byte-enabled write. -/
theorem pack_write [DecidableEq Address] (memory : Banks Lane Address)
    (address : Address) (enable : Lane → Bool) (data : Lane → BitVec 8) :
    pack (writeBanks memory address enable data) = writeWide (pack memory) address enable data := by
  funext a lane
  by_cases h : a = address <;> simp [pack, writeBanks, writeWide, h]

/-- Reading before the write observes exactly the same old byte in either layout. -/
theorem read_pack (memory : Banks Lane Address) (address : Address) (lane : Lane) :
    pack memory address lane = memory lane address := rfl

/-- The correspondence is preserved after every transaction in an arbitrary trace. -/
theorem trace_correspondence [DecidableEq Address] (memory : Banks Lane Address)
    (transactions : List (Address × (Lane → Bool) × (Lane → BitVec 8))) :
    pack (transactions.foldl (fun m (a, en, d) => writeBanks m a en d) memory) =
    transactions.foldl (fun m (a, en, d) => writeWide m a en d) (pack memory) := by
  induction transactions generalizing memory with
  | nil => rfl
  | cons transaction rest ih =>
    simp only [List.foldl_cons]
    rw [ih, pack_write]

end OpenTPU.MemoryProofs
