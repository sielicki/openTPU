import OpenTPU.VpuDatapathMax
open Sparkle.IR.AST

def mutate (m : Module) (fault : String) : Except String Module := do
  unless ["none","output","hold","init"].contains fault do throw "unknown fault"
  let mut hits := 0
  let mut body := []
  for stmt in m.body do
    match stmt with
    | .assign "mx_new" value =>
      if fault == "output" then
        hits := hits + 1
        body := body ++ [.assign "mx_new" (Expr.xor value (.const 1 32))]
      else body := body ++ [stmt]
    | .register "mxh_v0_0" clk rst (.op .mux [.ref "en", value, .ref "mxh_v0_0"]) initial =>
      if fault == "hold" then
        hits := hits + 1
        body := body ++ [.register "mxh_v0_0" clk rst value initial]
      else if fault == "init" then
        unless initial == 0 do throw "initial target changed"
        hits := hits + 1
        body := body ++ [.register "mxh_v0_0" clk rst (.op .mux [.ref "en", value, .ref "mxh_v0_0"]) 1]
      else body := body ++ [stmt]
    | _ => body := body ++ [stmt]
  unless hits == (if fault == "none" then 0 else 1) do throw "mutation target changed"
  pure {m with body := body}
