"""Streaming exact assertion-only assembly normalization; no hardware rewriting."""
from pathlib import Path
from check_sparkle_se_tail_assertion_assemblies import module_spans,exact_whole_assembly
from check_sparkle_fpga_top_complete import require,tokens

def guarded_block(text):
    marker='`ifndef SYNTHESIS\n'
    require(text.count(marker)==1 and text.endswith('`endif\nendmodule\n'),'Qualified exact end-of-module observer guard absent')
    return marker+text.split(marker)[1][:-len('endmodule\n')]

def normalize(source,destination,current,core_block,wrapper_block):
    spans=module_spans(source);require('otpu_se_comp_sparkle' in spans,'Composite core absent')
    target='otpu_se_comp_sparkle' if current else 'otpu_se_comp'
    expected=core_block if current else wrapper_block
    # Keep parsing/token comparison bounded to the small diagnostics block.
    expected_path=Path(str(destination)+'.expected-block.sv');expected_path.write_text(expected)
    actual_path=Path(str(destination)+'.actual-block.sv')
    expected_tokens=list(tokens(expected_path));removed=0;number=0
    with Path(source).open() as src,Path(destination).open('w') as dst:
        for line in src:
            number+=1
            inside=target in spans and spans[target][0]<number<spans[target][1]
            if inside and line.strip()=='`ifndef SYNTHESIS':
                first=number;block=[line]
                for row in src:
                    number+=1;block.append(row)
                    require(sum(map(len,block))<=256*1024,'Oversized diagnostic block')
                    if row.strip()=='`endif':break
                require(block[-1].strip()=='`endif' and number+1==spans[target][1],
                        'Observer is not the complete final guarded block')
                actual_path.write_text(''.join(block))
                require(list(tokens(actual_path))==expected_tokens,'Actual diagnostic predicates/ROM/messages changed')
                removed+=1;continue
            dst.write(line)
    require(removed==(1 if current or target in spans else 0),'Missing/duplicate required diagnostic block')
    return {'target':target,'removed_blocks':removed,'spans':spans}
