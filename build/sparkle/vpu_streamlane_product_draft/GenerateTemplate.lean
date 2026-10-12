import OpenTPU.VpuLanes
import OpenTPU.SeComposite

-- Fresh output path supplied by staged driver. Not executed or compiled.
def main (args : List String) : IO Unit := do
  let [path] := args | throw (IO.userError "one fresh output path required")
  let lanes ← IO.ofExcept (OpenTPU.VpuLanes.build ⟨8,2,true⟩)
  let composite ← IO.ofExcept (OpenTPU.SeComposite.toVerilog ⟨8,21,3,2,true⟩)
  let emit := Sparkle.Backend.Verilog.toVerilog
  IO.FS.writeFile path (emit lanes ++ composite ++
    emit {OpenTPU.Float.multiply 2 with name := "otpu_vpu_datapath_mul"} ++
    emit {OpenTPU.Float.addition 4 with name := "otpu_vpu_datapath_add"})
