# Benchmark Plan

Every experiment compares Tiberium against a clearly identified baseline.

Record:
- task ID
- baseline route
- Tiberium proposed route
- input/output tokens
- number of LLM calls
- API monetary cost when known
- latency
- CPU/GPU/VRAM/RAM when measurable
- task quality
- abstention
- escalation
- verifier outcome
- unsafe false positive
- evidence completeness

Initial benchmark families:
1. deterministic transforms
2. structured extraction
3. repeated known cases
4. tool selection
5. GitHub/CI state reasoning
6. agent handoff selection
7. small planning fragments
8. anomaly classification
9. local-model vs cloud escalation
10. ShardJEPA-style fast decision routing

Primary reports:
- quality vs cost
- quality vs latency
- escalation rate
- unsafe false-positive rate
- savings by task family
- savings by hardware profile
- route stability across versions

A 90% token reduction with silent quality degradation is not a success.
