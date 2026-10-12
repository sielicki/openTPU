import OpenTPU.DmaSetup
import OpenTPU.SeqWindow
import OpenTPU.Backend

/-! Native LD/ST/WAITW and DMA side of DSTEP/STREAM. Memories retain their
    independent clocked writes, asynchronous reads, and explicit read registers. -/
namespace OpenTPU.Dma
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.SeqLogic

structure Config where
  chunkBytes : Nat := 32
  lanes : Nat := 8
  bufferDepth : Nat := 128
  streams : Bool := true
  deriving Repr

def Config.words (c : Config) := c.chunkBytes/4
def Config.width (c : Config) := min c.words c.lanes
def Config.positions (c : Config) := c.words/c.width
def Config.pointerBits (c : Config) := clog2 c.bufferDepth
def Config.positionBits (c : Config) := max 1 (clog2 c.positions)
def Config.gatherBits (c : Config) := clog2 (128*c.positions)
def Config.outputBits (c : Config) := clog2 (256/c.width)
def Config.hasStream (c : Config) := c.streams && c.width == 8 && c.lanes == 8

def Config.validate (c : Config) : Except String Unit := do
  if c.chunkBytes < 4 || !powerOfTwo c.chunkBytes || !powerOfTwo c.lanes || c.width >= 256 then
    throw "DMA requires power-of-two D >= 4 and LANES, with min(D/4,LANES) < 256"
  if c.bufferDepth < 32 || !powerOfTwo c.bufferDepth then
    throw "DMA requires power-of-two DEPTH >= 32"

private def shr (a : Expr) (amount : Nat) := Expr.op .shr [a,lit amount]
private def inc (name : String) (width : Nat := 32) := add (ref name) (lit 1 width)
private def dec (name : String) (width : Nat := 32) := sub (ref name) (lit 1 width)
private def mask (width : Nat) := lit (2^width-1) width
private def low (value : Expr) (width : Nat) := if width == 0 then lit 0 else zext (slice value 0 width) width 32
private def arraySelect (name : String) (count width : Nat) (index : Expr) :=
  SeqWindow.select ((List.range count).map fun i => ref s!"{name}{i}") index (clog2 count) width

/-- Dynamic bit indexing preserves the HDL's out-of-range read behavior. A
    32-bit intermediate also retains its wrapped part-select base arithmetic. -/
private def dynamicWord (name : String) (data index : Expr) : CircuitM Expr := do
  let base ← wire s!"{name}_base" 32 (.mul index (lit 32))
  wire name 32 (pack ((List.range 32).map fun i => .index data (add base (lit i))))

private def memory (name : String) (aw dw : Nat) (wa wd we ra : Expr) : CircuitM Expr := do
  let rd := s!"{name}_read"
  let m ← getModule
  setModule <| (m.addWire {name := rd,ty := .bitVector dw}).addStmt
    (.memory name aw dw "clk" wa wd we ra rd true [] [])
  return ref rd

/-- The reference fill table has unspecified power-up contents. Choose one of
    its valid configurations, rather than zeroing bits that every setup writes
    as one. This avoids retaining constant flops and unreachable table reads. -/
private def fillNextRegister (index : Nat) (value : Expr) : CircuitM Unit := do
  let name := s!"f_nk{index}"
  let initial := (#[0,2,3,4,5,0,3,3] : Array Nat)[index]!
  let m ← getModule
  setModule <| (m.addWire {name,ty := .bitVector 3}).addStmt
    (.register name "clk" ("no_reset", .synchronous)
      (mux (ref "ds_su") value (ref name)) (Int.ofNat initial))

private def fillMask (width : Nat) (kind index rows : Expr) := pack ((List.range width).map fun l =>
  mux (eq kind (lit 3 3)) (lt (add (.mul (zext index 5 32) (lit width)) (lit l)) (zext rows 9 32))
    (if l == 0 then lit 1 1 else band (bnot (eq kind (lit 4 3))) (bnot (eq kind (lit 5 3)))))

private def occupancyFlags (c : Config) (value : Expr) :=
  let bits := c.pointerBits+1
  pack [bnot (lt (lit ((2^bits+c.bufferDepth-64) % 2^bits) bits) value),
    bnot (eq value (lit c.bufferDepth bits))]

private def nextOccupancyFlags (c : Config) (value up down : Expr) :=
  let bits := c.pointerBits+1
  mux (band up (bnot down)) (occupancyFlags c (add value (lit 1 bits)))
    (mux (band down (bnot up)) (occupancyFlags c (sub value (lit 1 bits))) (occupancyFlags c value))

private def productBelow (c : Config) (r n : Expr) (limit : Nat) :=
  let plm := lit (2^(clog2 (2*c.positions))-1)
  mux (bor (eq r (lit 0 9)) (eq n (lit 0 6))) (lit 1 1)
    (mux (bor (bnot (lt (zext r 9 32) (lit limit))) (bnot (lt (zext n 6 32) (lit limit)))) (lit 0 1)
      (lt (.mul (band (zext r 9 32) plm) (band (zext n 6 32) plm)) (lit limit)))

def build (c : Config) : Module := runModule "otpu_dma_sparkle" do
  clocks
  let start ← input "start" 1
  let cmd ← input "cmd" 240
  let grant ← input "b_gnt" 1
  let valid ← input "b_rvalid" 1
  let dram ← input "b_rdata" (c.chunkBytes*8)
  let idle ← input "wr_idle" 1
  let tdata ← input "t_rdata" (c.lanes*32)
  let sgrant ← input "ss_gnt" 1
  let syv ← input "ss_y_v" 1
  let syd ← input "ss_y_d" (c.lanes*32)
  let sov ← input "ss_o_v" 1
  let sod ← input "ss_o_d" 32
  let one := lit 1 1
  let zero := lit 0 1
  let w := c.width
  let cw := c.words
  let spc := c.positions
  let swl := clog2 w
  let cwl := clog2 cw
  let pw := c.pointerBits
  let gw := c.gatherBits+1
  let obw := c.outputBits
  let pos := fun x => shr (low x cwl) swl
  let held := every [bnot (ref "rst"),bnot start]
  let active ← wire "active" 1 (every [held,bnot (ref "ackw"),ref "busy"])
  let load := band active (bnot (ref "is_st"))
  let store := band active (ref "is_st")
  let stream := band active (ref "is_ds")
  let normalStart ← wire "normal_start" 1 (band start (bnot (among (opcode cmd) 8 [0x12,0x13])))
  let streamStart ← wire "stream_start" 1 (band start (among (opcode cmd) 8 [0x12,0x13]))
  let segEnd ← wire "seg_end" 1 (bor (eq (pos (ref "sw")) (lit (spc-1))) (ref "sl_one"))
  let ldAct ← wire "ld_act" 1 (every [ref "busy",bnot (ref "is_st"),bnot (ref "ackw")])
  let ldReq ← wire "ld_req" 1 (every [ldAct,ref "cl_nz",ref "oc_nf",
    bor (bnot (ref "is_ds")) (bor (ref "ds_rr") (band (bnot (ref "ds_wr")) (ref "oc_lr")))])
  let ldIss ← wire "ld_iss" 1 (every [ldReq,grant,bnot (ref "ds_wr")])
  let ldDv ← wire "ld_dv" 1 (every [ldAct,ref "sl_nz",nz (ref "cnt") (pw+1)])
  let stWr ← wire "st_wr" 1 (band (ref "st_pend") (ref "pl"))
  let adv ← wire "adv" 1 (bor (bnot stWr) (ref "oc_nf"))
  let stRd ← wire "st_rd" 1 (every [ref "busy",ref "is_st",bnot (ref "ackw"),ref "sl_nz",adv])
  let stPush ← wire "st_push" 1 (every [ref "busy",ref "is_st",bnot (ref "ackw"),stWr,adv])
  let stIss ← wire "st_iss" 1 (band (ref "st_wq") grant)
  let yv ← wire "y_v" 1 (if c.hasStream then syv else zero)
  let ov ← wire "o_v" 1 (if c.hasStream then sov else zero)
  let od ← wire "o_d" 32 (if c.hasStream then sod else lit 0)
  let yp ← wire "y_p" (32*w) (if c.hasStream then slice syd 0 (32*w) else lit 0 (32*w))
  let spad ← wire "ds_spad" 1 (band (ref "ds_pad") (bit (ref "ds_sj") 3))
  let yKeep ← wire "y_keep" 1 (band yv (bnot (band (ref "ds_pad") (bit (ref "ds_yj") 3))))
  let room ← wire "ds_room" 1 (bnot (lt (lit (128*spc-2) (gw+1))
    (add (add (zext (ref "og") gw (gw+1)) (zext yv 1 (gw+1))) (zext (ref "pe") 1 (gw+1)))))
  let take ← wire "ds_take" 1 (every [ref "ds_run",nz (ref "ds_left") 16,
    bor (ref "ds_zero") (bor spad (nz (ref "cnt") (pw+1))),room])
  let flushed ← wire "ds_flushed" 1 (band (eq (ref "ds_ycnt") (ref "ds_nseg"))
    (bor (bnot (ref "ds_qen")) (eq (ref "ds_ocnt") (ref "ds_rows"))))
  let drain ← wire "ds_drain" 1 (every [ref "ds_run",eq (ref "ds_left") (lit 0 16),bnot flushed,room])
  let eat ← wire "ds_eat" 1 (every [take,bnot (ref "ds_zero"),bnot spad,
    eq (zext (ref "ds_pos") c.positionBits 32) (lit (spc-1))])
  let ldEat ← wire "ld_eat" 1 (bor (band ldDv segEnd) eat)
  let dsIss ← wire "ds_issue" 1 (band (ref "ds_wr") grant)
  let ogNext ← wire "og_nx" gw (sub (add (ref "og") (zext yKeep 1 gw)) (mux dsIss (lit spc gw) (lit 0 gw)))
  let rrNext ← wire "ds_rr_nx" 1 (band (ref "ds_rr")
    (bnot (band ldIss (bor (eq (ref "ds_rc") (lit 63 6)) (ref "cl_one")))))
  let wrNext ← wire "ds_wr_nx" 1 (band (bnot (lt ogNext (lit spc gw)))
    (bor (ref "ds_wr") (band (bnot rrNext)
      (bor (bnot (lt ogNext (lit (64*spc) gw))) (eq (ref "ds_left") (lit 0 16))))))
  let mut stData := []
  let mut stMask := []
  for p in [:spc] do
    for l in [:w] do
      let selected := eq (ref "pp") (lit p)
      stData := stData ++ [mux selected (slice (ref "t_rq") (32*l) 32) (ref s!"cb{p*w+l}")]
      stMask := stMask ++ [bor (bit (ref "cbm") (p*w+l)) (band selected (bit (ref "pm") l))]
  let stCd ← wire "st_cd" (c.chunkBytes*8) (pack stData)
  let stCm ← wire "st_cm" cw (pack stMask)
  let lb ← memory "lb" pw (c.chunkBytes*8) (ref "wp") (mux valid dram stCd) (bor valid stPush)
    (mux stIss (inc "rp" pw) (ref "rp"))
  let lbq ← clocked "lb_q" (c.chunkBytes*8) one lb
  let lm ← memory "lm" pw cw (ref "wp") stCm stPush (ref "rp")
  let yq ← clocked "y_q" (32*w) one yp
  let gtChunk := slice (shr (zext (ref "gt") c.gatherBits 32) (clog2 spc)) 0 7
  let gtPos := low (zext (ref "gt") c.gatherBits 32) (clog2 spc)
  let mut gathered := []
  for p in [:spc] do
    for l in [:w] do
      let we ← clocked s!"gb_we{p}_{l}" 1 one (band yKeep (eq gtPos (lit p)))
      let wa ← clocked s!"gb_wa{p}_{l}" 7 one gtChunk
      let rd ← memory s!"gb{p}_{l}" 7 32 (ref s!"gb_wa{p}_{l}") (slice yq (32*l) 32)
        (ref s!"gb_we{p}_{l}") (ref "gh")
      -- RAM writes use the previous edge's enable/address, as in the RTL.
      let _ := we
      let _ := wa
      let bypass := if p+1 == spc then band (ref s!"gb_we{p}_{l}") (ref s!"gb_eq{l}") else zero
      gathered := gathered ++ [mux bypass (slice yq (32*l) 32) rd]
  for l in [:w] do
    let _ ← clocked s!"gb_eq{l}" 1 one (eq gtChunk (mux dsIss (inc "gh" 7) (ref "gh")))
  let oq ← clocked "o_q" 32 one od
  let mut obData := []
  for l in [:w] do
    let rd ← memory s!"ob{l}" obw 32 (ref s!"ow_a{l}") oq (bit (ref "ow_e") l) (slice (ref "oi") 0 obw)
    obData := obData ++ [rd]
  let su ← DmaSetup.logic w (ref "sc") (pack ((List.range 8).map fun i => ref s!"dsw{i}"))
  let cfgRows := slice su.config 8 9
  let cfgQ := bit su.config 1
  let setup := ref "ds_su"
  let fkOn ← wire "fk_on" 1 (band (ref "ds_fill") (nz (ref "fs_k") 3))
  let fNext ← wire "f_nx" 3 (arraySelect "f_nk" 8 3 (ref "fs_k"))
  let fkEnd := eq (ref "fs_i") (arraySelect "f_kn" 8 5 (ref "fs_k"))
  let nextKind := mux fkEnd fNext (ref "fs_k")
  let nextIndex := mux fkEnd (lit 0 5) (inc "fs_i" 5)
  let nsm := slice (sub su.rowSegments (lit 1 6)) 0 5
  let vectorWords ← wire "fill_vector_words" 32 (.mul (zext su.rowSegments 6 32) (lit w))
  let afterK := mux (band (bit su.config 7) (bit su.config 6)) (lit 6 3)
    (mux (eq (slice su.config 2 2) (lit 1 2)) (lit 7 3) (lit 3 3))
  let afterA := mux (eq (slice su.config 2 2) (lit 1 2)) (lit 7 3) (lit 3 3)
  let nextKinds := [lit 0 3,lit 2 3,afterK,lit 4 3,lit 5 3,lit 0 3,afterA,lit 3 3]
  let counts := [lit 0 5,nsm,nsm,slice (sub (shr (add (zext cfgRows 9 32) (lit (w-1))) swl) (lit 1)) 0 5,
    lit 0 5,lit 0 5,nsm,nsm]
  let addresses := [lit 0,su.vectors,add su.vectors vectorWords,su.x,su.constants,
    add su.constants su.constantStride,add su.vectors (.mul (lit 2) vectorWords),add su.vectors (.mul (lit 3) vectorWords)]
  for k in [:8] do
    fillNextRegister k nextKinds[k]!
    let _ ← clocked s!"f_kn{k}" 5 setup counts[k]!
    let _ ← clocked s!"f_ka{k}" 32 setup addresses[k]!
    let _ ← clocked s!"dsw{k}" 32 (ref "ds_dsd") (slice tdata (32*(k%c.lanes)) 32)
  let _ ← clocked "fs_k" 3 (bor setup fkOn) (mux setup (mux cfgQ (lit 1 3) (lit 2 3)) nextKind)
  let _ ← clocked "fs_i" 5 (bor setup fkOn) (mux setup (lit 0 5) nextIndex)
  let _ ← clocked "fs_a" 32 (bor setup fkOn) (mux setup (mux cfgQ su.vectors (add su.vectors vectorWords))
    (mux fkEnd (arraySelect "f_ka" 8 32 fNext) (add (ref "fs_a") (lit w))))
  let _ ← clocked "fs_m" w (bor setup fkOn) (mux setup (mask w) (fillMask w nextKind nextIndex (ref "ds_rows")))
  let fkK ← wire "fk_k" 3 (mux fkOn (ref "fs_k") (lit 0 3))
  let fkI ← wire "fk_i" 5 (mux fkOn (ref "fs_i") (lit 0 5))
  let fkA ← wire "fk_a" 32 (mux fkOn (ref "fs_a") (lit 0))
  let fkM ← wire "fk_m" w (mux fkOn (ref "fs_m") (lit 0 w))
  let frk ← clocked "fr_k" 3 one (mux (ref "rst") (lit 0 3) fkK)
  let fri ← clocked "fr_i" 5 one fkI
  let pe ← clocked "pe" 1 one (band (bnot (ref "rst")) (bor take drain))
  let peIn ← clocked "pe_in" 1 one take
  let peZero ← clocked "pe_zero" 1 one (bor (ref "ds_zero") spad)
  let pePos ← clocked "pe_pos" c.positionBits one (ref "ds_pos")
  let mut inputs := []
  for l in [:c.lanes] do
    if l < w then
      let value ← dynamicWord s!"in_d{l}" lbq (add (.mul (zext pePos c.positionBits 32) (lit w)) (lit l))
      inputs := inputs ++ [mux peZero (lit 0) value]
    else inputs := inputs ++ [lit 0]
  output "ss_pe" 1 pe
  output "ss_in_v" 1 peIn
  output "ss_in_d" (32*c.lanes) (pack inputs)
  output "ss_fk" 3 frk
  output "ss_fi" 5 fri
  output "ss_fd" (32*c.lanes) tdata
  let stActive := every [ref "busy",ref "is_st",bnot (ref "ackw")]
  output "b_req" 1 (bor (bor ldReq (ref "ds_wr")) (band stActive (ref "st_wq")))
  output "b_we" 1 (bor (ref "ds_wr") (band stActive (ref "st_wq")))
  output "b_addr" 32 (mux stActive (ref "ic") (mux (ref "ds_wr") (ref "ds_wa") (ref "ic")))
  output "b_wmask" cw (mux (ref "ds_wr") (mask cw) lm)
  output "b_wdata" (c.chunkBytes*8) (mux (ref "ds_wr") (pack gathered) lbq)
  let mut ren := []
  let mut raddr := []
  let mut wen := []
  let mut waddr := []
  let mut wdata := []
  for l in [:c.lanes] do
    if l < w then
      ren := ren ++ [mux stRd (bit (ref "sm") l) (mux (ref "ds_dsc") one (band (ref "ds_fill") (bit fkM l)))]
      raddr := raddr ++ [mux stRd (add (ref "so") (lit l))
        (mux (ref "ds_dsc") (add (zext (slice (word (ref "sc") 1) 0 16) 16 32) (lit l))
          (mux (ref "ds_fill") (add fkA (lit l)) (lit 0)))]
      let value ← dynamicWord s!"ld_word{l}" lbq (add (.mul (ref "dv_p") (lit w)) (lit l))
      let idx := add (.mul (zext (ref "oi") 8 32) (lit w)) (lit l)
      let valid := mux (ref "ds_out") (lt idx (zext (ref "ds_rows") 9 32))
        (every [ref "dv_v",bit (ref "dv_m") l,bnot (ref "is_ww")])
      let address := mux (ref "ds_out") (add (ref "ds_oa") idx) (add (ref "dv_a") (lit l))
      let value := mux (ref "ds_out") obData[l]! value
      let waitHolds := if l == 0 then band (ref "ww_c2") (ref "ww_ok") else zero
      wen := wen ++ [bor waitHolds valid]
      waddr := waddr ++ [mux waitHolds (ref "ww_t") address]
      wdata := wdata ++ [mux waitHolds (ref "ww_w") value]
    else
      ren := ren ++ [zero]; raddr := raddr ++ [lit 0]
      wen := wen ++ [zero]; waddr := waddr ++ [lit 0]; wdata := wdata ++ [lit 0]
  output "t_ren" c.lanes (pack ren)
  output "t_raddr" (32*c.lanes) (pack raddr)
  let twen ← clocked "t_wen_q" c.lanes one (mux (ref "rst") (lit 0 c.lanes) (pack wen))
  let twa ← clocked "t_waddr_q" (32*c.lanes) one (pack waddr)
  let twd ← clocked "t_wdata_q" (32*c.lanes) one (pack wdata)
  output "t_wen" c.lanes twen
  output "t_waddr" (32*c.lanes) twa
  output "t_wdata" (32*c.lanes) twd
  -- Command preparation and main control. Later updates retain NBA priority.
  let a ← wire "command_address" 32 (shr (word cmd 1) 2)
  let n ← wire "command_words" 32 (mux (isOp cmd 0x07) (lit 1) (word cmd 3))
  let offset ← wire "command_offset" 32 (low a swl)
  let chunkOffset ← wire "command_chunk_offset" 32 (low a cwl)
  let ns ← wire "command_segments" 32 (shr (add n (add offset (lit (w-1)))) swl)
  let nc ← wire "command_chunks" 32 (shr (add n (add chunkOffset (lit (cw-1)))) cwl)
  let segmentMask := lit (2^32-w)
  let chunkMask := lit (2^32-cw)
  let ackEnd ← wire "ack_end" 1 (every [held,ref "ackw",idle])
  let plainFinish := every [load,ref "ld_last",bnot (ref "is_ww")]
  let waitFinish := every [load,ref "is_ww",ref "ww_c2",ref "ww_ok"]
  let finish := bor plainFinish waitFinish
  let notReset := bnot (ref "rst")
  let done ← clocked "done_q" 1 one (mux (bor ackEnd (every [notReset,normalStart,eq n (lit 0)])) one (ref "ld_fin"))
  reg "ld_fin" 1 true [(one,zero),(finish,one)]
  reg "ld_last" 1 true [(one,zero),(every [load,ldDv,ref "sl_one"],one)]
  let _ ← clocked "dv_v" 1 one (band notReset ldDv)
  let _ ← clocked "dv_m" w one (ref "sm")
  let _ ← clocked "dv_a" 32 one (ref "so")
  let _ ← clocked "dv_p" 32 one (pos (ref "sw"))
  let ow ← clocked "ow_e" w one (mux (band stream ov)
    (.op .shl [lit 1 w,low (zext (ref "ds_ocnt") 9 32) swl]) (lit 0 w))
  let _ := ow
  for l in [:w] do
    reg s!"ow_a{l}" obw false [(band stream ov,slice (shr (zext (ref "ds_ocnt") 9 32) swl) 0 obw)]
  let wwHeld ← clocked "ww_held_q" 1 one (every [notReset,ref "busy",ref "is_ww",ref "ww_c2",ref "ww_ok"])
  let wwActive := band load (ref "is_ww")
  let wwSleep := every [wwActive,ref "ww_sl",bnot (ref "err_q")]
  let retry ← wire "wait_retry" 1 (band wwSleep (eq (ref "ww_n") (lit 0)))
  let wwWord ← dynamicWord "wait_word" lbq (low (ref "ww_a") cwl)
  let wwValue ← wire "wait_masked" 32 (band (ref "ww_w") (ref "ww_mask"))
  let wwDiff ← wire "wait_difference" 32 (sub wwValue (ref "ww_ref"))
  let wwOkay ← wire "wait_holds" 1 (mux (eq (ref "ww_cmp") (lit 0 2)) (eq wwValue (ref "ww_ref"))
    (mux (eq (ref "ww_cmp") (lit 1 2)) (bnot (eq wwValue (ref "ww_ref"))) (bnot (bit wwDiff 31))))
  let move := band active (bor ldDv stRd)
  let setupActive := band stream setup
  let streamWrite := band stream dsIss
  let streamDone := every [stream,ref "ds_run",flushed,eq (ref "og") (lit 0 gw)]
  let outputDone := every [stream,ref "ds_out",eq (inc "oi" 8) (ref "ds_nv")]
  let storesDone := every [store,ref "st_fin",bnot (ref "st_wq"),eq (ref "occ") (lit 0 (pw+1))]
  let storeAdvance := band store adv
  let storeEnd := every [storeAdvance,ref "st_pend",bnot (ref "pa"),bnot (ref "sl_nz")]
  let startRun := every [store,bnot (ref "st_wq"),
    bor (bnot (lt (ref "occ") (lit 32 (pw+1)))) (band (ref "st_fin") (nz (ref "occ") (pw+1)))]
  reg "busy" 1 true [(streamStart,one),(band normalStart (nz n),one),(ackEnd,zero),(finish,zero)]
  reg "ackw" 1 true [(start,zero),(ackEnd,zero),(band streamDone (bnot (ref "ds_qen")),one),(outputDone,one),(storesDone,one)]
  reg "is_st" 1 false [(streamStart,zero),(normalStart,isOp cmd 0x11)]
  reg "is_ds" 1 false [(streamStart,one),(normalStart,zero),(ackEnd,zero)]
  reg "is_ww" 1 true [(streamStart,zero),(normalStart,isOp cmd 0x07)]
  reg "sc" 240 false [(streamStart,cmd)]
  reg "ds_zero" 1 false [(streamStart,flag cmd 0)]
  for (name,value) in [("ww_a",a),("ww_t",word cmd 2),("ww_ref",word cmd 3),("ww_mask",word cmd 4),
      ("ww_iv",word cmd 5),("ww_to",word cmd 6),("dw",a),("de",add a n)] do
    reg name 32 false [(normalStart,value)]
  reg "ww_cmp" 2 false [(normalStart,slice cmd 224 2)]
  reg "ww_tc" 32 false [(normalStart,lit 0),(wwActive,inc "ww_tc")]
  reg "err_q" 1 true [(every [wwActive,nz (ref "ww_to"),eq (ref "ww_tc") (ref "ww_to")],one)]
  reg "ww_c1" 1 true [(normalStart,zero),(wwActive,ref "dv_v")]
  reg "ww_w" 32 false [(band wwActive (ref "dv_v"),wwWord)]
  reg "ww_c2" 1 true [(normalStart,zero),(wwActive,ref "ww_c1")]
  reg "ww_ok" 1 false [(band wwActive (ref "ww_c1"),wwOkay)]
  reg "ww_sl" 1 true [(normalStart,zero),(every [wwActive,ref "ww_c2",bnot (ref "ww_ok")],one),(retry,zero)]
  reg "ww_n" 32 false [(every [wwActive,ref "ww_c2",bnot (ref "ww_ok")],ref "ww_iv"),
    (band wwSleep (nz (ref "ww_n")),dec "ww_n")]
  reg "sw" 32 false [(normalStart,band a segmentMask),(move,add (ref "sw") (lit w)),(retry,band (ref "ww_a") segmentMask)]
  reg "so" 32 false [(normalStart,sub (word cmd 2) offset),(move,add (ref "so") (lit w)),
    (retry,sub (ref "ww_t") (low (ref "ww_a") swl))]
  let initialMask := pack ((List.range w).map fun l => band (bnot (lt (lit l) offset)) (lt (sub (lit l) offset) n))
  let movedMask := pack ((List.range w).map fun l =>
    let addr := add (add (ref "sw") (lit w)) (lit l)
    band (bnot (lt addr (ref "dw"))) (lt addr (ref "de")))
  let retryMask := pack ((List.range w).map fun l => eq (lit l) (low (ref "ww_a") swl))
  reg "sm" w false [(normalStart,initialMask),(move,movedMask),(retry,retryMask)]
  reg "sleft" 32 false [(streamStart,lit 0),(normalStart,ns),(move,dec "sleft"),(retry,lit 1)]
  reg "sl_nz" 1 false [(streamStart,zero),(normalStart,nz ns),(move,bnot (ref "sl_one")),(retry,one)]
  reg "sl_one" 1 false [(streamStart,zero),(normalStart,eq ns (lit 1)),(move,eq (ref "sleft") (lit 2)),(retry,one)]
  let loadIssue := band load ldIss
  let storeIssue := band store stIss
  reg "ic" 32 false [(normalStart,band a chunkMask),(setupActive,shr su.source 2),
    (bor loadIssue storeIssue,add (ref "ic") (lit cw)),(retry,band (ref "ww_a") chunkMask)]
  let sourceChunks ← wire "source_chunks" 32 (shr (.mul (zext cfgRows 9 32) (zext su.rowSegments 6 32)) (cwl-swl))
  let sourceNonzero := band (bnot (ref "ds_zero")) (bnot (productBelow c cfgRows su.rowSegments spc))
  reg "cleft" 32 false [(streamStart,lit 0),(normalStart,nc),(setupActive,mux (ref "ds_zero") (lit 0) sourceChunks),
    (loadIssue,dec "cleft"),(retry,lit 1)]
  reg "cl_nz" 1 false [(streamStart,zero),(normalStart,nz nc),(setupActive,sourceNonzero),
    (loadIssue,bnot (ref "cl_one")),(retry,one)]
  reg "cl_one" 1 false [(streamStart,zero),(normalStart,eq nc (lit 1)),
    (setupActive,band sourceNonzero (productBelow c cfgRows su.rowSegments (2*spc))),
    (loadIssue,eq (ref "cleft") (lit 2)),(retry,one)]
  reg "occ" (pw+1) false [(start,lit 0 (pw+1)),
    (load,sub (add (ref "occ") (zext ldIss 1 (pw+1))) (zext ldEat 1 (pw+1))),
    (store,sub (add (ref "occ") (zext stPush 1 (pw+1))) (zext stIss 1 (pw+1)))]
  let flags0 := occupancyFlags c (lit 0 (pw+1))
  let flagsLoad := nextOccupancyFlags c (ref "occ") ldIss ldEat
  let flagsStore := nextOccupancyFlags c (ref "occ") stPush stIss
  for (name,bitIndex) in [("oc_nf",1),("oc_lr",0)] do
    reg name 1 false [(start,bit flags0 bitIndex),(load,bit flagsLoad bitIndex),(store,bit flagsStore bitIndex)]
  reg "cnt" (pw+1) false [(start,lit 0 (pw+1)),(load,sub (add (ref "cnt") (zext valid 1 (pw+1))) (zext ldEat 1 (pw+1)))]
  reg "wp" pw false [(start,lit 0 pw),(bor (band load valid) (band store stPush),inc "wp" pw)]
  reg "rp" pw false [(start,lit 0 pw),(bor (band load ldEat) storeIssue,inc "rp" pw)]
  reg "st_pend" 1 true [(start,zero),(storeAdvance,ref "pa"),(storeEnd,zero)]
  reg "pa" 1 true [(start,zero),(storeAdvance,stRd)]
  reg "st_wq" 1 true [(normalStart,zero),(band storeIssue (eq (ref "st_wn") (lit 1 (pw+1))),zero),(startRun,one)]
  reg "st_fin" 1 false [(normalStart,zero),(storeEnd,one)]
  reg "st_wn" (pw+1) false [(storeIssue,dec "st_wn" (pw+1)),(startRun,ref "occ")]
  for (name,width,value) in [("pp",32,ref "ppa"),("pm",w,ref "pma"),("pl",1,ref "pla"),
      ("t_rq",32*w,slice tdata 0 (32*w)),("ppa",32,pos (ref "sw")),("pma",w,ref "sm"),("pla",1,segEnd)] do
    reg name width false [(storeAdvance,value)]
  let accumulate := every [storeAdvance,ref "st_pend",bnot (ref "pl")]
  let clearMask := every [storeAdvance,ref "st_pend",ref "pl"]
  let mut nextMask := []
  for p in [:spc] do
    -- The packed array index in the RTL wraps its 32-bit multiplication.
    let selected := eq (low (ref "pp") (32-swl)) (lit p)
    for l in [:w] do
      reg s!"cb{p*w+l}" 32 false [(band accumulate selected,slice (ref "t_rq") (32*l) 32)]
      nextMask := nextMask ++ [mux selected (bit (ref "pm") l) (bit (ref "cbm") (p*w+l))]
  reg "cbm" cw false [(normalStart,lit 0 cw),(clearMask,lit 0 cw),(accumulate,pack nextMask)]
  reg "ds_dsc" 1 true [(streamStart,isOp cmd 0x13),(band stream (ref "ds_dsc"),zero)]
  reg "ds_dsd" 1 true [(streamStart,zero),(band stream (ref "ds_dsc"),one),(band stream (ref "ds_dsd"),zero)]
  reg "ds_su" 1 true [(streamStart,isOp cmd 0x12),(band stream (ref "ds_dsd"),one),(setupActive,zero)]
  let streamGrant := every [stream,ref "ds_wait",sgrant]
  let filled := every [stream,ref "ds_fill",eq (ref "fs_k") (lit 0 3)]
  reg "ds_wait" 1 true [(streamStart,zero),(setupActive,one),(streamGrant,zero)]
  reg "ds_fill" 1 true [(streamStart,zero),(streamGrant,one),(filled,zero)]
  reg "ds_run" 1 true [(streamStart,zero),(filled,one),(streamDone,zero)]
  reg "ds_out" 1 true [(streamStart,zero),(band streamDone (ref "ds_qen"),one),(outputDone,zero)]
  reg "ss_req_q" 1 true [(setupActive,one),(every [stream,ref "ds_run",flushed],zero)]
  reg "ss_cfg_q" 23 false [(setupActive,su.config)]
  for (name,width,value) in [("ds_wb",32,shr su.destination 2),("ds_oa",32,su.outputAddress),
      ("ds_rows",9,cfgRows),("ds_qen",1,cfgQ),("ds_pad",1,bit su.config 0),
      ("ds_nseg",16,su.segments),("ds_nv",8,slice (shr (add (zext cfgRows 9 32) (lit (w-1))) swl) 0 8)] do
    reg name width false [(setupActive,value)]
  reg "ds_wa" 32 false [(setupActive,shr su.destination 2),(streamWrite,add (ref "ds_wa") (lit cw))]
  reg "ds_sj" 4 false [(setupActive,lit 0 4),(band stream take,inc "ds_sj" 4)]
  reg "ds_yj" 4 false [(setupActive,lit 0 4),(band stream yv,inc "ds_yj" 4)]
  reg "ds_left" 16 false [(setupActive,su.segments),(band stream take,dec "ds_left" 16)]
  reg "ds_pos" c.positionBits false [(streamStart,lit 0 c.positionBits),
    (every [stream,take,bnot (ref "ds_zero"),bnot spad],mux eat (lit 0 c.positionBits) (inc "ds_pos" c.positionBits))]
  reg "ds_ycnt" 16 false [(streamStart,lit 0 16),(band stream yv,inc "ds_ycnt" 16)]
  reg "ds_ocnt" 9 false [(streamStart,lit 0 9),(band stream ov,inc "ds_ocnt" 9)]
  reg "ds_wch" 16 false [(streamStart,lit 0 16),(streamWrite,inc "ds_wch" 16)]
  reg "gt" c.gatherBits false [(streamStart,lit 0 c.gatherBits),(band stream yKeep,inc "gt" c.gatherBits)]
  reg "gh" 7 false [(streamStart,lit 0 7),(streamWrite,inc "gh" 7)]
  reg "og" gw false [(streamStart,lit 0 gw),(stream,ogNext)]
  reg "ds_wr" 1 true [(streamStart,zero),(stream,wrNext)]
  reg "ds_rr" 1 true [(streamStart,zero),(stream,bor rrNext (every [ldIss,bnot (ref "ds_rr"),bnot (ref "cl_one")]))]
  reg "ds_rc" 6 false [(streamStart,lit 0 6),(band stream ldIss,mux (eq (ref "ds_rc") (lit 63 6)) (lit 0 6) (inc "ds_rc" 6))]
  reg "oi" 8 false [(streamStart,lit 0 8),(band stream (ref "ds_out"),inc "oi" 8)]
  output "rdy" 1 (bnot (ref "busy"))
  output "done" 1 done
  output "err" 1 (ref "err_q")
  output "ww_held" 1 wwHeld
  output "ss_req" 1 (ref "ss_req_q")
  output "ss_cfg" 23 (ref "ss_cfg_q")

def registerHints (c : Config) : Backend.RegisterHints :=
  [("pe",[.maxFanout 64]),("gh",[.maxFanout 64]),("ds_wr",[.maxFanout 64]),("pp",[.maxFanout 64])] ++
  (List.range c.width).flatMap (fun l => [(s!"ow_a{l}",[.keep]),(s!"gb_eq{l}",[.keep])]) ++
  (List.range c.positions).flatMap (fun p => (List.range c.width).flatMap fun l =>
    [(s!"gb_we{p}_{l}",[.keep]),(s!"gb_wa{p}_{l}",[.keep])])

def memoryHints (c : Config) : Backend.MemoryHints :=
  [("lb",.block),("lm",.distributed)] ++
  (List.range c.width).map (fun l => (s!"ob{l}",.distributed)) ++
  (List.range c.positions).flatMap (fun p => (List.range c.width).map fun l => (s!"gb{p}_{l}",.distributed))

def toVerilog (c : Config) : Except String String := do
  c.validate
  Backend.withRegisterHints (build c) (registerHints c) (memoryHints := memoryHints c)

end OpenTPU.Dma
