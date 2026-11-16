# Live validation checklist

Use a disposable repository created from this template, with the same visibility
and GitHub plan as your intended projects. You need a repository administrator,
the designated maintainer, and a second contributor with write access to test roles.
Follow the [setup guide](repository-setup.md), including successful CI on both
branches, preview, apply and read-back verification.

Record the repository URL, date, tested commit, actor, PR or run URL, and actual
result for each case. This checklist has not been executed by the local test suite.

| Case | Expected result |
| --- | --- |
| Designated maintainer pushes a new commit directly to `main` or `dev` | Rejected on both branches |
| Other contributor pushes directly to `main` or `dev` | Rejected on both branches |
| PR to either branch has a failing required CI job | Merge blocked, including for the designated maintainer |
| PR to either branch has an unresolved review conversation | Merge blocked |
| Other contributor opens a PR changing `.github/`, `policies/`, `scripts/` or `tests/` | Code-owner review required; test without using the owner's review bypass |
| Owner approves a sensitive PR, then contributor pushes another reviewable commit | Previous approval dismissed; fresh review required |
| Designated maintainer authors a sensitive PR | Successful CI required; explicit review bypass allows merge without self-approval |
| Other contributor attempts to merge an ordinary passing PR to either `main` or `dev` | CI runs and merge is blocked |
| Designated maintainer merges a passing PR from `dev` to `main` | Allowed; `dev` remains available |
| Designated maintainer merges an ordinary passing PR to `dev` | Allowed without a mandatory approval |
| Attempt to force-push or delete either protected branch | Rejected |
| Rerun configuration with identical arguments | Same three managed rulesets updated; unrelated rulesets preserved |

Use actual changes to exercise push restrictions, rather than pushing an unchanged
ref. Do not infer enforcement from the merge button alone: record the server's
rejection or successful operation. Check **Settings → Rules → Rulesets** for
inherited rules that could make results stricter than this template.

For the failing-CI case, introduce a temporary failing test in a PR and restore it
after recording the result. Disable automatic head-branch deletion before testing
promotion PRs. Do not run force-push or deletion probes against a production repository.
