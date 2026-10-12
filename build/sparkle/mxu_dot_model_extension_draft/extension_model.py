"""Source-pinned constructive model-extension rules, not X-to-zero lifting.

The source identity pins the complete implementation, including expression
constructors. ANCHORS locate the manually reviewed cases within that identity;
they are not a substitute for the full immutable-file/NAR authentication.
"""
from pathlib import Path
from sharing_model_rules import model_rules,SATGEN_CC_SHA,SATGEN_HEADER_SHA
from dot_initial_store import need
from extension_graph import TYPES

CC_ANCHORS=(
    'int undef_y_bit = ez->OR(undef_any_a, undef_any_b);',
    'std::vector<int> undef_y_bits(undef_y.size(), undef_y_bit);',
    'if (cell->type.in(ID($_NOT_), ID($not)))',
    'if (cell->type.in(ID($logic_and), ID($logic_or)))',
    'if (cell->type == ID($logic_not))',
    'if (cell->type == ID($pmux))',
    'all_undef = ez->OR(all_undef, ez->AND(s.at(i), found_active));',
    'undef_tmp = ez->vec_or(undef_tmp, std::vector<int>(a.size(), all_undef));',
    'yy.at(0) = ez->AND(yy.at(0), ez->vec_eq(undef_a, undef_b));',
    'int undef_y_bit = ez->AND(undef_any, ez->NOT(masked_ne));',
    'undef_a_shifted = ez->vec_shift_right(undef_a, b, cell->parameters[ID::B_SIGNED].as_bool(), ez->CONST_TRUE, ez->CONST_TRUE);',
    'std::vector<int> undef_all_y_bits(undef_y.size(), undef_any_b);',
    'ez->assume(ez->vec_eq(ez->vec_or(undef_a_shifted, undef_all_y_bits), undef_y));',
)
HEADER_ANCHORS=(
    'if (model_undef && dup_undef && bit == RTLIL::State::Sx)',
    'vec.push_back(ez->frozen_literal());',
    'vec.push_back(bit == (undef_mode ? RTLIL::State::Sx : RTLIL::State::S1) ? ez->CONST_TRUE : ez->CONST_FALSE);',
    'is_signed = cell->parameters[ID::A_SIGNED].as_bool() && cell->parameters[ID::B_SIGNED].as_bool();',
    'vec_y.push_back(ez->literal());',
    'ez->vec_or(vec_undef, ez->vec_iff(trunc_y, trunc_yy))',
    'ez->vec_or(vec_undef, ez->vec_iff(vec_y, vec_yy))',
    'undef_res = ez->vec_ite(undef_s, undef_ab, ez->vec_ite(s, undef_b, undef_a));',
)


def authenticate_extension_model(binary,source,freeze):
    _,model=model_rules(binary,freeze,source)
    source=Path(source).resolve()
    cc=source/'kernel/satgen.cc';header=source/'kernel/satgen.h'
    need(freeze(cc,SATGEN_CC_SHA)==model['satgen_cc_sha256'],'model source identity mismatch')
    need(freeze(header,SATGEN_HEADER_SHA)==model['satgen_header_sha256'],'model header identity mismatch')
    ctext=cc.read_text();htext=header.read_text()
    need(all(anchor in ctext for anchor in CC_ANCHORS),'total-relation primitive anchor differs')
    need(all(anchor in htext for anchor in HEADER_ANCHORS),'signal import/extension/gating anchor differs')
    return {'source_authentication':model,'accepted_cell_types':sorted(TYPES),
            'model_undef':True,'literal_z_accepted':False,
            'rule':'every schema-valid acyclic cell relation extends every assignment of input value and undefined bits',
            'witness':'compute internal value expression and output undefined mask; choose each known output equal to its expression and any value for each unknown output',
            'literal_x':'fresh value per importDefSigSpec use; undefined mask one; no cross-use correlation introduced',
            'named_wire_aliases':'same integer net coordinate preserves common value/mask identity',
            'unknown_input_restrictions':[],
            'binary_X_to_zero_compatibility_claimed':False,
            'concrete_initialized_theorem_claimed':False}
