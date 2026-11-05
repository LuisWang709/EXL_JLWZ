"""Documentation rater. Owner: A3.

Rule checks (60): SS1/23 section completeness 20, every claim has evidence 20, variables match
parse_code output 20. LLM reviewer (40) with an independent prompt. Pass: total >= 80 and no veto.
Rubric: src/mrf/rating/rubric.yaml. Implements mrf.contracts.agents.Rater.
"""
