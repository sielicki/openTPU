import OpenTPU.TMem

namespace OpenTPU.TMem

/-- Existing TMEM ABI, simulation contract checks and logical-memory dumps.
    All synthesized storage, routing and pipeline logic lives in `TMem.build`. -/
def wrapper (c : Config) : String :=
  let memoryInit := String.intercalate "\n" <|
    (List.range c.readPorts).flatMap fun p =>
      if c.shareMask.testBit p then [] else
        (List.range c.lanes).map fun b =>
          s!"  initial for(int a=0;a<WORDS/LANES;a++) impl.mem{p}_{b}[a]=0;"
  s!"
module otpu_tmem #(parameter int WORDS={c.words}, LANES={c.lanes}, NRP={c.readPorts},
  NWP={c.writePorts}, WPB={c.writesPerBank},
  parameter logic [NRP-1:0] GEN_R={c.generalRead},
  parameter logic [NWP-1:0] GEN_W={c.generalWrite},
  parameter int SH_HOST={c.shareHost},
  parameter logic [NRP-1:0] SH_MASK={c.shareMask}, parameter int SID=0)(
  input logic clk,
  input logic [NRP-1:0][LANES-1:0] r_en,r_req,
  input logic [NRP-1:0][LANES-1:0][31:0] r_addr,
  output wire [NRP-1:0][LANES-1:0][31:0] r_data,
  input logic [NWP-1:0][LANES-1:0] w_en,w_req,
  input logic [NWP-1:0] w_gnt,
  input logic [NWP-1:0][LANES-1:0][31:0] w_addr,w_data,
  input logic dump
);
  localparam int IW=$clog2(WORDS/LANES);
  initial if(WORDS!={c.words} || LANES!={c.lanes} || NRP!={c.readPorts} || NWP!={c.writePorts} ||
    WPB!={c.writesPerBank} || GEN_R!={c.generalRead} || GEN_W!={c.generalWrite} ||
    SH_HOST!={c.shareHost} || SH_MASK!={c.shareMask})
    $fatal(1, \"Sparkle TMEM configuration mismatch; regenerate\");
  wire [LANES-1:0][WPB-1:0] selected_valid;
  wire [LANES-1:0][WPB-1:0][IW-1:0] selected_address;
  wire [LANES-1:0][WPB-1:0][31:0] selected_data;
  otpu_tmem_sparkle impl(.clk,.r_en,.r_req,.r_addr,.r_data,.w_en,.w_req,.w_gnt,.w_addr,.w_data,
    .selected_valid,.selected_address,.selected_data);
`ifndef SYNTHESIS
{memoryInit}
  function automatic bit conflict(input logic [LANES-1:0] en,
      input logic [LANES-1:0][31:0] a, input bit is_write);
    for(int i=0;i<LANES;i++) for(int j=i+1;j<LANES;j++)
      if(en[i] && en[j] && a[i]%LANES==a[j]%LANES && (is_write || a[i]!=a[j])) return 1;
    return 0;
  endfunction
  function automatic bit contiguous(input logic [LANES-1:0] en,
      input logic [LANES-1:0][31:0] a);
    for(int l=0;l<LANES;l++) if(en[l] && a[l]!=a[0]+32'(l)) return 0;
    return 1;
  endfunction
  always @(posedge clk) begin
    for(int p=0;p<NRP;p++) begin
      if(SH_MASK[p] && |r_en[p]) begin
        if(|r_req[SH_HOST]) $fatal(1, \"Sparkle TMEM%0d guest beside host\",SID);
        for(int g=0;g<p;g++) if(SH_MASK[g] && |r_req[g])
          $fatal(1, \"Sparkle TMEM%0d guest beside earlier guest\",SID);
      end
      if(conflict(r_en[p],r_addr[p],0)) $fatal(1, \"Sparkle TMEM%0d read bank conflict\",SID);
      if(!GEN_R[p] && !contiguous(r_req[p],r_addr[p]))
        $fatal(1, \"Sparkle TMEM%0d noncontiguous read\",SID);
      for(int l=0;l<LANES;l++) if(r_en[p][l] && r_addr[p][l]>=WORDS)
        $fatal(1, \"Sparkle TMEM%0d read out of bounds\",SID);
    end
    for(int p=0;p<NWP;p++) begin
      if(conflict(w_en[p],w_addr[p],1)) $fatal(1, \"Sparkle TMEM%0d write bank conflict\",SID);
      if(WPB==1 && !GEN_W[p] && !contiguous(w_req[p],w_addr[p]))
        $fatal(1, \"Sparkle TMEM%0d noncontiguous write\",SID);
      for(int l=0;l<LANES;l++) if(w_en[p][l] && w_addr[p][l]>=WORDS)
        $fatal(1, \"Sparkle TMEM%0d write out of bounds\",SID);
    end
    for(int b=0;b<LANES;b++) begin
      int n;
      n=0;
      for(int p=0;p<NWP;p++) for(int l=0;l<LANES;l++)
        if(w_en[p][l] && w_addr[p][l]%LANES==b) n++;
      if(n>WPB) $fatal(1, \"Sparkle TMEM%0d too many bank writes\",SID);
    end
  end
  logic [31:0] shadow [WORDS];
  initial for(int i=0;i<WORDS;i++) shadow[i]=0;
  always @(posedge clk)
    for(int b=0;b<LANES;b++) for(int w=0;w<WPB;w++)
      if(selected_valid[b][w]) shadow[int'(selected_address[b][w])*LANES+b] <= selected_data[b][w];
  string dir;
  initial void'($value$plusargs(\"dir=%s\",dir));
  always @(posedge clk) if(dump) begin
    int fd;
    fd=$fopen($sformatf(\"%s/tmem_%0d.hex\",dir,SID),\"w\");
    for(int i=0;i<WORDS;i++) $fwrite(fd,\"%08x\\n\",shadow[i]);
    $fclose(fd);
  end
`endif
endmodule
"

end OpenTPU.TMem
