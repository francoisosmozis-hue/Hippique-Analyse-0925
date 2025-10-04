venv:
	python3 -m venv .venv && . .venv/bin/activate && pip install -U pip wheel && pip install -r requirements.txt

test:
	. .venv/bin/activate && pytest -q

run-h30:
	. .venv/bin/activate && python analyse_courses_du_jour_enrichie.py --course-url "$(URL)" --phase H30 --budget 5

run-h5:
	. .venv/bin/activate && python analyse_courses_du_jour_enrichie.py --course-url "$(URL)" --phase H5 --budget 5
