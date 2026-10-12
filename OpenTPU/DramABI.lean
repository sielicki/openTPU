import OpenTPU.Dram
namespace OpenTPU.Dram
/-- File I/O and scheduled host pokes are simulation-only; storage and write
priority are native circuit logic. Image words are big endian; dumps little endian. -/
def wrapper (c : Config) : String :=
  let initText := String.intercalate "\n" <| (List.range 4).map fun b =>
    s!"      impl.mem{b}[base+i] = image[i][{8*b} +: 8];"
  let dumpword := "{" ++ String.intercalate "," ((List.range 4).reverse.map fun b => s!"impl.mem{b}[i]") ++ "}"
  let pipes := String.intercalate "\n" <| (List.range c.latency).map fun k =>
    s!"    impl.av{k}=0; impl.bv{k}=0; impl.bt{k}=0;"
  s!"
module otpu_dram #(parameter int WORDS={c.words}, D={c.depth}, LAT={c.latency}, SID=0)(
  input logic clk,a_req,a_we,
  input logic [31:0] a_addr,a_wdata,
  input logic [3:0] a_be,
  output wire a_rvalid,
  output wire [31:0] a_rdata,a_rdata2,
  input logic sw_req,
  input logic [31:0] sw_addr,sw_wdata,
  input logic [3:0] sw_be,
  input logic b_req,b_tag,b_we,
  input logic [D/4-1:0] b_wmask,
  input logic [D*8-1:0] b_wdata,
  input logic [31:0] b_addr,
  output wire b_rvalid,b_rtag,
  output wire [D*8-1:0] b_rdata,
  input logic dump
);
  initial if(WORDS!={c.words} || D!={c.depth} || LAT!={c.latency})
    $fatal(1,\"Sparkle DRAM configuration mismatch; regenerate\");
  wire poke_valid;
  wire [31:0] poke_addr,poke_data;
  otpu_dram_sparkle impl(.clk,.a_req,.a_we,.a_addr,.a_wdata,.a_be,.a_rvalid,.a_rdata,.a_rdata2,
    .sw_req,.sw_addr,.sw_wdata,.sw_be,.b_req,.b_tag,.b_we,.b_wmask,.b_wdata,.b_addr,
    .b_rvalid,.b_rtag,.b_rdata,.poke_valid,.poke_addr,.poke_data);
`ifdef SYNTHESIS
  assign poke_valid=0;
  assign poke_addr=0;
  assign poke_data=0;
`else
  localparam int IMAGE_WORDS=4096;
  logic [31:0] image [IMAGE_WORDS];
  longint pk_c [64];
  logic [31:0] pk_a [64],pk_v [64];
  int pk_n=0,pk_i=0;
  longint pk_cyc=0;
  string dir;
  integer fd,nread;
  assign poke_valid = pk_i < pk_n && pk_cyc >= pk_c[pk_i];
  assign poke_addr = pk_a[pk_i];
  assign poke_data = pk_v[pk_i];
  initial begin
{pipes}
    fd=0;
    if($value$plusargs(\"dir=%s\",dir)) begin
      fd=$fopen($sformatf(\"%s/dram_%0d.bin\",dir,SID),\"rb\");
    end
    for(int base=0;base<WORDS;base+=IMAGE_WORDS) begin
      for(int i=0;i<IMAGE_WORDS;i++) image[i]=0;
      if(fd!=0) nread=$fread(image,fd,0,((WORDS-base)<IMAGE_WORDS)?(WORDS-base):IMAGE_WORDS);
      for(int i=0;i<IMAGE_WORDS && base+i<WORDS;i++) begin
{initText}
      end
    end
    if(fd!=0) $fclose(fd);
    if($value$plusargs(\"dir=%s\",dir)) begin
      fd=$fopen($sformatf(\"%s/poke_%0d.txt\",dir,SID),\"r\");
      if(fd!=0) begin
        while(pk_n<64 && $fscanf(fd,\"%h %h %h\",pk_c[pk_n],pk_a[pk_n],pk_v[pk_n])==3) pk_n++;
        $fclose(fd);
      end
    end
  end
  always @(posedge clk) begin
    pk_cyc <= pk_cyc+1;
    if(poke_valid) pk_i <= pk_i+1;
    if(dump) begin
      fd=$fopen($sformatf(\"%s/dram_out_%0d.bin\",dir,SID),\"wb\");
      for(int i=0;i<WORDS;i++) $fwrite(fd,\"%u\",{dumpword});
      $fclose(fd);
    end
  end
`endif
endmodule
"
end OpenTPU.Dram
