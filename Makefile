.PHONY: help run pass1 triage pass2 grade patterns report test clean

help:
	@echo "make run      full pipeline (stub backend, no credentials)"
	@echo "make pass1    broad discovery -> out/pass1.json (FROZEN)"
	@echo "make pass2    targeted verification -> out/pass2.json"
	@echo "make grade    accuracy vs gold set -> out/accuracy.json"
	@echo "make report   single-page HTML -> out/report.html"
	@echo "make test     trigger + schema tests"

run: pass1 pass2 patterns report
	@echo "\nDone. Open out/report.html"

pass1:
	python -m src.pass1_discover

triage: 
	python -m src.pass2_verify --help >/dev/null && python -m src.pass2_verify

pass2:
	python -m src.pass2_verify

grade:
	python -m src.grade

patterns:
	python -m src.patterns

report:
	python -m src.report

test:
	python -m pytest tests/ -q

clean:
	rm -f out/*.json out/*.html
