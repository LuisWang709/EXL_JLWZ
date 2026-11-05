"""Model identification agent. Owner: A1.

Static parse (parse_code tool) -> LLM extraction of algorithm/purpose with a JSON schema ->
confidence fusion; confidence < classification.min_confidence -> MRF-2002 + manual review.
Implements mrf.contracts.agents.Classifier.
"""
