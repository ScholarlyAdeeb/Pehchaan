# Sample data

Demo document images live here on each machine. Nothing in this folder is
committed except this file: identity documents, real or generated, do not
belong in a repository.

Create the three demo passports from the generated dataset:

```bash
cd backend
.venv\Scripts\python scripts\make_demo_samples.py
```

| File | Expected result |
|---|---|
| `demo_passport_genuine.jpg` | CLEAR |
| `demo_passport_tampered.jpg` | HIGH RISK: the expiry year was altered, so the check digits fail |
| `demo_passport_clone.jpg` | HIGH RISK: the MRZ holder differs from the printed page |

The script needs `backend/training/data_generated/`, which
`backend/scripts/cardgen` builds from the blank templates kept in
`sample-data/templates/`.
