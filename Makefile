.PHONY: check install

check:
	python3 scripts/check_skills.py

install:
	scripts/install_local.sh
