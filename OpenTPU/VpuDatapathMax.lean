import OpenTPU.VpuDatapathSupport

/-! The pipelined masked maximum tree and four-stage ARGMAX index conversion.
    Tree stages advance during reset; ARGMAX payload registers hold on reset. -/
namespace OpenTPU.VpuDatapathMax
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.VpuDatapathSupport

def build (c : Config) : Except String Module := do
  validate c
  return runModule "otpu_vpu_max_sparkle" do
    clocks
    for (n,w) in [("en",1),("xa",32*c.lanes),("mask",c.lanes),("m0r",41),("col",16),
      ("mx_have",1),("mx_run",32),("mx_ri",17),("red_act",1),("func",8),("tag",8),("imm",32)] do
      let _ ← input n w
    let lw := clog2 c.lanes
    let mut vs := ((List.range c.lanes).map fun l => FloatConvert.ftz (word (ref "xa") l)).toArray
    let mut hs := ((List.range c.lanes).map fun l => bit (ref "mask") l).toArray
    let mut ix := ((List.range c.lanes).map fun l => lit l lw).toArray
    let mut mm := ref "m0r"
    let mut col := ref "col"
    for j in [:lw] do
      let half := c.lanes / 2^(j+1)
      let mut nv := #[]
      let mut nh := #[]
      let mut ni := #[]
      for l in [:half] do
        let up ← wire s!"max_up{j}_{l}" 1 (bor (bnot hs[l]!)
          (band hs[l+half]! (FloatConvert.greater vs[l+half]! vs[l]!)))
        nv := nv.push (← clocked s!"mxh_v{j}_{l}" 32 (ref "en") (mux up vs[l+half]! vs[l]!))
        nh := nh.push (← clocked s!"mxh_h{j}_{l}" 1 (ref "en") (bor hs[l]! hs[l+half]!))
        ni := ni.push (← clocked s!"mxh_i{j}_{l}" lw (ref "en") (mux up ix[l+half]! ix[l]!))
      vs := nv; hs := nh; ix := ni
      mm ← clocked s!"mxh_m{j}" 41 (ref "en") mm
      col ← clocked s!"mxh_c{j}" 16 (ref "en") col
    let keep := band (ref "mx_have") (bnot (FloatConvert.greater vs[0]! (ref "mx_run")))
    let value ← wire "max_new" 32 (mux keep (ref "mx_run") vs[0]!)
    let idx ← wire "max_index" 17 (mux keep (ref "mx_ri") (add (ext col 1) (ext ix[0]! (17-lw))))
    for i in [1:5] do
      let p := s!"am{i}"
      let old := s!"am{i-1}"
      let valid := if i == 1 then every [ref "red_act",eq (ref "func") (lit 20 8),
        live mm (ref "tag"),rm mm "row_last"] else ref s!"{old}_v"
      reg s!"{p}_v" 1 true [(ref "en",valid)]
      for (n,w,v) in [("l",1,if i == 1 then rm mm "all_last" else ref s!"{old}_l"),
        ("a",20,if i == 1 then rm mm "waddr" else ref s!"{old}_a"),
        ("m",32,if i == 1 then value else ref s!"{old}_m")] do
        reg s!"{p}_{n}" w false [(ref "en",v)]
    reg "am1_i" 17 false [(ref "en",idx)]
    reg "am2_s" 32 false [(ref "en",add (ext (ref "am1_i") 15) (ref "imm"))]
    let prep ← FloatConvert.integerStage1 "argmax_prepare" (ref "am2_s")
    reg "am3_x" 32 false [(ref "en",slice prep 0 32)]
    reg "am3_s" 1 false [(ref "en",bit prep 38)]
    -- The original five-bit count is zero for zero magnitude.
    reg "am3_z" 5 false [(ref "en",slice prep 32 5)]
    let converted ← FloatConvert.integerStage2 "argmax_finish"
      (pack [ref "am3_x",ext (ref "am3_z") 1,ref "am3_s",eq (ref "am3_x") (lit 0)])
    reg "am4_i" 32 false [(ref "en",converted)]
    output "mx_new" 32 value
    output "mx_ni" 17 idx
    output "mxm" 41 mm
    for (n,w) in [("am4_v",1),("am4_l",1),("am4_a",20),("am4_m",32),("am4_i",32)] do
      output s!"o_{n}" w (ref n)

end OpenTPU.VpuDatapathMax
