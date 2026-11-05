"""SAS/R -> Python rebuild agent. Owner: A2.

Uses the mapping table from the KB (search_kb collection='mapping'), generates python, runs it
with run_sandbox and checks run_parity; the parity diff is the feedback for the next attempt.
Implements mrf.contracts.agents.Rebuilder (and ModelRunner for usability runs).
"""
