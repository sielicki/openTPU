module tb_tmem;
  parameter int WORDS=64, LANES=4, NRP=4, NWP=3, WPB=1;
  parameter logic [NRP-1:0] GEN_R='1, SH_MASK='0;
  parameter logic [NWP-1:0] GEN_W='1;
  parameter int SH_HOST=0;
  localparam int BW=$clog2(LANES), IW=$clog2(WORDS/LANES);
  bit clk=0;
  always #5 clk=~clk;
  logic [NRP-1:0][LANES-1:0] r_en=0,r_req=0;
  logic [NRP-1:0][LANES-1:0][31:0] r_addr=0;
  logic [NWP-1:0][LANES-1:0] w_en=0,w_req=0;
  logic [NWP-1:0] w_gnt=0;
  logic [NWP-1:0][LANES-1:0][31:0] w_addr=0,w_data=0;
  wire [NRP-1:0][LANES-1:0][31:0] gold,native_data;
  wire [LANES-1:0][WPB-1:0] selected_valid;
  wire [LANES-1:0][WPB-1:0][IW-1:0] selected_address;
  wire [LANES-1:0][WPB-1:0][31:0] selected_data;
  otpu_tmem #(.WORDS(WORDS),.LANES(LANES),.NRP(NRP),.NWP(NWP),.WPB(WPB),
    .GEN_R(GEN_R),.GEN_W(GEN_W),.SH_HOST(SH_HOST),.SH_MASK(SH_MASK)) golden(
    .clk,.r_en,.r_req,.r_addr,.r_data(gold),.w_en,.w_req,.w_gnt,.w_addr,.w_data,.dump(1'b0));
  otpu_tmem_sparkle native(.clk,.r_en,.r_req,.r_addr,.r_data(native_data),
    .w_en,.w_req,.w_gnt,.w_addr,.w_data,.selected_valid,.selected_address,.selected_data);
  logic [31:0] memory [WORDS];
  logic [NRP-1:0][LANES-1:0][31:0] expected=0;
  bit pending [WORDS];
  int used [LANES];
  int seed=32'h739bc541,dummy;
  int reads=0,writes=0,stalls=0,bypasses=0,collisions=0,guests=0,multiwrites=0;
  initial begin
    dummy=$urandom(seed);
    foreach(memory[a]) begin memory[a]=0; pending[a]=0; end
    for(int cyc=0;cyc<20000;cyc++) begin
      @(negedge clk);
      r_en=0; r_req=0; w_en=0; w_req=0; w_gnt=0;
      foreach(used[b]) used[b]=0;
      for(int p=0;p<NWP;p++) begin
        int base,rotation;
        bit grant;
        base=int'($urandom_range(0,WORDS-LANES));
        rotation=int'($urandom_range(0,LANES-1));
        if(cyc%5<2) begin base=0; rotation=0; end
        for(int l=0;l<LANES;l++) begin
          w_addr[p][l]=GEN_W[p] ? $urandom_range(0,WORDS/LANES-1)*LANES+((l+rotation)%LANES) : base+l;
          if(cyc%5<2) w_addr[p][l]=l;
          w_data[p][l]=$urandom;
          w_req[p][l]=$urandom_range(0,2)!=0;
        end
        grant=$urandom_range(0,3)!=0;
        for(int l=0;l<LANES;l++)
          if(w_req[p][l] && used[w_addr[p][l]%LANES]>=WPB) grant=0;
        w_gnt[p]=grant;
        if(grant) begin
          w_en[p]=w_req[p];
          for(int l=0;l<LANES;l++) if(w_en[p][l]) used[w_addr[p][l]%LANES]++;
        end else if(|w_req[p]) stalls++;
      end
      for(int p=0;p<NRP;p++) begin
        int base,rotation;
        base=int'($urandom_range(0,WORDS-LANES));
        rotation=int'($urandom_range(0,LANES-1));
        if(cyc%5<3) begin base=0; rotation=0; end
        for(int l=0;l<LANES;l++) begin
          r_addr[p][l]=GEN_R[p] ? $urandom_range(0,WORDS/LANES-1)*LANES+((l+rotation)%LANES) : base+l;
          if(cyc%5<3) r_addr[p][l]=l;
          if(GEN_R[p] && cyc%7==0) r_addr[p][l]=base; // broadcast of one word
          r_req[p][l]=$urandom_range(0,2)!=0;
        end
        // Leave whole ports idle often enough that low-priority guests get reads.
        if($urandom_range(0,2)==0) r_req[p]=0;
      end
      for(int p=0;p<NRP;p++) begin
        bit grant;
        grant=$urandom_range(0,3)!=0;
        if(SH_MASK[p]) begin
          if(|r_req[SH_HOST]) grant=0;
          for(int g=0;g<p;g++) if(SH_MASK[g] && |r_req[g]) grant=0;
        end
        if(grant) r_en[p]=r_req[p];
        else if(|r_req[p]) stalls++;
      end
      // Logical read-before-write scoreboard, independent of physical bank copies.
      for(int p=0;p<NRP;p++) for(int l=0;l<LANES;l++) if(r_en[p][l]) begin
        expected[p][l]=memory[r_addr[p][l]];
        reads++;
        if(pending[r_addr[p][l]]) bypasses++;
        if(SH_MASK[p]) guests++;
        for(int w=0;w<NWP;w++) for(int k=0;k<LANES;k++)
          if(w_en[w][k] && w_addr[w][k]==r_addr[p][l]) collisions++;
      end
      foreach(pending[a]) pending[a]=0;
      for(int p=0;p<NWP;p++) for(int l=0;l<LANES;l++) if(w_en[p][l]) begin
        memory[w_addr[p][l]]=w_data[p][l];
        pending[w_addr[p][l]]=1;
        writes++;
      end
      foreach(used[b]) if(used[b]>1) multiwrites++;
      #1;
      if({selected_valid,selected_address,selected_data} !== {golden.bw_v,golden.bw_a,golden.bw_d})
        $fatal(1,"TMEM selected-write mismatch at cycle %0d",cyc);
      @(posedge clk); #1;
      if(cyc>2 && (native_data !== gold || native_data !== expected))
        $fatal(1,"TMEM cycle %0d WPB=%0d gold=%h native=%h expected=%h",cyc,WPB,gold,native_data,expected);
    end
    if(reads<100 || writes<100 || stalls<100 || bypasses<100 || collisions<100 ||
       (SH_MASK!=0 && guests<100) || (WPB>1 && multiwrites<100))
      $fatal(1,"insufficient TMEM exercise");
    $display("PASS TMEM WORDS=%0d LANES=%0d WPB=%0d GEN_R=%h GEN_W=%h SH_MASK=%h 20000 cycles reads=%0d writes=%0d stalls=%0d bypasses=%0d collisions=%0d guests=%0d multiwrites=%0d",
      WORDS,LANES,WPB,GEN_R,GEN_W,SH_MASK,reads,writes,stalls,bypasses,collisions,guests,multiwrites);
    $finish;
  end
endmodule
