.PHONY: run test eval mcp

run:
	streamlit run app.py

test:
	pytest -q

eval:
	python scripts/evaluate.py

mcp:
	python -m trip_planner.mcp_server
