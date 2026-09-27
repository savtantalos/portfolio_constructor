---
name: commit-and-push
description: Write accurate commit messages, commit only intended changes, and safely push to a verified GitHub upstream when explicitly requested.
argument-hint: "[change scope] [draft only | commit only | commit and push]"
---

# Commit messages and safe upstream pushes

Use this workflow when asked to draft a commit message, commit changes, or commit and push. Respect the requested scope: a message-only request must not modify Git state, and a commit-only request must not push. Loading this skill is not itself authorization to commit or push; require an explicit user request for each operation.

## 1. Inspect before writing

- Read applicable repository instructions, including `AGENTS.md` and contribution guidelines.
- Run these independent checks in parallel: `git status --short --branch`, `git diff`, `git diff --cached`, and `git log -10 --format='%h %s'`.
- Check `git branch --show-current`, `git branch -vv`, and `git remote -v` before planning a push. Do not expose credentials embedded in remote URLs.
- Review relevant untracked files separately; ordinary `git diff` does not include them. Do not read or stage local secrets, credentials, databases, build output, or dependency directories.
- Identify the exact files and changes the user wants included. Preserve unrelated edits and previously staged work. If the scope is ambiguous, ask rather than assuming all changes belong in the commit.
- Stop for a detached HEAD, an unfinished merge/rebase, or unresolved conflicts and ask how to proceed.

## 2. Write an accurate message

Follow documented repository conventions first, then consistent recent history. A single initial commit does not establish a meaningful style. If no convention exists, use Conventional Commits:

```text
<type>(<optional-scope>): <imperative summary>
```

Choose the type based on the actual diff:

- `feat`: new user-facing capability.
- `fix`: correction of incorrect behavior.
- `refactor`: restructuring without changing behavior.
- `perf`: performance improvement.
- `test`: test-only change.
- `docs`: documentation-only change.
- `build` or `ci`: build/dependency tooling or CI changes.
- `chore`: maintenance not covered above, including agent workflow configuration.
- `style`: formatting-only change, not visual UI behavior.

Keep the subject concise, ideally at most 72 characters, with no trailing period. Use an imperative verb such as “prevent”, “preserve”, or “add”. Describe the specific outcome, not “update files”, “fix stuff”, or a filename list. Do not invent issue numbers, test results, performance claims, or intent unsupported by the diff and user context.

For nontrivial changes, add a blank line and a body explaining why the change is needed, relevant behavior or trade-offs, and any migration requirements. Wrap prose around 72 characters. Use `!` and a `BREAKING CHANGE:` footer only for a real breaking change, describing its impact and migration. Reference issues only when known, and use closing keywords only when the change actually resolves the issue.

Examples of subjects, to use only when supported by the diff:

```text
fix(charts): prevent annualizing returns with insufficient history
feat(analysis): allow rerunning a saved portfolio configuration
chore(skills): standardize commit messages and upstream push checks
```

For commits created by Devin, include these attribution lines after the body:

```text
Generated with [Devin](https://devin.ai)

Co-Authored-By: Devin <158243242+devin-ai-integration[bot]@users.noreply.github.com>
```

## 3. Verify and commit only the intended changes

- Run verification relevant to the changed files using repository instructions and current package scripts. For skill-only changes, validate skill discovery, review the instructions, and check whitespace; an application build is unnecessary. For browser verification here, mock `/api/v1/**` to avoid creating analyses in the user's database.
- Report failed or unavailable checks accurately. Fix issues within scope; ask before committing with unresolved failures. Never bypass hooks or weaken security settings to make checks pass.
- Stage explicit paths with `git add -- <path>...`, not blanket `git add .` or `git add -A`. If intended and unrelated edits share a file, ask how to separate them; do not silently include everything or use interactive Git flags.
- If unrelated changes are already staged, stop and ask how to handle them before committing. Do not unstage, stash, discard, or overwrite the user's work on your own.
- Review `git diff --cached --check`, `git diff --cached --stat`, and the full `git diff --cached`. Verify that the index contains only the intended changes and no sensitive data.
- Do not create an empty commit. If there are no intended changes, report that; an explicitly requested push of existing commits can still proceed after review.
- Create the commit using the reviewed message and the attribution above. Use safely quoted multiline input, such as `git commit -F -` with a quoted heredoc, to prevent shell expansion in message text.
- If a hook modifies files and the commit fails, inspect its changes, rerun relevant checks, stage only intended modifications, and retry normally. Never use `--no-verify`.
- Confirm the result with `git show --stat --oneline HEAD` and `git status --short --branch`. Never change Git identity/configuration or amend a commit without an explicit request.

## 4. Push only with authorization to a verified destination

- Proceed only when the user explicitly requested a push. Verify the remote's push URL and the current branch's upstream; do not assume the destination is `origin/main` or a remote named `upstream`.
- If there is no upstream, ask for the remote and branch, or use a destination already explicitly supplied by the user. Do not create a remote or switch branches silently.
- Fetch the selected remote, then check ahead/behind state and review every outgoing commit with `git log --oneline <remote>/<branch>..HEAD`. A push publishes all outgoing commits, not just the newest one. Ask before publishing unexpected pre-existing commits.
- If the remote branch has advanced or diverged, stop and explain. Do not automatically pull, merge, rebase, reset, or force-push. Respect protected branches; if direct pushes are rejected, ask about a feature branch and pull request instead of bypassing protection.
- State the verified remote and target branch, then run a dry run using an explicit refspec: `git push --dry-run <remote> HEAD:refs/heads/<branch>`. Replace placeholders with the inspected destination; do not paste them literally.
- If the dry run succeeds, run `git push <remote> HEAD:refs/heads/<branch>`. For an approved destination without an upstream, use `git push --set-upstream <remote> HEAD:refs/heads/<branch>` instead. Never use `--force`, `--force-with-lease`, `--mirror`, or `--all` in this workflow.
- For authentication or permission failures, stop and ask the user to resolve access. Do not search for credentials, print tokens, or change authentication configuration.
- Verify the remote branch SHA with `git ls-remote <remote> refs/heads/<branch>` against `git rev-parse HEAD`, then check local status. Report races or mismatches honestly rather than claiming success.

## 5. Report the result

Summarize the commit hash and subject, verification performed, push destination and result, and any unrelated work left untouched. If blocked, distinguish completed local commits from an unsuccessful or unattempted push. Never claim checks passed or a push succeeded without evidence.
