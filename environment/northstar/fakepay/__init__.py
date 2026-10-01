"""FakePay: a small, deterministic, simulated external payment processor.

FakePay runs as its own service with its own database. It shares no code or
storage with Northstar; Northstar talks to it only over its HTTP API.
"""
