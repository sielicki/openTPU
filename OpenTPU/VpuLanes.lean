import OpenTPU.VpuDatapathSupport
import OpenTPU.SeHelpers
import OpenTPU.SeComposite

namespace OpenTPU.VpuLanes
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.VpuDatapathSupport

private def sf (x : Expr) (f : Nat) := bit x f
private def state (v k1 k2 ii flags : Expr) := pack [flags,ii,k2,k1,v]
private def sv (s : Expr) := slice s 76 32
private def k1 (s : Expr) := slice s 44 32
private def k2 (s : Expr) := slice s 12 32
private def ii (s : Expr) := slice s 3 9
private def flags (s : Expr) := slice s 0 3
private def mtClass (c : Config) (m : Expr) := slice m (21+c.lanes) 3
private def narrowMeta (c : Config) (m : Expr) := pack
  [slice m 0 21,slice m 21 c.issueLanes,slice m (21+c.lanes) 4]
private def widenMeta (c : Config) (m : Expr) := if c.issueLanes == c.lanes then m else pack
  [slice m 0 (21+c.issueLanes),lit 0 (c.lanes-c.issueLanes),slice m (21+c.issueLanes) 4]
private def classF (cls : Expr) := SeqWindow.select
  ((List.range 8).map fun i => lit (VpuDecode.classFunction i) 8) cls 3 8

private def initialState (name : String) (fh x y : Expr) : CircuitM Expr := do
  let rcp ← SeHelpers.setup s!"{name}_rcp" (lit 3 3) x
  let rsq ← SeHelpers.setup s!"{name}_rsq" (lit 4 3) x
  let log ← SeHelpers.setup s!"{name}_log" (lit 5 3) x
  let zero := state (lit 0) (lit 0) (lit 0) (lit 0 9) (lit 0 3)
  let cases := [
    (any [sf fh 4,sf fh 5],state (FloatConvert.minMax x y (sf fh 5)) (lit 0) (lit 0) (lit 0 9) (lit 0 3)),
    (sf fh 8,state (FloatConvert.ftz x) (lit 0) (lit 0) (lit 0 9) (lit 0 3)),
    (sf fh 12,state (FloatConvert.abs x) (lit 0) (lit 0) (lit 0 9) (lit 0 3)),
    (sf fh 13,state (FloatConvert.ftz y) (lit 0) (lit 0) (lit 0 9) (lit 0 3)),
    (sf fh 10,state (lit 0) (k1 rcp) (k2 rcp) (lit 0 9) (flags rcp)),
    (sf fh 11,state (lit 0) (lit 0) (k2 rsq) (lit 0 9) (flags rsq)),
    (sf fh 15,state (lit 0) (k1 log) (lit 0) (ii log) (flags log))]
  return cases.foldr (fun (p,v) old => mux p v old) zero

private def expC (i : Nat) := (#[0x3f800000,0x3f317218,0x3e75fdf0,0x3d635847,
  0x3c1d955b,0x3aaec3ff,0x39218489,0x377fe5fe] : Array Nat)[i]!
private def logC (i : Nat) := (#[0,0x3fb8aa3b,0xbf38aa38,0x3ef639eb,0xbeb8ae27,
  0x3e9369c2,0xbe74adf2,0x3e5ce48e,0xbe543e8e,0x3e00db73] : Array Nat)[i]!

/-- Operand program includes priority for arbitrary one-hot decoder register states. -/
private def operands (c : Config) (s : Nat) (long : Bool)
    (fh x y xc xd rsa rsb rfb st : Expr) : Expr := Id.run do
  let op := fun a b d e dest neg => pack [a,b,d,e,lit dest 2,lit neg 1]
  let base := op (lit 0) (lit 0x3f800000) (lit 0x80000000) (lit 0x3f800000) 0 0
  let simple := fun a b d e => op a b d e 1 0
  let one := lit 0x3f800000
  let nz := lit 0x80000000
  let mut cases := []
  if s == 0 then
    cases := [(sf fh 3,simple x y nz one),(sf fh 6,simple x xd y xc),
      (sf fh 0,simple x one y one),(sf fh 1,simple x one (FloatConvert.neg y) one),
      (sf fh 2,simple y one (FloatConvert.neg x) one),
      (any [sf fh 16,sf fh 18,sf fh 19],if rma c then op rsa rsb rfb one 0 0 else base)]
  if long then
    let ex := if s == 0 then simple x one (mux (sf fh 14) (FloatConvert.neg y) nz) one
      else if s == 1 then op (sv st) one (k2 st) one 2 0
      else if s == 2 then simple (lit (expC 7)) (k1 st) (lit (expC 6)) one
      else if s <= 8 then simple (sv st) (k1 st) (lit (expC (8-s))) one else base
    let rc := if s >= 6 then base else if s%2 == 0 then simple (k1 st) (k2 st) (lit 0x40000000) one
      else op (k2 st) (sv st) nz one 3 0
    let rs := if s == 0 then op (lit 0x3f000000) (FloatConvert.ftz x) nz one 2 1
      else if (s-1)%3 == 0 then simple (k2 st) (k2 st) nz one
      else if (s-1)%3 == 1 then simple (k1 st) (sv st) (lit 0x3fc00000) one
      else op (k2 st) (sv st) nz one 3 0
    let lg := if s == 0 then op (k1 st) one (lit 0xbf800000) one 2 0
      else if s == 1 then simple (lit (logC 9)) (k1 st) (lit (logC 8)) one
      else if s <= 8 then simple (sv st) (k1 st) (lit (logC (9-s))) one
      else simple (sv st) (k1 st) (k2 st) one
    cases := cases ++ [(any [sf fh 9,sf fh 14],ex),(sf fh 10,rc),(sf fh 11,rs),(sf fh 15,lg)]
  return cases.foldr (fun (p,v) old => mux p v old) base

private def preStages (name : String) (st cls : Expr) : CircuitM Expr := do
  let exp := eq cls (lit 2 3)
  let lo := FloatConvert.greater (lit 0xc2fc0000) (sv st)
  let hi := bnot (FloatConvert.greater (lit 0x43000000) (sv st))
  let p0 ← clocked s!"{name}_p0" 108 (ref "en") (mux exp
    (state (mux (bor lo hi) (lit 0) (sv st)) (k1 st) (k2 st) (ii st) (pack [lo,hi,lit 0 1])) st)
  let e1 ← clocked s!"{name}_e1" 1 (ref "en") exp
  let g1 ← clocked s!"{name}_g1" 1 (ref "en") (eq cls (lit 5 3))
  let floor ← FloatConvert.floor s!"{name}_floor" (sv p0)
  let p1 ← clocked s!"{name}_p1" 108 (ref "en")
    (state (sv p0) (k1 p0) (k2 p0) (mux e1 (slice floor 0 9) (ii p0)) (flags p0))
  let e2 ← clocked s!"{name}_e2" 1 (ref "en") e1
  let g2 ← clocked s!"{name}_g2" 1 (ref "en") g1
  let signed := pack [ii p1,mux (bit (ii p1) 8) (lit (2^23-1) 23) (lit 0 23)]
  let prep ← FloatConvert.integerStage1 s!"{name}_i1" signed
  let fp ← FloatConvert.integerStage2 s!"{name}_i2" prep
  let adjusted := pack [slice fp 0 31,Expr.xor (bit fp 31) e2]
  clocked s!"{name}_p2" 108 (ref "en")
    (state (sv p1) (k1 p1) (mux (bor e2 g2) adjusted (k2 p1)) (ii p1) (flags p1))

/-- Full lane bank. Packed buses are lane-zero least significant. Tail's two
    arithmetic stages are explicit composite-loop inputs/outputs. -/
def build (c : Config) : Except String Module := do
  validate c
  return runModule "otpu_vpu_lanes_sparkle" do
    clocks
    for (n,w) in [("en",1),("m0",mw c),("m0d",28),("xa",32*c.lanes),("xb",32*c.lanes),
      ("xc",32*c.lanes),("xd",32*c.lanes),("rsa",32*c.lanes),("rsb",32*c.lanes),
      ("rfb",32*c.lanes),("c_uy",256),("c_qy",256)] do let _ ← input n w
    for (n,w) in [("c_sel",3),("c_sa",96*c.lanes),("c_sb",96*c.lanes),("c_sc",96*c.lanes),
      ("c_se",96*c.lanes),("c_hold",1),("c_ov",1),("c_od",32*c.lanes),("c_om",c.lanes),
      ("c_ometa",21)] do let _ ← declared n w
    let m := ref "m0"
    let fh := slice (ref "m0d") 8 20
    let initial := pack [field c m "all_last",field c m "waddr",field c m "mask",
      slice (ref "m0d") 0 3,field c m "v"]
    let mut taps := #[initial]
    let mut msl := #[]
    for s in [:nsx c] do
      let sti ← if s == 1 then do
        let p ← delay "meta_pre" 3 (25+c.issueLanes) (narrowMeta c taps[s]!)
        pure (widenMeta c p)
        else pure taps[s]!
      msl := msl.push sti
      let st ← if s == 0 then delay "meta_slot0" 7 (25+c.lanes) sti else do
        let p ← delay s!"meta_slot{s}" 7 (25+c.issueLanes) (narrowMeta c sti)
        pure (widenMeta c p)
      taps := taps.push st
    let mut hits := #[]
    let mut mo := lit 0 (25+c.lanes)
    for s in [:nsx c+1] do
      let h ← wire s!"hit{s}" 1 (if s == 0 then band (bit taps[s]! (24+c.lanes)) (bit (ref "m0d") 7)
        else if [1,6,9,10].contains s then band (bit taps[s]! (24+c.lanes))
          (eq (SeqWindow.select ((List.range 8).map fun cl => lit (VpuDecode.slots (VpuDecode.classFunction cl)) 4) (mtClass c taps[s]!) 3 4) (lit s 4)) else lit 0 1)
      hits := hits.push h
      mo := mux h taps[s]! mo
    if c.comp8 then
      mo := mux (ref "c_ov") (pack [ref "c_ometa",ref "c_om",lit 0 3,lit 1 1]) mo
    output "mo" (25+c.lanes) mo
    let mut results := []
    let mut maxMasks := []
    let mut maxValues := []
    let mut partials := []
    let mut compY := []
    let mut compB := []
    for l in [:c.lanes] do
      let name := s!"lane{l}"
      let x := word (ref "xa") l
      let y ← wire s!"{name}_y" 32 (laneY c m (ref "xb") l)
      compB := compB ++ [y]
      let long := l < nll c
      let st0 ← if long then initialState name fh x y else pure (state (mux (sf fh 8) (FloatConvert.ftz x) (mux (sf fh 12) (FloatConvert.abs x)
            (mux (sf fh 13) (FloatConvert.ftz y) (lit 0)))) (lit 0) (lit 0) (lit 0 9) (lit 0 3))
      let mut sts := #[st0]
      let mut r0 := lit 0
      for s in [:if long then 10 else 1] do
        let p := s!"{name}_slot{s}"
        let sti ← if s == 1 then preStages p sts[s]! (mtClass c taps[s]!) else pure sts[s]!
        let f ← wire s!"{p}_fh" 20 (if s == 0 then fh else
          SeqWindow.select ((List.range 8).map fun cl => lit (2^(VpuDecode.classFunction cl)) 20) (mtClass c msl[s]!) 3 20)
        let o ← wire s!"{p}_op" 131 (operands c s long f x y (word (ref "xc") l)
          (word (ref "xd") l) (word (ref "rsa") l) (word (ref "rsb") l) (word (ref "rfb") l) sti)
        let selected := fun i => if !long && c.comp8 then
          mux (bit (ref "c_sel") 0) (word (ref (#["c_sa","c_sb","c_sc","c_se"][i]!)) l) (slice o (i*32) 32)
          else slice o (i*32) 32
        let ra ← clocked s!"{p}_ra" 32 (ref "en") (selected 0)
        let rb ← clocked s!"{p}_rb" 32 (ref "en") (selected 1)
        reg s!"{p}_rc" 32 true [(ref "en",selected 2)] 0x80000000
        let re ← if s == 0 then clocked s!"{p}_re" 32 (ref "en") (selected 3) else pure (lit 0x3f800000)
        let r ← mma p ra rb (ref s!"{p}_rc") re (s == 0)
        if s == 0 then r0 := r
        if long then
          let sr ← clocked s!"{p}_sr" 108 (ref "en") sti
          let dst ← clocked s!"{p}_dst" 3 (ref "en") (pack [bit o 130,slice o 128 2])
          let ds ← delay s!"{p}_dst_delay" 6 3 dst
          let fl ← delay s!"{p}_f" 6 3 (flags sr)
          let a ← if s <= 8 then delay s!"{p}_k1" 6 32 (k1 sr) else pure (lit 0)
          let b ← if s <= 8 then delay s!"{p}_k2" 6 32 (k2 sr) else pure (lit 0)
          let i ← if s <= 8 then delay s!"{p}_ii" 6 9 (ii sr) else pure (lit 0 9)
          let rr := mux (bit ds 0) (FloatConvert.neg r) r
          let d := slice ds 1 2
          let st ← wire s!"{p}_out" 108 (state (mux (eq d (lit 1 2)) rr (lit 0))
            (mux (eq d (lit 2 2)) rr a) (mux (eq d (lit 3 2)) rr b) i fl)
          sts := sts.push st
      partials := partials ++ [r0]
      compY := compY ++ [if long then lit 0 else r0]
      if long then
        let te := sts[9]!
        let tc := sts[6]!
        let ts := sts[10]!
        let ex := mux (bit te 0) (lit 0) (mux (bit te 1) (lit 0x7f800000)
          (add (sv te) (pack [lit 0 23,ii te])))
        let rc := mux (bit tc 0) (lit 0) (mux (bit tc 1) (pack [lit 0 31,bit tc 2])
          (mux (bit tc 2) (FloatConvert.neg (k2 tc)) (k2 tc)))
        let rs := mux (bit ts 0) (lit 0) (k2 ts)
        let lg := mux (bit ts 0) (lit 0xff800000) (mux (bit ts 2) (lit 0x7fc00000)
          (mux (bit ts 1) (lit 0x7f800000) (sv ts)))
        results := results ++ [mux hits[9]! ex (mux hits[6]! rc (mux hits[10]!
          (mux (eq (mtClass c taps[10]!) (lit 5 3)) lg rs) (mux hits[0]! (sv st0) (sv sts[1]!))))]
        maxMasks := maxMasks ++ [lit 0 1]
        maxValues := maxValues ++ [lit 0]
      else
        let cv := if c.comp8 then ref "c_ov" else lit 0 1
        results := results ++ [mux cv (word (ref "c_od") l) (mux hits[0]! (sv st0) r0)]
        maxMasks := maxMasks ++ [every [bnot cv,hits[0]!,any [sf fh 4,sf fh 5]]]
        maxValues := maxValues ++ [FloatConvert.minMax x y (sf fh 5)]
    if c.comp8 then
      emitInstance "otpu_se_comp_sparkle" "u_comp"
        [("clk",ref "clk"),("rst",ref "rst"),("en",ref "en"),
         ("in_v",band (field c m "v") (bit (ref "m0d") 6)),("in_c",slice (ref "m0d") 3 3),
         ("in_a",ref "xa"),("in_b",pack compB),("in_m",field c m "mask"),
         ("in_meta",pack [field c m "all_last",field c m "waddr"]),
         ("hold",ref "c_hold"),("st_sel",ref "c_sel"),("st_a",ref "c_sa"),("st_b",ref "c_sb"),
         ("st_c",ref "c_sc"),("st_e",ref "c_se"),("st_y",pack [pack compY,ref "c_uy",ref "c_qy"]),
         ("out_v",ref "c_ov"),("out_d",ref "c_od"),("out_m",ref "c_om"),("out_meta",ref "c_ometa")]
    else
      for (n,w) in [("c_hold",1),("c_sel",3),("c_sa",96*c.lanes),("c_sb",96*c.lanes),
        ("c_sc",96*c.lanes),("c_se",96*c.lanes),("c_ov",1),("c_od",32*c.lanes),
        ("c_om",c.lanes),("c_ometa",21)] do emitAssign n (lit 0 w)
    for (n,w,e) in [("lres",32*c.lanes,pack results),("lmm",c.lanes,pack maxMasks),
      ("lmv",32*c.lanes,pack maxValues),("pacc",32*c.lanes,pack partials),
      ("o_c_hold",1,ref "c_hold"),("o_c_sel",3,ref "c_sel"),("o_c_sa",96*c.lanes,ref "c_sa"),
      ("o_c_sb",96*c.lanes,ref "c_sb"),("o_c_sc",96*c.lanes,ref "c_sc"),("o_c_se",96*c.lanes,ref "c_se")] do
      output n w e

end OpenTPU.VpuLanes
