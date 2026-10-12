import OpenTPU.SeMicrocode
import OpenTPU.SeHelpers
import OpenTPU.Float
import OpenTPU.Backend

/-! Native composite-function loop, metadata/control pipelines, operand muxes,
    and range reduction. Arithmetic may be external or instantiated natively. -/
namespace OpenTPU.SeComposite
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

structure Config where
  lanes : Nat := 8
  metadata : Nat := 64
  stages : Nat := 3
  lookAhead : Nat := 2
  external : Bool := true
  deriving Repr

def Config.period (c : Config) := c.stages*7+4
def Config.metaWidth (c : Config) := c.metadata+c.lanes+7
def Config.validate (c : Config) : Except String Unit := do
  if c.lanes == 0 || c.metadata == 0 || c.stages == 0 || c.stages > 2^27 ||
      c.lookAhead == 0 || c.lookAhead >= c.period then
    throw "SE composite requires positive LANES/MW/NS, NS <= 2^27, and 0 < HA < 7*NS+4"

private def delay (name : String) (cycles width : Nat) (value : Expr) : CircuitM Expr := do
  let mut q := value
  for i in [:cycles] do
    q ← clocked s!"{name}_{i}" width (ref "en") q
  return q

private def declared (name : String) (width : Nat) : CircuitM Expr := do
  let m ← getModule
  setModule <| m.addWire {name,ty := .bitVector width}
  return ref name

private def arithmetic (name : String) (multiply : Bool) (a b : Expr) : CircuitM Expr := do
  let result ← declared s!"{name}_result" 32
  emitInstance (if multiply then "otpu_se_comp_mul" else "otpu_se_comp_add") name
    [("clk",ref "clk"),("en",ref "en"),("a",a),("b",b),("y",result)]
  return result

/-- The reference control registers have unspecified power-up contents. An
    identity operation is a legal initial choice and preserves constant ROM
    bits, avoiding extra flops caused by an all-zero initialization. -/
private def controlRegister (name : String) (value : Expr) : CircuitM Expr := do
  let m ← getModule
  setModule <| (m.addWire {name,ty := .bitVector 105}).addStmt
    (.register name "clk" ("no_reset", .synchronous)
      (mux (ref "en") value (ref name)) (Int.ofNat (SeMicrocode.operation 0 0).encode))
  return ref name

private def passCount (c : Config) (cls : Expr) :=
  SeqWindow.select ((List.range 8).map fun k => lit (SeMicrocode.passCount c.stages k) 4) cls 3 4

private def classOf (c : Config) (cm : Expr) := slice cm (c.metadata+c.lanes+4) 3
private def passOf (c : Config) (cm : Expr) := slice cm (c.metadata+c.lanes) 4
private def nextPass (c : Config) (cm : Expr) := add (passOf c cm) (lit 1 4)
private def continues (c : Config) (cm : Expr) := lt (nextPass c cm) (passCount c (classOf c cm))
private def field (state : Expr) (which : Nat) := slice state (12+32*which) 32
private def offset (stage : Nat) := if stage == 0 then 0 else 10+(stage-1)*7

def build (c : Config) : Except String Module := do
  c.validate
  return runModule "otpu_se_comp_sparkle" do
    clocks
    let en ← input "en" 1
    let iv ← input "in_v" 1
    let cls ← input "in_c" 3
    let ia ← input "in_a" (32*c.lanes)
    let ib ← input "in_b" (32*c.lanes)
    let im ← input "in_m" c.lanes
    let metadata ← input "in_meta" c.metadata
    let sy ← input "st_y" (32*c.lanes*c.stages)
    let ret := ref "ret_r"
    let lp := ref "lp_m"
    let p0 ← wire "p0" 1 (bor iv ret)
    let mi0 ← wire "mi0" c.metaWidth (mux ret
      (pack [slice lp 0 (c.metadata+c.lanes),nextPass c lp,classOf c lp])
      (pack [metadata,im,lit 0 4,cls]))
    reg "vpos" c.period true [(en,pack [p0,slice (ref "vpos") 0 (c.period-1)])]
    reg "cpos" c.period true [(en,pack [band p0 (continues c mi0),slice (ref "cpos") 0 (c.period-1)])]
    output "hold" 1 (bit (ref "cpos") (c.period-c.lookAhead-1))
    output "out_v" 1 (band (bit (ref "vpos") (c.period-1)) (bnot (continues c lp)))
    output "out_m" c.lanes (slice lp c.metadata c.lanes)
    output "out_meta" c.metadata (slice lp 0 c.metadata)

    let mut mi := mi0
    let mut lastMeta := mi0
    let mut controls := #[]
    let mut destinations := #[]
    let mut selections := []
    for s in [:c.stages] do
      selections := selections ++ [if s == 0 then p0 else bit (ref "vpos") (offset s-1)]
      let control ← wire s!"uci{s}" 105
        (if s == 0 then mux ret (ref "uc_rt") (SeMicrocode.rom c.stages 0 cls (lit 0 4))
         else SeMicrocode.rom c.stages s (classOf c mi) (passOf c mi))
      controls := controls.push control
      let cp ← delay s!"cp{s}" 6 7 (pack [passOf c mi,classOf c mi])
      let destination ← controlRegister s!"uco{s}"
        (SeMicrocode.rom c.stages s (slice cp 4 3) (slice cp 0 4))
      destinations := destinations.push destination
      if s == 0 then
        let firstPass := eq (slice cp 0 4) (lit 0 4)
        let _ ← clocked "rr_e" 1 en (band firstPass
          (bor (eq (slice cp 4 3) (lit 1 3)) (eq (slice cp 4 3) (lit 2 3))))
        let _ ← clocked "rr_g" 1 en (band firstPass (eq (slice cp 4 3) (lit 5 3)))
      let mo ← delay s!"md{s}" 7 c.metaWidth mi
      lastMeta ← if s == 0 then delay "mr" 3 c.metaWidth mo else pure mo
      mi := lastMeta
    let _ ← clocked "lp_m" c.metaWidth en lastMeta
    reg "ret_r" 1 true [(en,band (bit (ref "vpos") (c.period-2)) (continues c lastMeta))]
    let _ ← controlRegister "uc_rt" (SeMicrocode.rom c.stages 0 (classOf c lastMeta) (nextPass c lastMeta))
    output "st_sel" c.stages (pack selections)
    for (name,previous) in [("e1","rr_e"),("e2","e1"),("g1","rr_g"),("g2","g1")] do
      let _ ← clocked name 1 en (ref previous)

    let mut as := Array.replicate (c.lanes*c.stages) (lit 0)
    let mut bs := as
    let mut cs := as
    let mut results := []
    for l in [:c.lanes] do
      let x := slice ia (32*l) 32
      let yInput := slice ib (32*l) 32
      let prepared ← SeHelpers.setup s!"setup{l}" cls x
      let mut state ← wire s!"sti{l}_0" 108 (mux ret (ref s!"lp_st{l}") prepared)
      for s in [:c.stages] do
        let u := controls[s]!
        let d := destinations[s]!
        let uses := fun f k => (SeMicrocode.stageUse c.stages s f &&& (1 <<< k)) != 0
        let v := field state 2
        let k1 := field state 1
        let k2 := field state 0
        let a ← wire s!"a{l}_{s}" 32 (mux (eq (slice u 103 2) (lit 1 2)) (if uses 0 1 then k1 else v)
          (mux (eq (slice u 103 2) (lit 2 2)) (if uses 0 2 then k2 else v)
            (mux (eq (slice u 103 2) (lit 3 2)) (if s == 0 && uses 0 3 then x else v) v)))
        let b ← wire s!"b{l}_{s}" 32 (mux (eq (slice u 101 2) (lit 0 2)) (if uses 1 0 then k1 else slice u 64 32)
          (mux (eq (slice u 101 2) (lit 1 2)) (if uses 1 1 then k2 else slice u 64 32) (slice u 64 32)))
        let cv ← wire s!"c{l}_{s}" 32 (mux (eq (slice u 99 2) (lit 1 2)) (if uses 2 1 then k2 else slice u 32 32)
          (mux (eq (slice u 99 2) (lit 2 2)) (if s == 0 && uses 2 2 then FloatConvert.neg yInput else slice u 32 32)
            (slice u 32 32)))
        as := as.set! (s*c.lanes+l) a
        bs := bs.set! (s*c.lanes+l) b
        cs := cs.set! (s*c.lanes+l) cv
        let result ← if c.external then pure (slice sy (32*(s*c.lanes+l)) 32) else do
          let ra ← clocked s!"ra{l}_{s}" 32 en a
          let rb ← clocked s!"rb{l}_{s}" 32 en b
          let rc ← clocked s!"rc{l}_{s}" 32 en cv
          let product ← arithmetic s!"mul{l}_{s}" true ra rb
          let cd ← delay s!"cd{l}_{s}" 2 32 rc
          arithmetic s!"add{l}_{s}" false product cd
        let kd ← delay s!"kd{l}_{s}" 7 76 (slice state 0 76)
        let r ← wire s!"r{l}_{s}" 32 (mux (bit d 96) (FloatConvert.neg result) result)
        let dst := slice d 97 2
        let nextV := mux (eq dst (lit 1 2)) r (if SeMicrocode.usesConstant c.stages s then slice d 0 32 else lit 0)
        let nextK1 := if uses 3 2 then mux (eq dst (lit 2 2)) r (field kd 1) else field kd 1
        let nextK2 := if uses 3 3 then mux (eq dst (lit 3 2)) r (field kd 0) else field kd 0
        let sto ← wire s!"sto{l}_{s}" 108 (pack [slice kd 0 12,nextK2,nextK1,nextV])
        if s == 0 then
          let flags := pack [FloatConvert.greater (lit 0xc2fc0000) nextV,
            bnot (FloatConvert.greater (lit 0x43000000) nextV),lit 0 1]
          let q0 ← clocked s!"q0_{l}" 108 en
            (pack [mux (ref "rr_e") flags (slice sto 0 3),slice sto 3 105])
          let integer ← SeHelpers.rangeFloor s!"rr{l}" (field q0 2)
          let q1 ← clocked s!"q1_{l}" 108 en
            (pack [slice q0 0 3,mux (ref "e1") integer (slice q0 3 9),slice q0 12 96])
          let float ← SeHelpers.integerToFloat s!"i9_{l}" (slice q1 3 9)
          let signed := .concat [Expr.xor (bit float 31) (ref "e2"),slice float 0 31]
          state ← clocked s!"q2_{l}" 108 en
            (pack [slice q1 0 12,mux (bor (ref "e2") (ref "g2")) signed (field q1 0),slice q1 44 64])
        else state := sto
      let lpState ← clocked s!"lp_st{l}" 108 en state
      results := results ++ [SeHelpers.finish (classOf c lp) lpState]
    output "st_a" (32*c.lanes*c.stages) (pack as.toList)
    output "st_b" (32*c.lanes*c.stages) (pack bs.toList)
    output "st_c" (32*c.lanes*c.stages) (pack cs.toList)
    output "st_e" (32*c.lanes*c.stages) (pack (List.replicate (c.lanes*c.stages) (lit 0x3f800000)))
    output "out_d" (32*c.lanes) (pack results)

def registerHints (c : Config) : Backend.RegisterHints :=
  let endpoint := fun name => (name,[Backend.RegisterAttribute.keep,.noShiftRegister])
  [endpoint "mr_2"] ++
  ((List.range c.stages).flatMap fun s => [endpoint s!"cp{s}_5",endpoint s!"md{s}_6"]) ++
  ((List.range c.lanes).flatMap fun l => (List.range c.stages).flatMap fun s =>
    [endpoint s!"kd{l}_{s}_6"] ++ if c.external then [] else [endpoint s!"cd{l}_{s}_1"])

/-- Simulation observers use the actual retained composite state; no new state. -/
private def diagnosticControlCheck (c : Config) (stage : Nat) : String :=
  let table := String.intercalate "\n" <| (List.range 5).flatMap fun ci =>
    (List.range 16).map fun p =>
      s!"      7'd{16*(ci+1)+p}: diagnostic_uc{stage}=105'd{(SeMicrocode.operation (ci+1) (p*c.stages+stage)).encode};"
  let offset := if stage == 0 then 0 else 10+(stage-1)*7
  let extra := if stage == 0 then
    s!" || rr_e != (md0_6[{c.metadata+c.lanes}+:4]==0 && (md0_6[{c.metadata+c.lanes+4}+:3]==1 || md0_6[{c.metadata+c.lanes+4}+:3]==2))"
    else ""
  s!"
  function automatic logic [104:0] diagnostic_uc{stage}(input logic [6:0] cp);
    case(cp)
{table}
      default: diagnostic_uc{stage}=105'd{(SeMicrocode.operation 0 0).encode};
    endcase
  endfunction
  always @(posedge clk)
    if (!rst && vpos[{offset+6}] &&
      (uco{stage} != diagnostic_uc{stage}(md{stage}_6[{c.metadata+c.lanes}+:7]){extra}))
      $fatal(1, \"otpu_se_comp: output control out of step\");
"

/-- Emit original collision, return and control checks in the production core. -/
def withDiagnostics (c : Config) (core : String) : Except String String := do
  let ending := "\nendmodule\n"
  if !core.endsWith ending || (core.splitOn ending).length != 2 then
    throw "SE composite diagnostics require exactly one complete emitted core"
  let diagnostic := s!"
`ifndef SYNTHESIS
  function automatic logic [3:0] diagnostic_n_pass(input logic [2:0] cls);
    case (cls)
      3'd1, 3'd2: return 4'd{((9+c.stages-1)/c.stages)%16};
      3'd3: return 4'd{((6+c.stages-1)/c.stages)%16};
      3'd4, 3'd5: return 4'd{((10+c.stages-1)/c.stages)%16};
      default: return 4'd1;
    endcase
  endfunction
  wire diagnostic_fin = (lp_m[{c.metadata+c.lanes}+:4] + 4'd1 >= diagnostic_n_pass(lp_m[{c.metadata+c.lanes+4}+:3]));
  always @(posedge clk)
    if (!rst && en && in_v && ret_r)
      $fatal(1, \"otpu_se_comp: entry while a chunk returns\");
  always @(posedge clk)
    if (!rst && ret_r != (vpos[{c.period-1}] && !diagnostic_fin))
      $fatal(1, \"otpu_se_comp: ret out of step\");
{String.intercalate "\n" ((List.range c.stages).map (diagnosticControlCheck c))}
`endif
"
  return core.replace ending (diagnostic ++ "endmodule\n")

def toVerilog (c : Config) : Except String String := do
  let core ← build c
  let emit := Sparkle.Backend.Verilog.toVerilog
  let core ← Backend.withRegisterHints core (registerHints c)
  let core ← withDiagnostics c core
  return core ++ if c.external then "" else
    emit { Float.multiply 2 with name := "otpu_se_comp_mul" } ++
    emit { Float.addition 4 with name := "otpu_se_comp_add" }

end OpenTPU.SeComposite
