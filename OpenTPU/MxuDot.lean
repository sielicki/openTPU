import OpenTPU.MxuConfig
import OpenTPU.MxuHelpers

/-! Native integer MXU datapaths, with the original three pipeline architectures.
    The module boundary is S0 -> S4: metadata, weight scales, and exact signed
    integer sums. Arithmetic registers, operand skews, and cascade boundaries are
    explicit Sparkle registers, including the DSP-paired tree's packed products. -/
namespace OpenTPU.MxuDot
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit
open OpenTPU.Mxu OpenTPU.MxuHelpers

private def mul (a b : Expr) : Expr := .op .mul [a,b]
private def zext (a : Expr) (width extra : Nat) : Expr := pack [slice a 0 width, lit 0 extra]
private def delay (name : String) (width count : Nat) (en value : Expr) : CircuitM Expr := do
  let mut x := value
  for k in [:count] do x ← clocked s!"{name}{k}" width en x
  return x

private def weight (d i : Nat) (w hb wf : Expr) : Expr :=
  mux (eq wf (lit 0 2)) (slice w (i*8) 8)
    (decode4 (mux hb (slice w (d*4+i*4) 4) (slice w (i*4) 4)) (eq wf (lit 2 2)))

private def fixed (name : String) (width : Nat) (value : Expr) : CircuitM Expr := do
  let m ← getModule
  setModule <| m.addWire {name,ty := .bitVector width}
  emitAssign name value
  return ref name

private def sum (width : Nat) (values : List Expr) := values.foldl add (lit 0 width)

/-- Input metadata layout: o,h,q[1:0],first,last,v from LSB to MSB. -/
def build (c : Config) : Module := runModule "otpu_mxu_dot_sparkle" do
  clockOnly
  let en ← input "en_c" 1
  let a0 ← input "a0" (c.columns*c.d*8)
  let w0 ← input "w0" (c.d*8)
  let m0 ← input "m0" 7
  let ws0 ← input "ws0" 32
  let ws0h ← input "ws0h" 32
  let mb0 ← input "mb0" 16
  let mb0h ← input "mb0h" 16
  let hi0 ← input "hi0" c.columns
  let chi ← input "c_hi" c.columns
  let wf0 ← input "wf0" 2
  let pr0 ← input "pr0" 1
  let sw := c.sumWidth
  let d := c.d
  let cols := c.columns
  let cl := c.chainLength
  let mut results : List Expr := []
  if c.implementation == 0 then
    let ar ← clocked "ar" (cols*d*8) en a0
    let gs := min (d/4) 16
    let ng3 := d/gs
    let gpb := ng3/4
    for p in [:cols/2] do
      let split := band pr0 (band (bnot (bit hi0 (2*p))) (bit hi0 (2*p+1)))
      let hb := mux pr0 (bit hi0 (2*p)) (bit m0 1)
      let _ ← clocked s!"sp{p}" 1 en split
      let _ ← clocked s!"pkr{p}" 44 en (mux split (lit 0x10001000 44) (lit 32513 44))
      for i in [:d] do
        let b8 ← wire s!"b8_{p}_{i}" 8 (weight d i w0 (bor split hb) wf0)
        let lo8 := weight d i w0 (lit 0 1) wf0
        let sign5 := mux (bit b8 7) (lit 31 5) (lit 0 5)
        let upper := mux split (sub (slice lo8 0 5) (zext (bit b8 7) 1 4)) sign5
        let _ ← clocked s!"wr{p}_{i}" 18 en (pack [b8, sign5, upper])
      for q in [:d/2] do
        let pa := fun i => add (sext (pack [lit 0 16, slice ar ((2*p*d+i)*8) 8]) 24 25)
          (sext (slice ar (((2*p+1)*d+i)*8) 8) 8 25)
        let pae ← wire s!"pa{p}_{q}" 25 (pa (2*q))
        let _ ← clocked s!"pme{p}_{q}" 44 en (mul (sext pae 25 44) (sext (ref s!"wr{p}_{2*q}") 18 44))
        let _ ← clocked s!"pe{p}_{q}" 44 en (add (ref s!"pme{p}_{q}") (ref s!"pkr{p}"))
        let pao ← clocked s!"pao{p}_{q}" 25 en (pa (2*q+1))
        let wro ← clocked s!"wro{p}_{q}" 18 en (ref s!"wr{p}_{2*q+1}")
        let pmo ← clocked s!"pmo{p}_{q}" 44 en (mul (sext pao 25 44) (sext wro 18 44))
        let _ ← clocked s!"pq{p}_{q}" 44 en (add pmo (ref s!"pe{p}_{q}"))
    if cols % 2 == 1 then
      for i in [:d] do
        let wr ← clocked s!"wrl{i}" 8 en (weight d i w0 (mux pr0 (bit hi0 (cols-1)) (bit m0 1)) wf0)
        let _ ← clocked s!"odd_pr{i}" 16 en (mul (sext (slice ar (((cols-1)*d+i)*8) 8) 8 16) (sext wr 8 16))
      for q in [:d/2] do
        let prq ← clocked s!"prq{q}" 17 en (add (sext (ref s!"odd_pr{2*q}") 16 17) (sext (ref s!"odd_pr{2*q+1}") 16 17))
        let _ ← clocked s!"prq2_{q}" 17 en prq
    let mb3 ← delay "mbpipe" 16 5 en mb0
    let mb3h ← delay "mbhpipe" 16 5 en mb0h
    for j in [:cols] do
      for g in [:ng3] do
        let sp := ref s!"sp{j/2}"
        let init := if j % 2 == 0 then lit 0 20 else
          mux sp (lit ((2^20-gs/2*4096)%2^20) 20) (lit ((2^20-gs/2*32513)%2^20) 20)
        let mut t := init
        for k in [:gs/2] do
          let pq := ref s!"pq{j/2}_{gs/2*g+k}"
          let v := if j % 2 == 1 then
            zext (mux sp (zext (slice pq 0 13) 13 3) (slice pq 0 16)) 16 4
          else if j+1 < cols then
            mux sp (sext (slice pq 29 15) 15 20) (sext (slice pq 16 17) 17 20)
          else sext (ref s!"prq2_{gs/2*g+k}") 17 20
          t := add t v
        let _ ← clocked s!"s3_{j}_{g}" 20 en t
      let mut vs : List Expr := []
      for b in [:4] do
        let t := sum sw ((List.range gpb).map fun g => sext (ref s!"s3_{j}_{b*gpb+g}") 20 sw)
        let multiplier := zext (mux (bit hi0 j) (slice mb3h (b*4) 4) (slice mb3 (b*4) 4)) 4 (sw-4)
        let v ← clocked s!"v{j}_{b}" sw en (mul t multiplier)
        vs := vs ++ [v]
      let s4 ← clocked s!"s4_{j}" sw en (sum sw vs)
      results := results ++ [s4]
  else if c.implementation == 1 then
    for i in [:d] do
      let ws ← delay s!"wsk{i}_" 8 (i%cl) en (slice w0 (i*8) 8)
      for j in [:cols] do
        let ask ← delay s!"ask{j}_{i}_" 8 (i%cl) en (slice a0 ((j*d+i)*8) 8)
        let mreg ← clocked s!"mreg{j}_{i}" 16 en (mul (sext ask 8 16) (sext ws 8 16))
        let _ ← clocked s!"preg{j}_{i}" 24 en (add
          (if i%cl == 0 then lit 0 24 else ref s!"preg{j}_{i-1}") (sext mreg 16 24))
    let ng := d/cl
    for j in [:cols] do
      let mut t1s : List Expr := []
      for u in [:(ng+3)/4] do
        let vs := ((List.range 4).filter fun v => 4*u+v < ng).map fun v =>
          sext (ref s!"preg{j}_{(4*u+v)*cl+cl-1}") 24 32
        let t1 ← clocked s!"t1_{j}_{u}" 32 en (sum 32 vs)
        t1s := t1s ++ [t1]
      let mut t2s : List Expr := []
      for u in [:(ng+15)/16] do
        let vs := ((List.range 4).filter fun v => 4*u+v < (ng+3)/4).map fun v => ref s!"t1_{j}_{4*u+v}"
        let t2 ← clocked s!"t2_{j}_{u}" 32 en (sum 32 vs)
        t2s := t2s ++ [t2]
      let t := if ng ≤ 1 then sext (ref s!"preg{j}_{cl-1}") 24 32
        else if ng ≤ 4 then ref s!"t1_{j}_0" else sum 32 t2s
      results := results ++ [slice t 0 sw]
  else
    let cls := min (d/4) cl
    let cps := d/4/cls
    let cpa := (cps+1)/2
    for i in [:d] do
      let wd ← clocked s!"wd{i}" 16 en (pack [weight d i w0 (bit m0 1) wf0, weight d i w0 (lit 1 1) wf0])
      let wc ← delay s!"wsk{i}_" 16 (i%cls) en wd
      let _ ← fixed s!"wc0_{i}" 16 wc
      for j in [1:cols] do
        let _ ← clocked s!"wc{j}_{i}" 16 en (ref s!"wc{j-1}_{i}")
    for j in [:cols] do
      for i in [:d] do
        let ask ← delay s!"ask{j}_{i}_" 8 (i%cls+j) en (slice a0 ((j*d+i)*8) 8)
        let wc := ref s!"wc{if j == 0 then 0 else j-1}_{i}"
        let stem := s!"pe{j}_{i}_"
        let br ← clocked (stem++"br") 8 en ask
        let selr ← clocked (stem++"selr") 1 en (bit chi j)
        let wl ← if j == 0 then pure (slice wc 0 8) else clocked (stem++"wlr") 8 en (slice wc 0 8)
        let wh ← if j == 0 then pure (slice wc 8 8) else clocked (stem++"whr") 8 en (slice wc 8 8)
        let m ← clocked (stem++"m") 16 en (mul (sext br 8 16) (sext (mux selr wh wl) 8 16))
        let pn := add (if i%cls == 0 then lit 0 24 else ref s!"preg{j}_{i-1}") (sext m 16 24)
        if i%cls == cls-1 then
          let _ ← fixed s!"preg{j}_{i}" 24 pn
        else
          let _ ← clocked s!"preg{j}_{i}" 24 en pn
      let mbd ← delay s!"mbd{j}_" 16 (cls+1+j) en (mux (bit hi0 j) mb0h mb0)
      let mut vs : List Expr := []
      let mr ← clocked s!"ce{j}_mr" 16 en mbd
      for b in [:4] do
        let ends := fun lo hi => ((List.range cps).filter fun k => lo ≤ k && k < hi).map fun k =>
          ref s!"preg{j}_{(b*cps+k)*cls+cls-1}"
        let ar ← clocked s!"ce{j}_ar{b}" 24 en (sum 24 (ends 0 cpa))
        let dr ← clocked s!"ce{j}_dr{b}" 24 en (sum 24 (ends cpa cps))
        let v ← clocked s!"ce{j}_v{b}" 48 en (mul (add (sext ar 24 48) (sext dr 24 48)) (zext (slice mr (b*4) 4) 4 44))
        vs := vs ++ [v]
      let sr ← clocked s!"ce{j}_s" sw en (slice (sum 48 vs) 0 sw)
      let s4 ← delay s!"dsk{j}_" sw (cols-1-j) en sr
      results := results ++ [s4]
  let m4 ← delay "meta" 7 c.dotLatency en m0
  let ws4 ← delay "scale" 32 c.dotLatency en ws0
  let ws4h ← delay "scaleh" 32 c.dotLatency en ws0h
  output "s4" (cols*sw) (pack results)
  output "m4" 7 m4
  output "ws4" 32 ws4
  output "ws4h" 32 ws4h

end OpenTPU.MxuDot
