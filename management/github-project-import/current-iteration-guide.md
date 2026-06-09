# Current Iteration Guide

Project URL: https://github.com/users/LN-676/projects/2/views/1

## What Git Can Push

Git can push files and commits only to a GitHub repository, not directly to a GitHub Project board.

The Project board reads work items from:

- GitHub Issues
- Pull requests
- Draft issues inside the Project

Recommended flow:

1. Push this repository to GitHub.
2. Create GitHub Issues from `current-iteration-items.csv`.
3. Add those issues to the Project.
4. Set the Project's `Iteration` field to the current iteration.

## Current Iteration Format

For GitHub Projects, current iteration is controlled by an `Iteration` custom field.

Use these formats:

- In Project filters: `iteration:@current`
- In issue titles/bodies: normal Markdown
- In CSV staging files: one row per issue/task, with columns like `Title`, `Body`, `Status`, `Iteration`, and `Labels`
- In GraphQL/API automation: use the Project item ID, the Iteration field ID, and the actual iteration option ID

`@current` is useful in Project filters. For setting a row's field value, GitHub usually needs the actual current iteration value selected in the Project UI or set through the API.

## Recommended CSV Columns

Use this shape when preparing work outside GitHub:

```csv
Title,Body,Status,Iteration,Labels
"Implement video source interfaces","Task details...","Todo","@current","autocamtracker,backend"
```

If importing manually, create issues first, add them to the Project, then bulk-edit the Project rows and set `Iteration` to the visible current iteration.

## Why Team Members May Not See the Project

Common causes:

- The GitHub Project is owned by your personal account, not an organization.
- Adding teammates to LINE does not grant GitHub access.
- They are not collaborators on the repository that contains the issues.
- They do not have access to the personal Project.
- The Project visibility is private.
- They are logged into a different GitHub account.
- The Project has issues from a private repository they cannot access.

For classmates or teammates, the simplest setup is:

1. Add them as collaborators on the GitHub repository.
2. Add repository issues to the Project.
3. Make sure the Project is visible to them, or move the Project under a GitHub organization/team.
