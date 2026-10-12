import OpenTPU.ISA
import OpenTPU.Collective
import OpenTPU.ActRam
import OpenTPU.TMem
import OpenTPU.VTree
import OpenTPU.Physical
import OpenTPU.Seq
import OpenTPU.Quant
import OpenTPU.Dma
import OpenTPU.QuantRead
import OpenTPU.QuantWrite
import OpenTPU.QuantScale

open OpenTPU

private def check (ok : Bool) (message : String) : IO Unit :=
  unless ok do throw <| IO.userError message

def main : IO Unit := do
  for n in [:256] do
    let c : Command :=
      { op := BitVec.ofNat 8 n, flags := BitVec.ofNat 8 (255 - n),
        w1 := BitVec.ofNat 32 (n * 0x1020304), w2 := 0xffffffff, w3 := 0x12345678,
        w4 := 0x87654321, w5 := 0x80000000, w6 := 1, w7 := BitVec.ofNat 32 n }
    check (Command.unpack c.pack == c) "command ABI roundtrip"
  for (input, expected) in [(0, 0), (0x80000000, 0), (0x3f7fffff, 0),
      (0x3f800000, 1), (0xbf800000, 0xffffffff), (0x4effffff, 0x7fffff80),
      (0x4f000000, 0x80000000), (0x7f800000, 0x80000000),
      (0x7fc00001, 0x80000000)] do
    check (rldF2i (BitVec.ofNat 32 input) == BitVec.ofNat 32 expected) s!"RLD {input}"
  for s in [1, 2, 4] do
    for l in [1, 4, 8, 16] do
      let cfg : Collective.Config := ⟨s, l⟩
      IO.ofExcept cfg.validate
      let m := Collective.build cfg
      check (m.inputs.length == 6 && m.outputs.length == 6) "collective ports"
  check (match Collective.Config.validate ⟨0, 8⟩ with | .error _ => true | .ok _ => false) "reject empty slices"
  for cfg in [ActRam.Config.mk 32 2 6 8 8, ActRam.Config.mk 96 2 2 8 24,
      ActRam.Config.mk 8 2 4 4 1] do
    IO.ofExcept cfg.validate
  for cfg in [ActRam.Config.mk 32 2 5 8 8, ActRam.Config.mk 32 2 6 0 8,
      ActRam.Config.mk 32 2 6 8 3] do
    check (match cfg.validate with | .error _ => true | .ok _ => false) "reject invalid ACT RAM configuration"
  for cfg in [TMem.Config.mk 4 2 2 2 1 1 0 0 2,
      TMem.Config.mk 64 4 4 3 2 5 7 0 10, ({} : TMem.Config)] do
    IO.ofExcept cfg.validate
  for cfg in [({ lanes := 3 } : TMem.Config), { words := 8 }, { readPorts := 0 },
      { writesPerBank := 0 }, { shareMask := 2 }, { generalWrite := 16 }] do
    check (match cfg.validate with | .error _ => true | .ok _ => false) "reject invalid TMEM configuration"
  for l in [1,2,4,8,16] do
    for a in [4,5,7] do IO.ofExcept (VTree.Config.mk l a).validate
  for cfg in [VTree.Config.mk 0 4, VTree.Config.mk 3 4, VTree.Config.mk 32 4, VTree.Config.mk 8 3] do
    check (match cfg.validate with | .error _ => true | .ok _ => false) "reject invalid VTREE configuration"
  for w in [2,4,8,16,32] do IO.ofExcept (SeqSchedule.validate w)
  for w in [0,1,3,64] do
    check (match SeqSchedule.validate w with | .error _ => true | .ok _ => false)
      "reject invalid sequencer window"
  for cfg in [({} : Seq.Config), { words := 3072, depth := 96, slices := 3, slots := 16 }] do
    IO.ofExcept cfg.validate
  for cfg in [({ words := 8 } : Seq.Config), { words := 24 }, { words := 17 },
      { depth := 0 }, { depth := 33 }, { slices := 0 }, { slots := 3 }] do
    check (match cfg.validate with | .error _ => true | .ok _ => false)
      "reject unsupported sequencer configuration"
  for cfg in [QuantScale.Config.mk 2 4 2, QuantScale.Config.mk 3 5 1, QuantScale.Config.mk 2 7 5] do
    IO.ofExcept cfg.validate
  for cfg in [QuantScale.Config.mk 1 4 2, QuantScale.Config.mk 2 3 2, QuantScale.Config.mk 2 4 0] do
    check (match cfg.validate with | .error _ => true | .ok _ => false)
      "reject invalid quantizer scale configuration"
  for lanes in [4,8,16,32] do
    IO.ofExcept (QuantRead.Config.mk lanes).validate
    IO.ofExcept (QuantWrite.Config.mk lanes).validate
  for lanes in [0,1,2,3,7] do
    check (match (QuantRead.Config.mk lanes).validate with | .error _ => true | .ok _ => false)
      "reject invalid quantizer reader configuration"
    check (match (QuantWrite.Config.mk lanes).validate with | .error _ => true | .ok _ => false)
      "reject invalid quantizer writer configuration"
  for cfg in [Quant.Config.mk 32 4, Quant.Config.mk 96 8, Quant.Config.mk 4 4] do
    IO.ofExcept cfg.validate
  for cfg in [Quant.Config.mk 0 4, Quant.Config.mk 32 3, Quant.Config.mk 33 4] do
    check (match cfg.validate with | .error _ => true | .ok _ => false)
      "reject invalid quantizer configuration"
  for cfg in [Dma.Config.mk 32 8 128 true, Dma.Config.mk 128 4 32 false,
      Dma.Config.mk 128 16 64 false, Dma.Config.mk 4 1 32 false] do
    IO.ofExcept cfg.validate
  for cfg in [Dma.Config.mk 0 8 128 true, Dma.Config.mk 96 8 128 true,
      Dma.Config.mk 32 0 128 true, Dma.Config.mk 32 3 128 true,
      Dma.Config.mk 32 8 16 true, Dma.Config.mk 32 8 96 true,
      Dma.Config.mk 1024 256 128 false] do
    check (match cfg.validate with | .error _ => true | .ok _ => false)
      "reject unsupported DMA configuration"
  let module := Float.addition 4 true
  for hints in [([("missing", [.keep])] : Backend.RegisterHints),
      [("result_copy", [.maxFanout 0])], [("result_copy", [.keep]), ("result_copy", [.keep])]] do
    check (match Backend.withRegisterHints module hints with | .error _ => true | .ok _ => false)
      "reject invalid physical register hints"
  let portRegister := { module with outputs := module.outputs ++ [{ name := "result_copy", ty := .bitVector 32 }] }
  check (match Backend.withRegisterHints portRegister [("result_copy", [.keep])] with
    | .error _ => true | .ok _ => false) "reject hints on filtered port declarations"
  let seq := Seq.build { words := 16, slots := 2 }
  for hints in [([("missing", .distributed)] : Backend.MemoryHints),
      [("cmd_mem0", .distributed), ("cmd_mem0", .block)]] do
    check (match Backend.withMemoryHints seq hints with | .error _ => true | .ok _ => false)
      "reject invalid physical memory hints"
  let annotated ← IO.ofExcept (Physical.seq { words := 16, slots := 2 })
  check ((annotated.splitOn "ram_style = \"distributed\"").length == 6)
    "all five command memories require distributed RAM"
  IO.println "openTPU Lean tests passed"
