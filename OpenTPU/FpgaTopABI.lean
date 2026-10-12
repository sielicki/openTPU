import OpenTPU.FpgaTop

namespace OpenTPU.FpgaTop

private def widthText (w : Nat) := if w == 1 then "" else s!"[{w-1}:0] "

/-- Pure structural shell for external bidirectional pads and named vendor IP.
The native core owns every directed signal and all state. Supply vendor IP and
an independently emitted native otpu_native_sys ABI definition alongside it. -/
def wrapper (c : Config) : Except String String := do
  let bs ← boundaries c
  let parameters := String.intercalate ",\n" (c.parameters.map fun (n,v) => s!"  parameter {n} = 32'd{v}")
  let ports := (externalInputs.map fun (n,w) => "input wire " ++ widthText w ++ n) ++
    (externalOutputs.map fun (n,w) => "output wire " ++ widthText w ++ n) ++
    (externalPads.map fun (n,w) => "inout wire " ++ widthText w ++ n)
  let mut text := "module otpu_fpga_top_ld #(\n" ++ parameters ++ "\n)(\n" ++ String.intercalate ",\n" ports ++ ");\n"
  let checks := c.parameters.map fun (n,v) => s!"({n} != 32'd{v})"
  text := text ++ "initial if(" ++ String.intercalate " || " checks ++ ") $fatal(1, \"FPGA top parameters differ from native elaboration; regenerate\");\n"
  let mut corePins := (externalInputs ++ externalOutputs).map (fun (n,_) => (n,n))
  for b in bs do
    for (n,w) in (b.inputs.map fun p => (p.name,p.width)) ++ b.outputs do
      let signal := b.signal n
      text := text ++ "wire " ++ widthText w ++ signal ++ ";\n"
      corePins := corePins ++ [(signal,signal)]
    let params := if b.name == "u_sys" then
      " #(" ++ String.intercalate "," (c.system.parameters.map fun (n,v) => s!".{n}(32'd{v})") ++ ")" else ""
    let pins := ((b.inputs.map fun p => p.name) ++ b.outputs.map Prod.fst).map (fun n => (n,b.signal n)) ++
      b.pads.map (fun (n,_,padName) => (n,padName)) ++ b.unusedOutputs.map (fun (n,_) => (n,""))
    text := text ++ b.moduleName ++ params ++ " " ++ b.name ++ "(" ++
      String.intercalate "," (pins.map fun (p,s) => "." ++ p ++ "(" ++ s ++ ")") ++ ");\n"
  text := text ++ "otpu_fpga_top_ld_sparkle impl(" ++
    String.intercalate "," (corePins.map fun (p,s) => "." ++ p ++ "(" ++ s ++ ")") ++ ");\nendmodule\n"
  return text

def emitShell (c : Config) : Except String String := do
  return Sparkle.Backend.Verilog.toVerilog (← build c) ++ (← wrapper c)

/-- Typed boundary declarations for structural verification, not vendor models. -/
def boundaryDeclarations (c : Config) : Except String String := do
  let bs ← boundaries c
  let mut names : List String := []
  let mut text := ""
  for b in bs do
    if names.contains b.moduleName then continue
    names := b.moduleName :: names
    let params := if b.name == "u_sys" then
      " #(" ++ String.intercalate "," (c.system.parameters.map fun (n,v) => s!"parameter {n}=32'd{v}") ++ ")" else ""
    let ports := (b.inputs.map fun p => "input wire " ++ widthText p.width ++ p.name) ++
      ((b.outputs ++ b.unusedOutputs).map fun (n,w) => "output wire " ++ widthText w ++ n) ++
      (b.pads.map fun (n,w,_) => "inout wire " ++ widthText w ++ n)
    text := text ++ "(* blackbox *) module " ++ b.moduleName ++ params ++ "(" ++ String.intercalate "," ports ++ ");\nendmodule\n"
  return text
end OpenTPU.FpgaTop
