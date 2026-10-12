import OpenTPU.SeqLogic

/-! Native DMA stream descriptor decoder. The descriptor and command are
    unrestricted bit vectors; validation and truncation match the hardware. -/
namespace OpenTPU.DmaSetup
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.SeqLogic

structure Outputs where
  config : Expr
  source : Expr
  destination : Expr
  vectors : Expr
  x : Expr
  constants : Expr
  constantStride : Expr
  outputAddress : Expr
  segments : Expr
  rowSegments : Expr
  valid : Expr

private def payload (x : Expr) := Expr.concat [bit x 31,slice x 0 23]
private def scalarOp (op dst a b : Nat) := lit (op ||| (dst <<< 4) ||| (a <<< 7) ||| (b <<< 11)) 24
private def nz (x : Expr) (width : Nat) := bnot (eq x (lit 0 width))

def logic (width : Nat) (command descriptor : Expr) : CircuitM Outputs := do
  let ds := eq (opcode command) (lit 0x12 8)
  let w := word command
  let desc := fun i => slice descriptor (32*i) 32
  let d := fun i => payload (desc i)
  let d0 ← wire "desc0" 24 (d 0)
  let d1 ← wire "desc1" 24 (d 1)
  let d2 ← wire "desc2" 24 (d 2)
  let op5 ← wire "op5" 24 (d 5)
  let op6 ← wire "op6" 24 (d 6)
  let op7 ← wire "op7" 24 (d 7)
  let nops := slice d2 0 4
  let delta ← wire "delta" 1 (every [eq nops (lit 3 4),eq op5 (scalarOp 2 0 8 10),
    eq op6 (scalarOp 1 1 9 0),eq op7 (scalarOp 2 2 1 11)])
  let delta1 ← wire "delta1" 1 (every [eq nops (lit 2 4),eq op5 (scalarOp 1 1 9 8),eq op6 (scalarOp 2 2 1 11)])
  let scale ← wire "scale" 1 (band (eq nops (lit 1 4)) (eq op5 (scalarOp 2 2 9 11)))
  let dot ← wire "dot" 1 (band (eq nops (lit 1 4)) (eq op5 (scalarOp 2 2 8 11)))
  let dm ← wire "dmode" 2 (mux delta (lit 0 2) (mux delta1 (lit 1 2) (mux scale (lit 2 2) (mux dot (lit 3 2) (lit 0 2)))))
  let dmOk := bor delta (bor delta1 (bor scale dot))
  let gk := band (eq (slice d1 7 2) (lit 2 2)) (eq (slice d1 9 3) (lit 0 3))
  let gc := band (eq (slice d1 7 2) (lit 1 2)) (eq (slice d1 9 3) (lit 3 3))
  let go := eq (slice d1 7 2) (lit 3 2)
  let g ← wire "gsource" 2 (mux gk (lit 0 2) (mux gc (lit 1 2) (mux go (lit 2 2) (lit 0 2))))
  let aOk := band (eq (bit d1 0) (bnot (eq dm (lit 2 2))))
    (bor (bnot (bit d1 0)) (band (eq (slice d1 1 2) (lit 0 2))
      (bor (eq (slice d1 3 2) (lit 1 2)) (eq (slice d1 3 2) (lit 2 2)))))
  let safe ← wire "float_safe" 1 (every ((List.range 8).map fun i =>
    let exponent := eq (slice (desc i) 23 8) (lit 0x80 8)
    if i < 5 then exponent else bor (bnot (lt (lit (i-5) 4) nops)) exponent))
  let rows ← wire "rows" 12 (mux ds (slice (w 4) 0 12) (slice d0 0 12))
  let cols ← wire "columns" 12 (mux ds (slice (w 4) 16 12) (slice d0 12 12))
  let ns ← wire "row_segments" 6 (.op .shr [cols,lit (clog2 width)])
  let pad ← wire "padding" 1 (eq ns (lit 8 6))
  let nsPadded ← wire "padded_segments" 6 (mux pad (lit 16 6) ns)
  let cfg ← wire "configuration" 23 (pack [pad,bor ds (bit d1 20),mux ds (lit 0 2) g,
    mux ds (lit 0 2) dm,band (bnot ds) (eq (slice d1 3 2) (lit 2 2)),bor ds (bit d1 0),slice rows 0 9,nsPadded])
  let flags := slice command 224 8
  let ok ← wire "valid" 1 (bor ds (every [safe,dmOk,bor gk (bor gc go),aOk,nz rows 12,
    bnot (lt (lit 256 12) rows),eq (slice cols 0 6) (lit 0 6),nz cols 12,bnot (lt (lit 256 12) cols),
    eq (d 4) (lit 0 24),eq (slice d1 5 2) (lit 1 2),eq (slice d1 12 2) (lit 0 2),
    eq (slice d1 14 3) (lit 1 3),eq (slice d1 17 3) (lit 2 3),
    bor (bnot (bit d1 20)) (eq (slice d1 21 2) (lit 0 2)),bnot (bit d1 23),
    eq (slice d2 4 10) (lit 0 10),bnot (bit flags 1),bnot (bit flags 2),bnot (bit flags 3)]))
  let segments ← wire "segments" 16 (.mul (zext (slice rows 0 9) 9 32) (zext nsPadded 6 32))
  return ⟨cfg, mux ds (w 1) (w 2), mux ds (w 1) (w 3),
    mux ds (w 2) (w 4), mux ds (w 3) (w 5), mux ds (w 5) (w 6),
    mux ds (w 7) (zext (slice (w 1) 16 16) 16 32), mux ds (w 6) (w 7), segments, ns, ok⟩


def build (width : Nat) : Module := runModule "otpu_dma_setup_sparkle" do
  let command ← input "command" 240
  let descriptor ← input "descriptor" 256
  let o ← logic width command descriptor
  for (name,width,value) in [("su_cfg",23,o.config),("su_src",32,o.source),("su_dst",32,o.destination),
      ("su_vec",32,o.vectors),("su_x",32,o.x),("su_k",32,o.constants),("su_ks",32,o.constantStride),
      ("su_out",32,o.outputAddress),("su_nseg",16,o.segments),("su_ns",6,o.rowSegments),("su_ok",1,o.valid)] do
    output name width value

end OpenTPU.DmaSetup
