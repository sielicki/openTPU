import json
from pathlib import Path
import sqlite3
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from inspect_literal_paths import trace,same


def db():
    conn=sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE driver(design,bit,kind,name,pin,idx)')
    conn.execute('CREATE TABLE owner(design,module,kind,name,data)')
    conn.execute("INSERT INTO driver VALUES('probe',1,'input','retained_7','retained_7',0)")
    return conn


def mux(conn,selector='0',a=1,b='x',width='1'):
    body={'type':'$mux','parameters':{'WIDTH':width},'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
        'connections':{'A':[a],'B':[b],'S':[selector],'Y':[2]}}
    conn.execute("INSERT INTO driver VALUES('probe',2,'cell','m','Y',0)")
    conn.execute("INSERT INTO owner VALUES('probe','paired','cells','m',?)",(json.dumps(body),))


def test_defined_selected_root_with_unknown_other_arm():
    conn=db();mux(conn)
    result=trace(conn,2)
    assert same(result,trace(conn,1)) and result['steps'][0]['selected_pin']=='A'


def test_unknown_selected_root_never_identical():
    conn=db();mux(conn,selector='1')
    result=trace(conn,2);assert result['terminal']=={'literal':'x'}
    assert not same(result,result)


def test_dynamic_selector_stops_without_guess():
    conn=db();mux(conn,selector=1)
    result=trace(conn,2);assert result['terminal']['opaque_bit']==2
    assert not same(result,result)


def test_invalid_width_rejected():
    conn=db();mux(conn,width='10')
    with pytest.raises(ValueError,match='schema differs'):trace(conn,2)


def test_cycle_rejected():
    conn=db();mux(conn,a=2)
    with pytest.raises(ValueError,match='cycle'):trace(conn,2)
