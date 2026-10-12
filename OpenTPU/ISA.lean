import Std
import Std.Tactic.BVDecide

/-! openTPU's fixed-width instruction interface. Words and addresses wrap at 32 bits,
    just as they do in otpu_pkg and the Python ISA. -/
namespace OpenTPU

abbrev Word := BitVec 32

structure Command where
  op : BitVec 8 := 0
  flags : BitVec 8 := 0
  w1 : Word := 0
  w2 : Word := 0
  w3 : Word := 0
  w4 : Word := 0
  w5 : Word := 0
  w6 : Word := 0
  w7 : Word := 0
  deriving Repr, BEq, Inhabited

namespace Opcode
abbrev nop : BitVec 8 := 0x00
abbrev halt : BitVec 8 := 0x01
abbrev li : BitVec 8 := 0x02
abbrev addi : BitVec 8 := 0x03
abbrev loop : BitVec 8 := 0x04
abbrev bar : BitVec 8 := 0x05
abbrev rld : BitVec 8 := 0x06
abbrev waitw : BitVec 8 := 0x07
abbrev ld : BitVec 8 := 0x10
abbrev st : BitVec 8 := 0x11
abbrev dstep : BitVec 8 := 0x12
abbrev stream : BitVec 8 := 0x13
abbrev mm : BitVec 8 := 0x20
abbrev qact : BitVec 8 := 0x21
abbrev qst : BitVec 8 := 0x22
abbrev vop : BitVec 8 := 0x30
abbrev gather : BitVec 8 := 0x40
end Opcode

/-- The packed `cmd_t` ABI, MSB first. -/
def Command.pack (c : Command) : BitVec 240 :=
  c.op ++ c.flags ++ c.w1 ++ c.w2 ++ c.w3 ++ c.w4 ++ c.w5 ++ c.w6 ++ c.w7

def Command.unpack (bits : BitVec 240) : Command :=
  { op := bits.extractLsb' 232 8, flags := bits.extractLsb' 224 8,
    w1 := bits.extractLsb' 192 32, w2 := bits.extractLsb' 160 32,
    w3 := bits.extractLsb' 128 32, w4 := bits.extractLsb' 96 32,
    w5 := bits.extractLsb' 64 32, w6 := bits.extractLsb' 32 32,
    w7 := bits.extractLsb' 0 32 }

/-- The Lean command layout loses no information across the hardware boundary. -/
theorem Command.unpack_pack (c : Command) : Command.unpack c.pack = c := by
  cases c
  simp only [Command.pack, Command.unpack, Command.mk.injEq]
  bv_decide

/-- RLD float-to-integer conversion: truncate, flush subnormals, saturate to the sentinel. -/
def rldF2i (x : Word) : Word :=
  let e := (x.extractLsb' 23 8).toNat
  let m : Word := 0x800000 ||| (x &&& 0x7fffff)
  if e < 127 then 0
  else if e ≥ 158 then 0x80000000
  else
    let v := if e ≥ 150 then m <<< (e - 150) else m >>> (150 - e)
    if x.getLsbD 31 then -v else v

end OpenTPU
