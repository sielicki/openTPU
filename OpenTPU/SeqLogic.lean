import OpenTPU.Circuit

/-! Native combinational stages of the sequencer. All arithmetic has the reference
    ISA's fixed widths, including the 24-bit multiplicands and wrapped intervals.
    These builders are shared by the stage-level proof harness and the controller;
    no reference HDL is read by generation. -/
namespace OpenTPU.SeqLogic
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

def nz (e : Expr) (w : Nat := 32) := bnot (eq e (lit 0 w))
def any (xs : List Expr) := xs.foldl bor (lit 0 1)
def every (xs : List Expr) := xs.foldl band (lit 1 1)
def zext (e : Expr) (src dst : Nat) :=
  if src == dst then e else pack [e, lit 0 (dst - src)]
def shl (e : Expr) (n : Nat) := Expr.op .shl [e, lit n]
def word (c : Expr) (n : Nat) := slice c ((7 - n) * 32) 32
def opcode (c : Expr) := slice c 232 8
def flag (c : Expr) (n : Nat) := bit c (224 + n)
def isOp (c : Expr) (op : Nat) := eq (opcode c) (lit op 8)
def among (e : Expr) (w : Nat) (ns : List Nat) := any (ns.map fun n => eq e (lit n w))
def choose (cases : List (Expr × Expr)) (fallback : Expr) :=
  cases.foldr (fun (cond, val) rest => mux cond val rest) fallback

/-- Unit number, with 32'hffffffff for instructions executed by R or invalid opcodes. -/
def unitOf (op : Expr) : Expr := choose
  [(among op 8 [0x10, 0x11, 0x12, 0x13, 0x07], lit 0),
   (eq op (lit 0x20 8), lit 1), (among op 8 [0x21, 0x22], lit 2),
   (eq op (lit 0x30 8), lit 3), (among op 8 [0x05, 0x40, 0x06], lit 4)]
  (lit 0xffffffff)

/-- Balanced indexed lookup, with zero for indices beyond the supplied entries.
The shape lets register-file users share the same read network. -/
def indexed (xs : List Expr) (idx : Expr) (iw width : Nat) : Expr := Id.run do
  let mut level := (List.range (2^iw)).map fun i => xs[i]?.getD (lit 0 width)
  for k in [:iw] do
    let values := level.toArray
    level := (List.range (values.size / 2)).map fun i =>
      mux (bit idx k) values[2*i+1]! values[2*i]!
  return level.head!

/-- Resolve the packed instruction's register-relative operands. R0 always reads zero. -/
def decode (ir regs : Expr) : CircuitM Expr := do
  let rv := fun idx => indexed ((lit 0) :: ((List.range 15).map fun j =>
    slice regs ((j + 1) * 32) 32)) idx 4 32
  let mut rs := #[]
  for i in [:4] do
    rs := rs.push (← wire s!"decode_r{i}" 32 (rv (slice ir (8 + 4*i) 4)))
  let a := rs[0]!
  let b := rs[1]!
  let c := rs[2]!
  let d := rs[3]!
  let op := slice ir 0 8
  let stream := eq op (lit 0x13 8)
  let offsets := [mux stream (lit 0) a, mux stream a b, mux stream a c,
    mux stream b (lit 0), mux stream c (lit 0), mux stream d (lit 0),
    mux (eq op (lit 0x30 8)) d (lit 0)]
  let mut ws := []
  for (v, i) in offsets.zipIdx do
    ws := ws ++ [← wire s!"decode_w{i+1}" 32 (add (slice ir (32*(i+1)) 32) v)]
  return .concat ([op, slice ir 24 8] ++ ws)

/-- `fpo_t`: four 24-bit multiplicands above four 32-bit factors. -/
def operands (c : Expr) (depth slices : Nat) : CircuitM Expr := do
  let w := word c
  let lo := fun n => zext (slice (w n) 0 16) 16 32
  let hi := fun n => zext (slice (w n) 16 16) 16 32
  let rows8 := zext (slice (w 2) 0 8) 8 32
  let m := zext (slice (w 6) 16 8) 8 32
  let dec := fun e => slice (sub e (lit 1)) 0 24
  let u24 := fun e => slice e 0 24
  let mm := [(dec (lo 4), w 5), (dec (lo 4), w 7), (dec m, lo 6), (u24 m, lo 6)]
  let qa := [(dec rows8, w 3)]
  let qs := [(dec (lo 4), w 5), (dec (lo 4), w 6),
    (dec (Expr.mul (hi 4) (lit depth)), w 7), (u24 (lo 4), hi 4)]
  let vo := [(dec (lo 4), hi 5), (dec (lo 4), lo 6), (dec (lo 4), lo 5)]
  let ds := [(dec (lo 4), hi 4)]
  let ga := [(dec (lo 3), w 4), (lit (slices-1) 24, w 6), (dec (lo 3), w 5)]
  let cases := [(0x20, mm), (0x21, qa), (0x22, qs), (0x30, vo), (0x12, ds), (0x40, ga)]
  let mut aa := []
  let mut ww := []
  for i in [:4] do
    let as := cases.map fun (op, ps) => (isOp c op, (ps[i]?.getD (lit 0 24, lit 0)).1)
    let ws := cases.map fun (op, ps) => (isOp c op, (ps[i]?.getD (lit 0 24, lit 0)).2)
    aa := aa ++ [← wire s!"fp_a{i}" 24 (choose as (lit 0 24))]
    ww := ww ++ [← wire s!"fp_w{i}" 32 (choose ws (lit 0))]
  return pack [pack ww, pack aa]

/-- Eight partial multiplies, preserving the original two-DSP decomposition. -/
def partialProducts (o : Expr) : CircuitM Expr := do
  let mut lows := []
  let mut highs := []
  for i in [:4] do
    let a := zext (slice o (128 + 24*i) 24) 24 32
    let wl := zext (slice o (32*i) 16) 16 32
    let wh := zext (slice o (32*i+16) 16) 16 32
    lows := lows ++ [← wire s!"fp_pl{i}" 32 (Expr.mul a wl)]
    highs := highs ++ [← wire s!"fp_ph{i}" 16 (Expr.mul a wh)]
  return pack [pack highs, pack lows]

/-- `fpm_t` packs p0 most significant, unlike the operand/partial-product arrays. -/
def sumProducts (p : Expr) : CircuitM Expr := do
  let mut ps := []
  for i in [:4] do
    ps := ps ++ [← wire s!"fp_p{i}" 32
      (add (slice p (64+32*i) 32) (pack [lit 0 16, slice p (16*i) 16]))]
  return .concat ps

structure Range where
  valid : Expr := lit 0 1
  space : Expr := lit 0 2
  lo : Expr := lit 0
  hi : Expr := lit 0
  deriving Inhabited

def Range.pack (r : Range) := Circuit.pack [r.hi, r.lo, r.space, r.valid]
def Range.unpack (e : Expr) : Range :=
  ⟨bit e 66, slice e 64 2, slice e 32 32, slice e 0 32⟩
def mkRange (sp : Nat) (lo len : Expr) : Range := ⟨nz len, lit sp 2, lo, add lo len⟩

structure Footprint where
  all : Expr := lit 0 1
  reads : Array Range := Array.replicate 4 {}
  writes : Array Range := Array.replicate 2 {}

def Footprint.pack (f : Footprint) :=
  Circuit.pack [(Circuit.pack (f.writes.toList.map Range.pack)),
    (Circuit.pack (f.reads.toList.map Range.pack)), f.all]
def Footprint.unpack (e : Expr) : Footprint :=
  { all := bit e 402,
    reads := (List.range 4).toArray.map fun i => Range.unpack (slice e (134+67*i) 67),
    writes := (List.range 2).toArray.map fun i => Range.unpack (slice e (67*i) 67) }
def Footprint.rd (f : Footprint) (i sp : Nat) (lo len : Expr) :=
  { f with reads := f.reads.set! i (mkRange sp lo len) }
def Footprint.wr (f : Footprint) (i sp : Nat) (lo len : Expr) :=
  { f with writes := f.writes.set! i (mkRange sp lo len) }
def Footprint.rdIf (f : Footprint) (cond : Expr) (i sp : Nat) (lo len : Expr) :=
  let r := mkRange sp lo len
  let r := Range.unpack (mux cond r.pack (lit 0 67))
  { f with reads := f.reads.set! i r }
def Footprint.wrIf (f : Footprint) (cond : Expr) (i sp : Nat) (lo len : Expr) :=
  let r := mkRange sp lo len
  let r := Range.unpack (mux cond r.pack (lit 0 67))
  { f with writes := f.writes.set! i r }

/-- Full ISA memory ranges, including conservative STREAM bounds, MM RMAX and
    ASCALE, VOP broadcasts/reductions, barriers, and overflow/wrap behavior. -/
def ranges (c p : Expr) (depth : Nat) : CircuitM Expr := do
  let w := word c
  let pr := fun i => slice p ((3-i)*32) 32
  let lo := fun n => zext (slice (w n) 0 16) 16 32
  let hi := fun n => zext (slice (w n) 16 16) 16 32
  let rows := lo 4
  let cols := hi 4
  let kbD ← wire "fp_kbD" 32 (Expr.mul cols (lit depth))
  let m := zext (slice (w 6) 16 8) 8 32
  let nonempty := every [nz rows, nz cols]
  let empty : Footprint := {}
  let ld := (empty.rd 0 1 (w 1) (shl (w 3) 2)).wr 0 0 (w 2) (w 3)
  let st := (empty.rd 0 0 (w 2) (w 3)).wr 0 1 (w 1) (shl (w 3) 2)
  let stream := (((((empty.wr 0 1 (w 2) (lit (4*256*256))).wr 1 0 (w 7) (lit 256)).rd
    0 0 (lo 1) (lit 8)).rd 1 0 (w 4) (lit 1024)).rd 2 0 (w 5) (lit 256)).rd
    3 0 (w 6) (add (hi 1) (lit 1))
  let ds := ((((empty.wr 0 1 (w 1) (shl (add (pr 0) cols) 2)).wr 1 0 (w 6) rows).rd
    0 0 (w 2) (shl cols 1)).rd 1 0 (w 3) rows).rd 2 0 (w 5) (add (w 7) (lit 1))
  let mm := (((((empty.rd 0 1 (w 1) (add (pr 0) kbD)).rdIf (bnot (flag c 0))
    1 1 (w 2) (add (pr 1) (shl cols 2))).rdIf (flag c 3) 3 0 (w 2) m).rd
    2 2 (zext (slice (w 6) 24 8) 8 32) cols).wr 0 0 (w 3) (add (pr 2) rows)).wrIf
    (flag c 2) 1 0 (add (w 3) (pr 3)) m
  let qr := zext (slice (w 2) 0 8) 8 32
  let qk := hi 2
  let qd ← wire "fp_qd" 32 (Expr.mul qk (lit depth))
  let qa := (((empty.rd 0 0 (w 1) (add (pr 0) qd)).rdIf (flag c 1) 1 0 (w 4) qd).rdIf
    (flag c 2) 2 0 (w 5) qr).wr 0 2 (zext (slice (w 2) 8 8) 8 32) qk
  let qs := ((empty.rd 0 0 (w 1) (add (pr 0) kbD)).wr 0 1 (w 2)
    (add (add (pr 1) (pr 2)) (lit 1))).wr 1 1 (w 3) (shl (mux (flag c 0) rows (pr 3)) 2)
  let fn := slice (w 6) 16 8
  let outer := eq fn (lit 6 8)
  let bmode := slice (w 6) 24 2
  let readsB := among fn 8 [0,1,2,3,4,5,13,14,19,6]
  let reduce := among fn 8 [16,17,18,19,20]
  let vo := (((empty.rdIf (mux outer (bnot (flag c 1)) (bnot (eq fn (lit 13 8))))
    0 0 (w 2) (mux outer (mux (flag c 0) (lit 1) cols) (add (pr 0) cols))).rdIf
    outer 2 0 (w 7) cols).rdIf (band readsB (bnot (eq bmode (lit 3 2)))) 1 0 (w 3)
    (choose [(eq bmode (lit 0 2), add (pr 1) cols),
      (eq bmode (lit 1 2), add (pr 1) (lit 1))] cols)).wr 0 0 (w 1)
    (add (pr 2) (mux (eq fn (lit 20 8)) (lit 2) (mux reduce (lit 1) cols)))
  let ga := (empty.rd 0 0 (w 1) (add (pr 0) (hi 3))).wr 0 0 (w 2)
    (add (add (pr 1) (pr 2)) (hi 3))
  let wa := (empty.wr 0 1 (lit 0) (lit 0xffffffff)).wr 1 0 (w 2) (lit 1)
  let cases := [(isOp c 0x10, ld), (isOp c 0x11, st), (isOp c 0x13, stream),
    (band (isOp c 0x12) nonempty, ds), (every [isOp c 0x20, nonempty, nz m], mm),
    (every [isOp c 0x21, nz qr, nz qk], qa), (band (isOp c 0x22) nonempty, qs),
    (band (isOp c 0x30) nonempty, vo), (every [isOp c 0x40, nz (lo 3), nz (hi 3)], ga),
    (isOp c 0x05, { empty with all := lit 1 1 }),
    (isOp c 0x06, empty.rd 0 0 (w 1) (lit 1)), (isOp c 0x07, wa)]
  wire "fp_ranges" 403 (choose (cases.map fun (cond, f) => (cond, f.pack)) (lit 0 403))

structure Interval where
  lo : Expr
  hi : Expr

def Interval.pack (r : Interval) := Circuit.pack [r.hi, r.lo]
def Interval.overlap (a b : Interval) := band (lt a.lo b.hi) (lt b.lo a.hi)
def Range.dram (r : Range) : Interval := ⟨r.lo, mux r.valid r.hi (lit 0)⟩
def Range.tmem (r : Range) : Interval :=
  ⟨slice r.lo 0 16, mux r.valid (slice r.hi 0 17) (lit 0 17)⟩
def Range.overflow (r : Range) := band r.valid
  (bor (nz (slice r.lo 16 16) 16) (nz (slice r.hi 17 15) 15))
def Interval.hull (a b : Interval) : Interval :=
  let lo := mux (lt a.lo b.lo) a.lo b.lo
  let hi := mux (lt a.hi b.hi) b.hi a.hi
  ⟨mux (eq b.hi (lit 0 17)) a.lo (mux (eq a.hi (lit 0 17)) b.lo lo),
   mux (eq b.hi (lit 0 17)) a.hi (mux (eq a.hi (lit 0 17)) b.hi hi)⟩

/-- The sequencer stores a 322-bit segregated footprint, with t0's write role and
    a conservative hull for MM's second output. Disabled interval endpoints are zero. -/
def segregate (op fp : Expr) : CircuitM Expr := do
  let f := Footprint.unpack fp
  let r := fun i => f.reads[i]!
  let w := fun i => f.writes[i]!
  let zero : Range := {}
  -- d0,d1,t0,t1,t2,t3,t4,hull-extra,ACT; plus DRAM/TMEM/ACT write roles.
  let cases : List (Nat × List Range × Nat × Nat × Nat) := [
    (0x10, [r 0,zero,w 0,zero,zero,zero,zero,zero,zero], 0,1,0),
    (0x11, [w 0,zero,r 0,zero,zero,zero,zero,zero,zero], 1,0,0),
    (0x12, [w 0,zero,w 1,r 0,r 1,r 2,r 3,zero,zero], 1,1,0),
    (0x13, [w 0,zero,w 1,r 0,r 1,r 2,r 3,zero,zero], 1,1,0),
    (0x20, [r 0,r 1,w 0,zero,r 3,zero,zero,w 1,r 2], 0,1,0),
    (0x21, [zero,zero,r 0,r 1,r 2,zero,zero,zero,w 0], 0,0,1),
    (0x22, [w 0,w 1,r 0,zero,zero,zero,zero,zero,zero], 1,0,0),
    (0x30, [zero,zero,w 0,r 0,r 1,r 2,zero,zero,zero], 0,1,0),
    (0x40, [zero,zero,w 0,r 0,zero,zero,zero,zero,zero], 0,1,0),
    (0x06, [zero,zero,r 0,zero,zero,zero,zero,zero,zero], 0,0,0),
    (0x07, [w 0,zero,w 1,zero,zero,zero,zero,zero,zero], 1,1,0)]
  let mut fields := #[]
  for i in [:9] do
    let e ← wire s!"seg_range{i}" 67 (choose (cases.map fun (o, rs, _, _, _) =>
      (eq op (lit o 8), (rs[i]?.getD zero).pack)) zero.pack)
    fields := fields.push (Range.unpack e)
  let role := fun getter => choose (cases.map fun (o, _, dw, tw, aw) =>
    (eq op (lit o 8), lit (getter dw tw aw) 1)) (lit 0 1)
  let d0 := fields[0]!.dram
  let d1 := fields[1]!.dram
  let t := fun i => fields[i+2]!.tmem
  let h := fields[7]!.tmem
  let a := fields[8]!
  let all := bor f.all (any ((List.range 6).map fun i => fields[i+2]!.overflow))
  return pack [mux a.valid (slice a.hi 0 17) (lit 0 17), slice a.lo 0 8,
    role (fun _ _ aw => aw), (t 4).pack, (t 3).pack, (t 2).pack, (t 1).pack,
    ((t 0).hull h).pack, role (fun _ tw _ => tw), d0.pack, d1.pack,
    role (fun dw _ _ => dw), all]

/-- Packed {any-conflict, DRAM-conflict}. Inputs may be arbitrary segregated bits. -/
def conflicts (n e : Expr) : Expr := Id.run do
  let dw := fun f => bit f 320
  let dr := fun f i => Interval.mk (slice f (224 + 64*i) 32) (slice f (192 + 64*i) 32)
  let tw := fun f => bit f 191
  let tr := fun f i => Interval.mk (slice f (43 + 33*(4-i)) 16) (slice f (26+33*(4-i)) 17)
  let ar := fun f => Interval.mk (zext (slice f 17 8) 8 17) (slice f 0 17)
  let all := bor (bit n 321) (bit e 321)
  let mut dram := all
  for i in [:2] do
    for j in [:2] do
      dram := bor dram (band (bor (dw n) (dw e)) ((dr n i).overlap (dr e j)))
  let mut both := bor dram (band (bor (tw n) (tw e)) ((tr n 0).overlap (tr e 0)))
  for i in [1:5] do
    both := bor both (bor (band (tw n) ((tr n 0).overlap (tr e i)))
      (band (tw e) ((tr e 0).overlap (tr n i))))
  both := bor both (band (bor (bit n 25) (bit e 25)) ((ar n).overlap (ar e)))
  return pack [dram, both]

/-- Independent ports expose each combinational stage, allowing exhaustive local
    proofs without assuming a legal instruction or a pipeline reachability condition. -/
def build (depth slices : Nat) : Module := runModule "otpu_seq_logic_sparkle" do
  let c ← input "cmd" 240
  let o ← input "ops_in" 224
  let pp ← input "part_in" 192
  let p ← input "prod_in" 128
  let fp ← input "fp_in" 403
  let sn ← input "seg_n" 322
  let se ← input "seg_e" 322
  let ir ← input "ir" 256
  let regs ← input "regs" 512
  output "unit_out" 32 (unitOf (opcode c))
  output "cmd_out" 240 (← decode ir regs)
  output "ops_out" 224 (← operands c depth slices)
  output "part_out" 192 (← partialProducts o)
  output "prod_out" 128 (← sumProducts pp)
  output "fp_out" 403 (← ranges c p depth)
  output "seg_out" 322 (← segregate (opcode c) fp)
  output "conf_out" 2 (conflicts sn se)

end OpenTPU.SeqLogic
