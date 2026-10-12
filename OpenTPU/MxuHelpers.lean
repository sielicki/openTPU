import OpenTPU.Circuit

/-! Native MXU storage, skew, systolic multiply/accumulate, and column-end circuits.
    All arithmetic is explicit bit-vector arithmetic; no RTL is loaded by these builders. -/
namespace OpenTPU.MxuHelpers
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

def sext (x : Expr) (fromWidth toWidth : Nat) : Expr :=
  if toWidth ≤ fromWidth then slice x 0 toWidth
  else .concat ((List.replicate (toWidth-fromWidth) (bit x (fromWidth-1))) ++ [x])

def ram (width depth : Nat) : Module := runModule "otpu_ram_sdp_sparkle" do
  clockOnly
  let we ← input "we" 1
  let wa ← input "wa" (clog2 depth)
  let wd ← input "wd" width
  let re ← input "re" 1
  let ra ← input "ra" (clog2 depth)
  let data ← emitMemoryComboRead "mem" (clog2 depth) width "clk" wa wd we ra
  let rd ← clocked "rd_reg" width re (.ref data)
  output "rd" width rd

def skew (width depth : Nat) : Module := runModule "otpu_skew_sparkle" do
  clockOnly
  let en ← input "en" 1
  let d ← input "d" width
  let mut value := d
  for i in [:depth] do
    value ← clocked s!"r{i}" width en value
  output "q" width value

/-- FIRST removes the incoming cascade; LAST bypasses the P register and terminates
    PCOUT. WREG independently enables the weight input registers. -/
def pe (first last weightRegister : Bool) : Module := runModule "otpu_pe_sparkle" do
  clockOnly
  let en ← input "en" 1
  let act ← input "act" 8
  let wlo ← input "wlo" 8
  let whi ← input "whi" 8
  let sel ← input "sel" 1
  let pcin ← input "pcin" 48
  let br ← clocked "br" 8 en act
  let selr ← clocked "selr" 1 en sel
  let wlr ← clocked "wlr" 8 en wlo
  let whr ← clocked "whr" 8 en whi
  let wl := if weightRegister then wlr else wlo
  let wh := if weightRegister then whr else whi
  let m ← clocked "m" 16 en (.op .mul [sext br 8 16, sext (mux selr wh wl) 8 16])
  let pn ← wire "pn" 24 (add (if first then lit 0 24 else slice pcin 0 24) (sext m 16 24))
  let p ← if last then pure pn else clocked "p_reg" 24 en pn
  output "p" 24 p
  output "pcout" 48 (if last then lit 0 48 else sext p 24 48)

def colend (sumWidth : Nat) : Module := runModule "otpu_colend_sparkle" do
  clockOnly
  let en ← input "en" 1
  let a ← input "a" 96
  let d ← input "d" 96
  let mb ← input "mb" 16
  let ar ← clocked "ar" 96 en a
  let dr ← clocked "dr" 96 en d
  let mr ← clocked "mr" 16 en mb
  let mut values : List Expr := []
  for b in [:4] do
    let av := sext (slice ar (b*24) 24) 24 48
    let dv := sext (slice dr (b*24) 24) 24 48
    let multiplier := pack [slice mr (b*4) 4, lit 0 44]
    let v ← clocked s!"v{b}" 48 en (.op .mul [add av dv, multiplier])
    values := values ++ [v]
  let sum := values.foldl add (lit 0 48)
  let s ← clocked "s_reg" sumWidth en (slice sum 0 sumWidth)
  output "s" sumWidth s

/-- Decode int4 or sign/magnitude E2M1 (scaled by two) without a lookup ROM. -/
def decode4 (code fp : Expr) : Expr := Id.run do
  let mut value := pack [code, lit 0 4]
  for (c, v) in [(5,6),(6,8),(7,12),(8,0),(9,255),(10,254),(11,253),
                 (12,252),(13,250),(14,248),(15,244)] do
    value := mux (eq code (lit c 4)) (lit v 8) value
  return mux fp value (sext code 4 8)

def decode : Module := runModule "otpu_mxu_decode4_sparkle" do
  let code ← input "code" 4
  let fp ← input "fp" 1
  output "value" 8 (decode4 code fp)

end OpenTPU.MxuHelpers
