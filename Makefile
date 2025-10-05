.RECIPEPREFIX := >
.PHONY: compile helpcheck importcheck doctor

compile:
> python tools/compile_check.py

helpcheck:
> python tools/ci_check.py --mode helpcheck --timeout 5

importcheck:
> python tools/ci_check.py --mode importcheck --timeout 5

doctor: compile helpcheck
