"""Test production verdict/count functions without importing Isaac Gym."""
import ast
from pathlib import Path
import torch

p = Path(__file__).with_name('evaluate_walk.py')
tree = ast.parse(p.read_text())
tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('render_verdicts', 'classify_terminations')]
scope = {}
exec(compile(ast.fix_missing_locations(tree), str(p), 'exec'), scope)
counts = {k:int(v.sum()) for k,v in scope['classify_terminations'](
    torch.tensor([False,True,True]), torch.tensor([True,False,True])).items()}
assert counts == {'reset_total':2,'non_timeout_reset':1,'episode_timeout_reset':1,'command_boundary_without_reset':1}
assert scope['render_verdicts'](1200,0,True,False) == ('FAIL','INSUFFICIENT_COVERAGE')
assert scope['render_verdicts'](1200,1200,False,False) == ('PASS','OK')
print('PASS: real termination classification counts physical and timeout events; nonfinite/incomplete coverage fails')
