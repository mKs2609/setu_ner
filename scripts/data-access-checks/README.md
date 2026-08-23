# data-access-checks

Throwaway scripts, not production ingestion code. Run these locally (this
sandbox's own network is restricted and can't reach Indian government
domains -- both scripts were verified for correctness here but return
`host_not_allowed`/403 from this environment specifically).

```bash
pip install requests
python check_cwc_nwdp_access.py
python check_asdma_access.py
```

Paste the summary output into `docs/decisions/0002-corridor-selection.md`
once you've run them, and use the decision guide each script prints to
inform the ingestion design in `docs/decisions/0001` §1.
