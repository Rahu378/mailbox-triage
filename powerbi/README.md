# Power BI report

The report reads the views in `sql/views.sql` through the PostgreSQL connector (Import or DirectQuery).
Load the theme with View > Themes > Browse for themes > `theme.json`, then add the measures from `measures.dax`.

## Model

| Table | Grain | Key |
|---|---|---|
| `vw_triage` | one row per email | `email_id` |
| `vw_daily_volume` | day x category x route | - |
| `vw_open_queues` | one row per queue | `queue` |
| `vw_t1_at_risk` | one row per at-risk ticket | `email_id` |
| `vw_draft_turnaround` | one row per draft | `email_id` |
| `vw_counterparty_fails` | one row per counterparty | `counterparty` |

`vw_t1_at_risk` and `vw_draft_turnaround` relate to `vw_triage` on `email_id` (many-to-one, single direction).
Add a date table and mark it as one: `Date = CALENDAR ( DATE ( 2026, 1, 1 ), DATE ( 2026, 12, 31 ) )`, then relate
`'Date'[Date]` to `vw_triage[received_day]`.

## Pages

1. **Today**: cards for Emails Received, Auto-handled %, T+1 At Risk, Open SSI Call-backs, Drafts Awaiting Approval.
   Stacked column of `vw_daily_volume` by day and category. Table of `vw_t1_at_risk` sorted by settlement date.
2. **Queues**: `vw_open_queues` with the age of the oldest item (conditional formatting past 2 hours),
   Median Minutes To Approve, review reasons from `vw_triage[reasons]`.
3. **Counterparties**: `vw_counterparty_fails`, fails due or past due, by counterparty.

The GitHub Pages site has a web version of these pages, built from the same numbers.
