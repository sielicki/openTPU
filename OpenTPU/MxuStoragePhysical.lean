import OpenTPU.Mxu
import OpenTPU.Backend

/-! Physical storage boundaries retained from the original MXU controller. -/
namespace OpenTPU.MxuStoragePhysical
open Sparkle.IR.AST OpenTPU.Backend OpenTPU.Mxu

def control (c : Config) : Except String String := do
  c.validateWhole
  let m := Mxu.control c
  let registers := (List.range (MxuControlFields.fg c)).flatMap fun g =>
    [(s!"f_tl{g}",[RegisterAttribute.keep]),(s!"f_rdl{g}",[RegisterAttribute.keep])]
  let instances := (List.range (MxuControlFields.fg c)).map fun g =>
    (s!"fifo_group{g}",[InstanceAttribute.keepHierarchy])
  let memories := m.body.filterMap fun stmt => match stmt with
    | .memory name .. =>
      if name.startsWith "_tmp_fifo_scale_" then some (name,MemoryStyle.block)
      else if name.startsWith "_tmp_result_fifo" then some (name,MemoryStyle.distributed)
      else none
    | _ => none
  if memories.length != 4 then throw "mxu: expected one scale and three result FIFO memories"
  withRegisterHints m registers false false memories instances

def fifo (c : Config) (g : Nat) : Except String String :=
  withMemoryHints (MxuControlDatapath.fifoModule c g) [("_tmp_mem_0",.block)]

def emit (c : Config) : Except String String := do
  c.validateWhole
  let groups ← (List.range (MxuControlFields.fg c)).mapM (fifo c)
  let core ← control c
  return String.join groups ++ core

end OpenTPU.MxuStoragePhysical
