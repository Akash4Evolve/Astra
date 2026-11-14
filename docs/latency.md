# ASTRA latency (measured by scripts/demo.py)

- Measured: 2026-11-14T21:06:07+00:00
- Python 3.11.9, in-memory store, local HTTP on the same machine, 21 simulated days of data
- Round-trip time seen by the client, including HTTP. Numbers change from machine to machine.

```
POST /measurements (1 day)  n= 16  median=  14.9 ms  p95=  24.3 ms  max=  27.5 ms
GET  dashboard              n= 30  median=  14.0 ms  p95=  26.8 ms  max=  27.6 ms
GET  twin                   n= 30  median=   2.4 ms  p95=  26.4 ms  max=  28.5 ms
```
