"""Actual safetensors parity with optional bounded aggregate tensor caching."""
import json

import numpy as np
import pytest
import torch
from safetensors.torch import save_file

from opentpu.llm.qwen3 import Weights


@pytest.fixture
def checkpoint(tmp_path):
    values={name:torch.arange(8,dtype=torch.float16)+i for i,name in enumerate(('a','b','c'))}
    values['large']=torch.arange(24,dtype=torch.float16)
    values['larger']=torch.arange(32,dtype=torch.float16)
    values['model.layers.0.self_attn.qkv_proj.weight']=torch.arange(24,dtype=torch.float16).reshape(6,4)
    values['model.layers.0.mlp.gate_up_proj.weight']=torch.arange(16,dtype=torch.float16).reshape(4,4)
    save_file(values,tmp_path/'model.safetensors')
    (tmp_path/'config.json').write_text(json.dumps({'hidden_size':4,'num_attention_heads':2,
        'num_key_value_heads':1,'head_dim':1,'intermediate_size':2}))
    return tmp_path


def cache_sum(weights):
    assert weights._small_bytes==sum(v.nbytes for v in weights._small.values())
    if weights._small_budget is not None:assert weights._small_bytes<=weights._small_budget


def test_lru_hits_eviction_and_caller_lifetime(checkpoint,monkeypatch):
    monkeypatch.setenv('OTPU_WEIGHT_CACHE_BYTES','64')
    w=Weights(checkpoint)
    a=w['a'];b=w['b'];assert w['a'] is a
    w['c'];cache_sum(w)
    assert list(w._small)==['a','c']
    assert np.array_equal(b,np.arange(8,dtype=np.float32)+1)
    assert np.array_equal(w['b'],b)
    assert list(w._small)==['c','b'];cache_sum(w)


@pytest.mark.parametrize('budget',['0','16','64','128'])
def test_all_mapping_values_and_fused_aliases_survive_evictions(checkpoint,monkeypatch,budget):
    monkeypatch.delenv('OTPU_WEIGHT_CACHE_BYTES',raising=False)
    reference=Weights(checkpoint)
    expected={name:reference[name].copy() for name in reference}
    monkeypatch.setenv('OTPU_WEIGHT_CACHE_BYTES',budget)
    w=Weights(checkpoint)
    assert set(w)==set(expected) and len(w)==len(expected)
    for names in (list(expected),list(reversed(expected)),list(expected)):
        for name in names:
            assert name in w
            assert np.array_equal(w[name].view(np.uint32),expected[name].view(np.uint32))
            cache_sum(w)
    assert np.array_equal(w['model.layers.0.self_attn.q_proj.weight'],expected['model.layers.0.self_attn.qkv_proj.weight'][:2])
    assert np.array_equal(w['model.layers.0.self_attn.k_proj.weight'],expected['model.layers.0.self_attn.qkv_proj.weight'][2:3])
    assert np.array_equal(w['model.layers.0.self_attn.v_proj.weight'],expected['model.layers.0.self_attn.qkv_proj.weight'][3:4])
    assert np.array_equal(w['model.layers.0.mlp.up_proj.weight'],expected['model.layers.0.mlp.gate_up_proj.weight'][2:])


def test_absent_budget_preserves_unlimited_small_cache(checkpoint,monkeypatch):
    monkeypatch.delenv('OTPU_WEIGHT_CACHE_BYTES',raising=False)
    w=Weights(checkpoint)
    arrays={name:w[name] for name in w}
    assert w._small_budget is None
    assert all(w[name] is value for name,value in arrays.items())
    cache_sum(w)


def test_single_large_cache_is_independent_of_small_budget(checkpoint,monkeypatch):
    monkeypatch.setattr(Weights,'CACHE',64)
    monkeypatch.setenv('OTPU_WEIGHT_CACHE_BYTES','16')
    w=Weights(checkpoint)
    large=w['large'];assert w['large'] is large
    w['a'];assert not w._small and w['large'] is large
    larger=w['larger'];assert w['larger'] is larger and w._big[0]=='larger'
    assert np.array_equal(w['large'],large) and w._big[0]=='large'
    cache_sum(w)


@pytest.mark.parametrize('value',['','-1','+1',' 32','32 ','1.0','1e3','0x20','٣٢','true'])
def test_malformed_budget_rejected_before_opening_checkpoint(tmp_path,monkeypatch,value):
    monkeypatch.setenv('OTPU_WEIGHT_CACHE_BYTES',value)
    with pytest.raises(ValueError,match='nonnegative decimal integer'):Weights(tmp_path/'absent')
