import OpenTPU.VpuIssue

namespace OpenTPU.VpuStream
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.SeqLogic

/-- Stream grant arbitration, two-edge input alignment and reduction-kind FIFO.
    The tail and reduction tree connect through explicit completion/data ports. -/
def build : Module := runModule "otpu_vpu_stream_sparkle" do
  clocks
  for (n,w) in [("start",1),("cq_n",2),("busy",1),("done_i",1),("dpend",1),("wb_e",1),
    ("ss_req",1),("ss_pe",1),("ss_fk",3),("ss_fi",5),("ss_fd",256),
    ("ss_in_v",1),("ss_in_d",256),("ss_cfg",23),("en",1),("s_xm_first",1),
    ("t_qc",1),("t_qrl",1),("t_qsub",8),("t_qd",256),("cap",1),("vt_rl",1),
    ("root_v",1),("t_yv",1),("t_ov",1)] do
    let _ ← input n w
  let idle ← wire "idle" 1 (every [bnot (ref "start"),eq (ref "cq_n") (lit 0 2),
    bnot (ref "busy"),bnot (ref "done_i"),bnot (ref "dpend"),ref "wb_e"])
  let active ← wire "active_next" 1 (every [ref "ss_req",ref "ss_rq",bor (ref "ss_act") idle])
  for (n,w,v) in [("ss_rq",1,ref "ss_req"),("ss_act",1,active),
    ("s_init",1,every [ref "ss_req",ref "ss_rq",bnot (ref "ss_act"),idle]),
    ("sen_q",1,band active (ref "ss_pe")),("sen",1,ref "sen_q"),
    ("s1_fk",3,mux (ref "ss_act") (ref "ss_fk") (lit 0 3)),("s_fk",3,ref "s1_fk")] do
    reg n w true [(lit 1 1,v)]
  for (n,w,v) in [("s1_fi",5,ref "ss_fi"),("s1_fd",256,ref "ss_fd"),
    ("s_fi",5,ref "s1_fi"),("s_fd",256,ref "s1_fd"),
    ("s1_in_v",1,ref "ss_in_v"),("s1_in_d",256,ref "ss_in_d"),
    ("s_in_v",1,ref "s1_in_v"),("s_in_d",256,ref "s1_in_d"),("s_cfg",23,ref "ss_cfg")] do
    let _ ← clocked n w (lit 1 1) v
  for (n,w,v) in [("q_cap",1,band (ref "ss_act") (ref "t_qc")),("q_rl",1,ref "t_qrl"),
    ("q_sub",8,ref "t_qsub"),("q_pd",256,ref "t_qd")] do
    let _ ← clocked n w (ref "en") v
  let push := every [ref "en",ref "cap",ref "vt_rl"]
  reg "kt" 3 true [(push,add (ref "kt") (lit 1 3)),(ref "s_init",lit 0 3)]
  reg "kh" 3 true [(band (ref "en") (ref "root_v"),add (ref "kh") (lit 1 3)),(ref "s_init",lit 0 3)]
  for i in [:8] do
    reg s!"kq{i}" 1 false [(every [bnot (ref "s_init"),push,eq (ref "kt") (lit i 3)],ref "q_cap")]
  output "vt_q" 1 (OpenTPU.SeqWindow.select ((List.range 8).map fun i => ref s!"kq{i}") (ref "kh") 3 1)
  output "ss_act_d" 1 active
  output "ss_gnt" 1 (ref "ss_act")
  output "s_first" 1 (band (ref "ss_act") (ref "s_xm_first"))
  output "ss_y_v" 1 (band (ref "sen") (ref "t_yv"))
  output "ss_o_v" 1 (band (ref "sen") (ref "t_ov"))
  for (n,w) in [("ss_rq",1),("ss_act",1),("s_init",1),("sen",1),("s_fk",3),
    ("s_fi",5),("s_fd",256),("s_in_v",1),("s_in_d",256),("s_cfg",23),
    ("q_cap",1),("q_rl",1),("q_sub",8),("q_pd",256)] do
    output s!"o_{n}" w (ref n)

end OpenTPU.VpuStream
