# A test file emptied during an import tidy-up (2026-11-18)

## Summary

During the MCP client build, an AI coding agent asked to "sort imports" in a test file
emptied it (`backend/tests/cli/test_inspect_mcp.py`). The change was committed with the
tests gone and the suite still green. It was caught during review of that build, and the
file was restored from git history in `f2d316d`. In the same build a different agent wrote a commit trailer naming
the wrong model, which was fixed by amending.

## What happened

- The agent replaced the file's contents instead of editing only the import block.
- Deleting tests can't make a suite fail: fewer tests still pass. "All tests pass" was
  true and meaningless.

## Why every safety net missed it

- **Tests:** a removed test can't fail.
- **Review:** nothing in the review routine treated a large deletion in a test file as
  a finding in itself.
- **CI:** none runs on this repo, by choice.
- **Commit trailer:** nothing checked the message. The agent followed its harness
  default over the project's rule.

## The guard that now catches it

- The pre-commit hook (`.githooks/pre-commit`, `scripts/githooks/checks.py`) refuses a
  staged change that lowers a test file's test count, deletes a test file, or shrinks
  it below half its size, unless `ZYGOS_ALLOW_TEST_SHRINK=1` is set. The commit-msg hook
  refuses a Claude co-author trailer other than the project's exact one. Both were shown
  to reject the bad case in a throwaway repository before being enabled.
- Review rule (CLAUDE.md, "Zygos working rules"): check the result, not the report; read
  `git diff --stat` and treat any test file that loses tests as a finding.
