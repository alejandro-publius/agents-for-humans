# BART API fixtures

Used whenever `BART_API_KEY` is unset (every test and eval). Every file carries a `_fixture` object
saying whether it is a verbatim documented sample, a repaired one, or synthetic.

| File | Endpoint | Provenance |
| --- | --- | --- |
| `elev_sample.json` | `bsa.aspx?cmd=elev` | Verbatim documented sample: "There is 1 elevator out of service at this time: DELN: Platform - Richmond". |
| `elev_multi.json` | `bsa.aspx?cmd=elev` | **Synthetic.** Three outages (DELN, SANL, PLZA) in the documented phrasing; the `;` separator is an assumption. |
| `elev_changed.json` | `bsa.aspx?cmd=elev` | **Synthetic.** The snapshot after `elev_multi`: DELN cleared, EMBR added. For poller diff tests. |
| `elev_none.json` | `bsa.aspx?cmd=elev` | **Synthetic.** No outages; BART's real no-outage wording is not documented. |
| `bsa_sample.json` | `bsa.aspx?cmd=bsa` | Documented sample, one typo removed. |
| `etd_RICH.json` | `etd.aspx?cmd=etd&orig=RICH` | Documented sample, missing commas inserted. |
| `depart_ASHB_CIVC.json` | `sched.aspx?cmd=depart` | Verbatim documented sample (historical schedule 45). |
| `depart_<ORIG>_<DEST>.json` (six files) | `sched.aspx?cmd=depart` | **Synthetic.** Per-pair schedules for the policy tests (SANL/EMBR/BAYF, EMBR/PLZA/DELN); head stations chosen for BART's two worked examples, times are placeholders. |
| `stns.json` | `stn.aspx?cmd=stns` | **Derived.** All 50 names and abbreviations from BART's abbreviation table; coordinates omitted. |
| `stnaccess_12TH.json` | `stn.aspx?cmd=stnaccess&orig=12TH` | Documented sample, re-serialized because the printed sample is not valid JSON. |

No file here came from a live call. A human with a key can record real responses later; see
docs/reports/day-1.md.
