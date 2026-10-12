import OpenTPU.VpuDatapath

open Sparkle.IR.AST OpenTPU.VpuDatapathSupport

/-- Reject any new dependency rather than silently cutting it. -/
partial def decoderRefs : Expr → Except String (List String)
  | .const _ _ => pure []
  | .ref n => pure [n]
  | .op _ xs | .concat xs => do
    let mut result := []
    for x in xs do result := result ++ (← decoderRefs x)
    pure result
  | .slice x _ _ => decoderRefs x
  | _ => throw "unsupported decoder cone expression"

partial def withoutStream : Expr → Expr
  | .ref "ss_act" => .const 0 1
  | .op op xs => .op op (xs.map withoutStream)
  | .concat xs => .concat (xs.map withoutStream)
  | .slice x hi lo => .slice (withoutStream x) hi lo
  | x => x

/-- Structural projection of the actual builder, never a reimplementation. -/
def decoderCone (full : Module) (interfaces : List Module) (fault : String := "none") : Except String Module := do
  unless ["none", "reset", "update", "stream"].contains fault do throw "unknown fault"
  let isState := fun n => n == "m0" || n == "m0d" || n.startsWith "m0[" || n.startsWith "m0d["
  unless !(full.inputs.any fun p => isState p.name) do throw "state also driven by input"
  for stmt in full.body do
    match stmt with
    | .assign lhs _ =>
      if isState lhs then throw "additional combinational state driver"
    | .register n _ _ _ _ =>
      if isState n && n != "m0" && n != "m0d" then throw "partial state driver"
    | .memory n _ _ _ _ _ _ _ rd _ _ reads =>
      if isState n || isState rd || reads.any (fun p => isState p.2) then
        throw "additional memory state driver"
    | .inst moduleName _ connections =>
      for (port, expr) in connections do
        let refs ← decoderRefs expr
        if refs.any isState then
          let candidates := interfaces.filter fun m => m.name == moduleName
          unless candidates.length == 1 do throw s!"unknown instance touching decoder state: {moduleName}.{port}"
          let interface ← match candidates with | [m] => pure m | _ => throw "ambiguous interface"
          unless (interface.inputs.filter fun p => p.name == port).length == 1 &&
              !(interface.outputs.any fun p => p.name == port) do
            throw "instance may drive decoder state"
  let selected := full.body.filter fun s => match s with
    | .register n _ _ _ _ => n == "m0" || n == "m0d"
    | _ => false
  unless selected.length == 2 do throw "decoder register inventory changed"
  let mut seen := []
  let mut body := []
  for s in selected do
    match s with
    | .register n clk reset d initial =>
      unless clk == "clk" && reset == ("rst", .synchronous) && !seen.contains n do
        throw "unexpected decoder clock/reset or duplicate state"
      seen := n :: seen
      for dependency in (← decoderRefs d) do
        unless ["m0", "m0d", "en", "mi", "ss_act"].contains dependency do
          throw s!"unbound decoder dependency {dependency}"
      let d := if n == "m0d" && fault == "update" then
        Expr.mux (.ref "en") (Expr.xor d (.const 1 28)) d
        else if n == "m0d" && fault == "stream" then withoutStream d else d
      let initial := if n == "m0d" && fault == "reset" then initial + 1 else initial
      body := body ++ [.register n clk reset d initial]
    | _ => throw "unexpected selected statement"
  let inputs := full.inputs.filter fun p => ["clk", "rst", "en", "mi", "ss_act"].contains p.name
  unless inputs.length == 5 do throw "decoder input inventory changed"
  let wires := full.wires.filter fun p => ["m0", "m0d"].contains p.name
  unless wires.length == 2 do throw "decoder wire inventory changed"
  let outputs := wires.map fun p => {p with name := "o_" ++ p.name}
  pure {
    name := "gate"
    inputs := inputs
    outputs := outputs
    wires := wires
    body := body ++ wires.map (fun p => .assign ("o_" ++ p.name) (.ref p.name))
  }

/-- These guards execute in the compiled generator against the real module. -/
def decoderProjectionGuards (full : Module) (interfaces : List Module) : Except String Unit := do
  let changed := full.body.map fun s => match s with
    | .register "m0d" clk reset _ initial => .register "m0d" clk reset (.ref "unproved_dependency") initial
    | other => other
  let faults := [
    {full with body := changed},
    {full with body := full.body ++ [.assign "m0" (.const 0 1)]},
    {full with body := full.body ++ [.inst "otpu_vpu_lanes_sparkle" "bad" [("mo", .ref "m0d")]]},
    {full with body := full.body ++ [.inst "unknown" "bad" [("x", .ref "m0")]]}]
  for faulty in faults do
    match decoderCone faulty interfaces with
    | .error _ => pure ()
    | .ok _ => throw "projection mutation accepted"
