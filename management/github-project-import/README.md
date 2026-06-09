# GitHub Project Import

Use `current-iteration-items.csv` as the staging file for GitHub Project items.

GitHub Projects does not read a Git commit as Project rows automatically. Create GitHub Issues from these rows, add the issues to the Project, then set the Project iteration field to the current iteration. `@current` is a local placeholder for that step, not a GitHub CSV magic value.

Recommended issue fields:

- `Title`: issue title
- `Body`: issue body
- `Status`: Project status, usually `Todo`
- `Iteration`: set this to the Project's current iteration after import
- `Labels`: comma-separated labels to apply to the issue
