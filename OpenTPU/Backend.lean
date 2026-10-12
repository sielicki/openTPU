import OpenTPU.Circuit

/-! Physical lowering of independent Sparkle byte banks into wide, byte-enabled
    RAMs. This changes the Verilog storage layout, not the native circuit model.
    Only banks with identical clock, depth, write address, and read address are
    combined. Each byte retains its own write enable and data. -/
namespace OpenTPU.Backend
open Sparkle.IR.AST Sparkle.Backend.Verilog

/-- Synthesis constraints attached to native register declarations. -/
inductive RegisterAttribute where
  | keep
  | noShiftRegister
  | asyncRegister
  | maxFanout (limit : Nat)
  deriving Repr, BEq

abbrev RegisterHints := List (String × List RegisterAttribute)

/-- Synthesis implementation preference for a native memory declaration. -/
inductive MemoryStyle where
  | distributed
  | block
  deriving Repr, BEq

abbrev MemoryHints := List (String × MemoryStyle)

/-- Preserve a physical boundary around a native module instance. -/
inductive InstanceAttribute where
  | keepHierarchy
  deriving Repr, BEq

abbrev InstanceHints := List (String × List InstanceAttribute)

inductive ParamValue where
  | nat (value : Nat)
  | bits (width value : Nat)
  | string (value : String)
  deriving Repr, BEq

abbrev InstanceParameters := List (String × List (String × ParamValue))

private def safeIdentifier (s : String) : Bool :=
  let letter := fun c : Char => ('a' ≤ c && c ≤ 'z') || ('A' ≤ c && c ≤ 'Z') || c == '_'
  !s.isEmpty && letter s.toList.head! && s.toList.all (fun c => letter c || ('0' ≤ c && c ≤ '9') || c == '$')

private def parameterText : ParamValue → String
  | .nat n => toString n
  | .bits w n => s!"{w}'d{n}"
  | .string s =>
    let escaped := (s.replace "\\" "\\\\").replace "\"" "\\\""
    "\"" ++ escaped ++ "\""

private def instanceAttributeText : InstanceAttribute → String
  | .keepHierarchy => "keep_hierarchy = \"yes\""

private def memoryStyleText : MemoryStyle → String
  | .distributed => "distributed"
  | .block => "block"

private def attributeText : RegisterAttribute → String
  | .keep => "keep = \"true\""
  | .noShiftRegister => "shreg_extract = \"no\""
  | .asyncRegister => "ASYNC_REG = \"TRUE\""
  | .maxFanout n => s!"max_fanout = {n}"

structure ByteBank where
  name : String
  addressWidth : Nat
  clock : String
  writeAddress : Expr
  writeData : Expr
  writeEnable : Expr
  readAddress : Expr
  readData : String
  deriving BEq, Inhabited

private def byteBank? : Stmt → Option ByteBank
  | .memory name aw 8 clock wa wd we ra rd true [] [] =>
      some ⟨name, aw, clock, wa, wd, we, ra, rd⟩
  | _ => none

private def compatible (a b : ByteBank) : Bool :=
  a.addressWidth == b.addressWidth && a.clock == b.clock &&
    a.writeAddress == b.writeAddress && a.readAddress == b.readAddress

/-- Bound the physical word to 32 bytes, the ACT RAM's existing piece width. -/
def groups (m : Module) : Array (Array ByteBank) := Id.run do
  let mut result : Array (Array ByteBank) := #[]
  for stmt in m.body do
    if let some bank := byteBank? stmt then
      if let some idx := result.findIdx? (fun g => g.size < 32 && compatible g[0]! bank) then
        result := result.modify idx (·.push bank)
      else result := result.push #[bank]
  return result.filter (·.size > 1)

private def zeroInitialization (name : String) (addressWidth : Nat) : String :=
  s!"`ifndef SYNTHESIS\n    initial for (integer a=0; a<{2^addressWidth}; a=a+1) {sanitizeName name}[a] = '0;\n`endif\n"

private def emitGroup (m : Module) (group : Array ByteBank) (zeroMemories : Bool) : String := Id.run do
  let first := group[0]!
  -- Original bank/read-data names are unique. Reserve generated suffixes too.
  let occupied := (m.inputs ++ m.outputs ++ m.wires).map (·.name) ++
    m.body.filterMap (fun s => match s with | .memory n .. => some n | _ => none)
  let mut suffix := 0
  while occupied.contains s!"{first.name}_packed{suffix}" ||
      occupied.contains s!"{first.readData}_packed{suffix}" do
    suffix := suffix + 1
  let name := sanitizeName s!"{first.name}_packed{suffix}"
  let rd := sanitizeName s!"{first.readData}_packed{suffix}"
  let widthOf := fun name => ((m.inputs ++ m.outputs ++ m.wires).find? (fun p => p.name == name)).map (·.ty.bitWidth)
  let emit := emitExpr widthOf
  let mut text := s!"    logic [{group.size*8-1}:0] {name} [0:{2^first.addressWidth-1}];\n" ++
    s!"    wire [{group.size*8-1}:0] {rd} = {name}[{emit first.readAddress}];\n" ++
    s!"    always_ff @(posedge {sanitizeName first.clock}) begin\n"
  for i in [:group.size] do
    let b := group[i]!
    text := text ++ s!"        if ({emit b.writeEnable}) {name}[{emit first.writeAddress}][{i*8} +: 8] <= {emit b.writeData};\n"
  text := text ++ "    end\n"
  for i in [:group.size] do
    text := text ++ s!"    assign {sanitizeName group[i]!.readData} = {rd}[{i*8} +: 8];\n"
  if zeroMemories then text := text ++ zeroInitialization name first.addressWidth
  return text

/-- Reuse Sparkle's expression, port and register emitters. Memory grouping is a
    structural IR pass: it never reads or translates a SystemVerilog source. -/
private def emit (m : Module) (hints : RegisterHints) (packBytes zeroMemories : Bool)
    (memoryHints : MemoryHints := []) (instanceHints : InstanceHints := [])
    (instanceParameters : InstanceParameters := []) : String := Id.run do
  let gs := if packBytes then groups m else #[]
  if (gs.isEmpty && hints.isEmpty && memoryHints.isEmpty && instanceHints.isEmpty && instanceParameters.isEmpty && !zeroMemories) || m.isPrimitive then return toVerilog m
  let names := gs.toList.flatMap (fun g => g.toList.map (·.name))
  let ports := (m.inputs ++ m.outputs).map (·.name)
  let inits := m.body.filterMap fun s => match s with
    | .register output _ _ _ init => some (output, init)
    | _ => none
  let mut result := s!"// Generated by Sparkle HDL; native physical lowering\nmodule {sanitizeName m.name}{emitParameterList m.parameters} ({emitPortList m.inputs m.outputs});\n"
  for wire in m.wires.filter (fun w => !ports.contains w.name) do
    if let some (_, attrs) := hints.find? (fun (name, _) => name == wire.name) then
      result := result ++ "    (* " ++ String.intercalate ", " (attrs.map attributeText) ++ " *)\n"
    result := result ++ emitWireDecls [wire] "    " inits
  for stmt in m.body do
    if let some bank := byteBank? stmt then
      if names.contains bank.name then continue
    if let .memory name .. := stmt then
      if let some (_, style) := memoryHints.find? (fun (n, _) => n == name) then
        result := result ++ s!"    (* ram_style = \"{memoryStyleText style}\" *)\n"
    if let .inst _ name _ := stmt then
      if let some (_, attrs) := instanceHints.find? (fun (n, _) => n == name) then
        result := result ++ "    (* " ++ String.intercalate ", " (attrs.map instanceAttributeText) ++ " *)\n"
    let widths := if packBytes then m.inputs ++ m.outputs ++ m.wires else m.wires
    if let .inst moduleName name connections := stmt then
      if let some (_, params) := instanceParameters.find? (fun (n, _) => n == name) then
        let widthOf := fun name => ((m.inputs ++ m.outputs ++ m.wires).find? (·.name == name)).map (·.ty.bitWidth)
        let args := params.map fun (key,value) => s!".{key}({parameterText value})"
        let conns := connections.map fun (port,value) => s!".{sanitizeName port}({emitExpr widthOf value})"
        result := result ++ s!"    {sanitizeName moduleName} #({String.intercalate ", " args}) {sanitizeName name} ({String.intercalate ", " conns});\n"
        continue
    result := result ++ emitStmt stmt "    " widths ++ "\n"
    if zeroMemories then
      if let .memory name aw .. := stmt then result := result ++ zeroInitialization name aw
  for g in gs do result := result ++ emitGroup m g zeroMemories
  return result ++ "endmodule\n"

def toPackedVerilog (m : Module) : String := emit m [] true false

/-- Fail rather than silently dropping an attribute after a register is renamed. -/
def withRegisterHints (m : Module) (hints : RegisterHints)
    (packBytes : Bool := false) (zeroMemories : Bool := false)
    (memoryHints : MemoryHints := []) (instanceHints : InstanceHints := [])
    (instanceParameters : InstanceParameters := []) : Except String String := do
  if m.isPrimitive && !hints.isEmpty then throw s!"{m.name}: cannot annotate a primitive's internal registers"
  let registers := m.body.filterMap fun s => match s with
    | .register name .. => some name
    | _ => none
  let mut seen := []
  for (name, attrs) in hints do
    if !registers.contains name then throw s!"{m.name}: attribute target {name} is not a register"
    if !(m.wires.any (·.name == name)) || (m.inputs ++ m.outputs).any (·.name == name) then
      throw s!"{m.name}: attribute target {name} must have an internal declaration"
    if seen.contains name then throw s!"{m.name}: duplicate attribute target {name}"
    if attrs.isEmpty then throw s!"{m.name}: empty attributes for {name}"
    for attr in attrs do
      if attr == .maxFanout 0 then throw s!"{m.name}: max_fanout must be positive"
    seen := name :: seen
  if m.isPrimitive && !memoryHints.isEmpty then
    throw s!"{m.name}: cannot annotate a primitive's internal memories"
  let memories := m.body.filterMap fun s => match s with
    | .memory name .. => some name
    | _ => none
  let packed := if packBytes then (groups m).toList.flatMap (fun g => g.toList.map (·.name)) else []
  let mut seenMemories := []
  for (name, _) in memoryHints do
    if !memories.contains name then throw s!"{m.name}: attribute target {name} is not a memory"
    if seenMemories.contains name then throw s!"{m.name}: duplicate memory attribute target {name}"
    if packed.contains name then throw s!"{m.name}: cannot attach a memory attribute to packed byte bank {name}"
    seenMemories := name :: seenMemories
  if m.isPrimitive && !instanceHints.isEmpty then
    throw s!"{m.name}: cannot annotate a primitive's internal instances"
  let instances := m.body.filterMap fun s => match s with
    | .inst _ name _ => some name
    | _ => none
  let mut seenInstances := []
  for (name, attrs) in instanceHints do
    if !instances.contains name then throw s!"{m.name}: attribute target {name} is not an instance"
    if seenInstances.contains name then throw s!"{m.name}: duplicate instance attribute target {name}"
    if attrs.isEmpty then throw s!"{m.name}: empty instance attributes for {name}"
    seenInstances := name :: seenInstances
  if m.isPrimitive && !instanceParameters.isEmpty then
    throw s!"{m.name}: cannot parameterize a primitive's internal instances"
  let mut seenParameters := []
  for (name, params) in instanceParameters do
    if !instances.contains name then throw s!"{m.name}: parameter target {name} is not an instance"
    if seenParameters.contains name then throw s!"{m.name}: duplicate parameter instance {name}"
    if params.isEmpty then throw s!"{m.name}: empty parameters for {name}"
    let mut keys := []
    for (key,value) in params do
      if !safeIdentifier key then throw s!"{m.name}: unsafe parameter identifier {key}"
      if keys.contains key then throw s!"{m.name}: duplicate parameter {name}.{key}"
      match value with
      | .bits w n => if w == 0 || n ≥ 2^w then throw s!"{m.name}: invalid bit parameter {name}.{key}"
      | .string s => if !(s.toList.all fun c => ' ' ≤ c && c ≤ '~') then
          throw s!"{m.name}: parameter string {name}.{key} must contain printable ASCII"
      | .nat _ => pure ()
      keys := key :: keys
    seenParameters := name :: seenParameters
  return emit m hints packBytes zeroMemories memoryHints instanceHints instanceParameters

/-- Memory attributes are attached to IR declarations, never patched into HDL. -/
def withMemoryHints (m : Module) (hints : MemoryHints) : Except String String :=
  withRegisterHints m [] false false hints

/-- Instance attributes attach to validated IR instances, not HDL text matches. -/
def withInstanceHints (m : Module) (hints : InstanceHints) : Except String String :=
  withRegisterHints m [] false false [] hints

end OpenTPU.Backend
