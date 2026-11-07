# Aircraft Selection Test Fixtures — Provenance and Licensing

## 1. Recorded Decoder Fixture (`recorded_readsb_perpignan_2022.json`)

- **File:** `recorded_readsb_perpignan_2022.json`
- **Kind:** Real recorded `readsb` / `dump1090` `aircraft.json` output (unmodified bytes)
- **Source repository:** `https://github.com/LunnosMp4/Dump1090-Web-Modern`
- **Source path:** `backend/aircraft.json`
- **Source commit:** `c1203e3ecdd28bae6159e48046018900c1bd8795` (`2022-08-10T14:53:11Z`)
- **Git blob SHA-1:** `51e1c0366016b9940e936dd2e62a124b5f2f3b8d`
- **Captured timestamp (`now`):** `1659548165.407` (`2022-08-03T17:36:05.407Z`)
- **License:** MIT License

```text
MIT License

Copyright (c) 2022 Loïc Tisseyre

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 2. Synthetic Contract Fixtures (`synthetic_*.json`)

All files prefixed with `synthetic_` are deterministic synthetic fixtures authored for
Phlight to test specific boundary conditions of `docs/aircraft-selection-contract.md`
at controlled timestamp `now = 1760000000.0`. They are not live receiver recordings
and do not claim hardware reception validation.
