# Key numbers

Run kind: **full**. All radio/phone/human parameters are *assumed* unless a measured trace is in `paper/real/` (see E12/E13).

* **E01 false-absent, 93 students, door closed:** 0.37% (95% CI 0.24-0.52)
* **E01 corridor admitted, 93 students, door open:** 1.75% (95% CI 0.00-4.50)
* **E01 false-absent, 20 students (stated limit):** 4.94% (95% CI 3.17-7.41)
* **E03 collusion, k=1: friend admitted with 1 / 2 / 3 accomplices:** 100% (95% CI 100-100) / 100% (95% CI 100-100) / 100% (95% CI 100-100)
* **E03 collusion, k=2: friend admitted with 1 / 2 / 3 accomplices:** 0% (95% CI 0-0) / 100% (95% CI 100-100) / 100% (95% CI 100-100)
* **E03 collusion, k=3: friend admitted with 1 / 2 / 3 accomplices:** 0% (95% CI 0-0) / 0% (95% CI 0-0) / 100% (95% CI 100-100)
* **E03 relay (3 relays), co-location OFF: admitted / flagged / honest flagged:** 100.0% (95% CI 100.0-100.0) / 0.0% (95% CI 0.0-0.0) / 0.00% (95% CI 0.00-0.00)
* **E03 relay (3 relays), co-location ON: admitted / flagged / honest flagged:** 2.2% (95% CI 0.6-4.4) / 97.8% (95% CI 95.6-99.4) / 0.00% (95% CI 0.00-0.00)
* **E04 12 dB iPhone TX asymmetry, 50% iOS: self-cal OFF -> ON:** 29.5% (95% CI 22.8-36.9) -> 0.36% (95% CI 0.17-0.59)
* **E04 fresh server (no per-model offset table), 20 students: with table -> without:** 6.2% (95% CI 2.4-11.9) -> 42.1% (95% CI 30.7-52.6)
* **E05 wait for the verdict, window 20 s, tap median 4 s: p50 / p95 (s); manual roll call total (s):** 31 / 34; manual 264
* **E09 B0 manual roll call (door open, 30% iOS): false-absent / corridor admitted / proxy succeeds / time s:** 0.0% (95% CI 0.0-0.0) / 0.0% (95% CI 0.0-0.0) / 52% (95% CI 47-58) / 264
* **E09 B1 teacher beacon (door open, 30% iOS): false-absent / corridor admitted / proxy succeeds / time s:** 30.0% (95% CI 28.7-31.4) / 6.9% (95% CI 4.6-9.4) / 30% (95% CI 25-35) / 20
* **E09 B2 acoustic (v1) (door open, 30% iOS): false-absent / corridor admitted / proxy succeeds / time s:** 32.8% (95% CI 31.5-34.3) / 0.0% (95% CI 0.0-0.0) / 30% (95% CI 25-35) / 20
* **E09 B5 rotating QR (door open, 30% iOS): false-absent / corridor admitted / proxy succeeds / time s:** 3.3% (95% CI 2.9-3.9) / 0.0% (95% CI 0.0-0.0) / 30% (95% CI 25-35) / 20
* **E09 NetPresence (door open, 30% iOS): false-absent / corridor admitted / proxy succeeds / time s:** 0.4% (95% CI 0.2-0.6) / 0.0% (95% CI 0.0-0.0) / 2% (95% CI 0-4) / 26
* **E09 NetPresence, no co-location (door open, 30% iOS): false-absent / corridor admitted / proxy succeeds / time s:** 0.4% (95% CI 0.2-0.6) / 0.0% (95% CI 0.0-0.0) / 100% (95% CI 100-100) / 26
* **E11 200 students false-absent, ttl 8 -> ttl 12:** 12.2% (95% CI 8.7-15.2) -> 0.3% (95% CI 0.1-0.5)
* **E14 energy per roll call (assumed currents):** 1.0451 mAh = 0.157% of a 4000 mAh battery per day (6 lectures)

## Not measured on real phones
E12 (simulator vs real sessions) and E13 (trace-driven channel) need data in `paper/real/`; until then they are labelled NO REAL DATA / SYNTHETIC.
