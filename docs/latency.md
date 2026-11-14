# ASTRA latency (measured by scripts/demo.py)

- Measured: 2026-11-14T20:08:48+00:00
- Python 3.11.9, in-memory store, local HTTP on the same machine, 21 simulated days of data
- Round-trip time seen by the client, including HTTP. Numbers change from machine to machine.

```
POST /measurements (1 day)  n= 16  median=   1.4 ms  p95=  16.2 ms  max=  16.4 ms
GET  dashboard              n= 30  median=   1.5 ms  p95=  22.6 ms  max=  25.4 ms
GET  twin                   n= 30  median=   1.8 ms  p95=  17.8 ms  max=  17.9 ms
```
