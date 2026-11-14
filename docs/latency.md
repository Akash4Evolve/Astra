# ASTRA latency (measured by scripts/demo.py)

- Measured: 2026-11-14T18:03:14+00:00
- Python 3.11.9, in-memory store, local HTTP on the same machine, 21 simulated days of data
- Round-trip time seen by the client, including HTTP. Numbers change from machine to machine.

```
POST /measurements (1 day)  n= 16  median=   1.5 ms  p95=  13.8 ms  max=  21.7 ms
GET  dashboard              n= 30  median=   1.6 ms  p95=  17.7 ms  max=  23.5 ms
GET  twin                   n= 30  median=   1.6 ms  p95=  16.0 ms  max=  19.7 ms
```
