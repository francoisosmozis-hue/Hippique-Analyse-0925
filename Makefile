.PHONY: compile helpcheck importcheck doctor
compile:
	python - <<'PY'
import py_compile, sys
from pathlib import Path
skip={'.venv','.git','.github','data','dist','build','excel','out','cache','__pycache__'}
errs=[]
for p in Path('.').rglob('*.py'):
    if any(part in skip for part in p.parts): continue
    try: py_compile.compile(str(p), doraise=True)
    except Exception as e: errs.append((str(p), e))
if errs:
    print('== Syntax errors ==')
    for f,e in errs: print(' -', f, '->', e); sys.exit(1)
print('Syntax OK')
PY
helpcheck:
	python tools/ci_check.py --mode helpcheck --timeout 5
importcheck:
	python tools/ci_check.py --mode importcheck --timeout 5
doctor: compile helpcheck
