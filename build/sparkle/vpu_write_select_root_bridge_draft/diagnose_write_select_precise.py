"""Same authenticated mapping probe with private precise dependency traversal."""
from types import FunctionType
import diagnose_write_select
from precise_write_select import closure


def main():
    scope=dict(diagnose_write_select.main.__globals__)
    scope['closure']=closure
    FunctionType(diagnose_write_select.main.__code__,scope)()

if __name__=='__main__':main()
