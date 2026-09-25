# data-access-checks

Diagnostics, not production ingestion code: they probe a government source and
print what actually came back, so a claim about availability can be checked
rather than assumed.

```bash
pip install requests
python check_cwc_nwdp_access.py
python check_asdma_access.py
```

`check_cwc_nwdp_access.py` is what found CWC's dated bulletin URLs returning
404 for every date, which moved live ingestion to DRIMS
(`docs/decisions/0004`). Re-running it is how you would find out if CWC
resumed publishing.
