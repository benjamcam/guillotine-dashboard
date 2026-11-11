# Guillotine elimination odds dashboard

Live site: https://benjamcam.github.io/guillotine-dashboard/

This public GitHub Pages site shows a point-in-time estimate of which active ESPN Fantasy team has the highest chance of scoring lowest in the current guillotine week. It includes current actual points, live team projections, and lineup details from ESPN, along with a provisional score-variance model.

## Automatic refresh

A GitHub Actions workflow checks ESPN every 15 minutes and publishes a fresh static snapshot when projections are available. Scheduled runs can be delayed by GitHub. The dashboard does not connect to ESPN from a visitor's browser.

For refreshes to work, the repository owner must add two repository Actions secrets:

- `ESPN_S2`
- `ESPN_SWID`

Add them in **Settings → Secrets and variables → Actions → New repository secret**. These are sensitive ESPN session cookies. Do not put their values in a commit, issue, or public page. The workflow reads them only to make read-only ESPN API requests; it does not print them or include them in the published site. Until both secrets are set, scheduled workflow runs will skip publishing.

## Model note

The ESPN projections set expected points. Player score uncertainty currently uses provisional position-level standard deviations, so last-place percentages are estimates and are not calibrated guarantees.

## Lineups and projection what-if

Expand a team row to see its starters, actual points, projections, and played/remaining status. Edit a projection to recalculate and resort all teams' last-place percentages in the browser. These what-if edits are temporary, stay in the current page, and are cleared by refreshing ESPN data. Players who have already scored have locked projections. No changes are written to ESPN.
