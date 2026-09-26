#!/usr/bin/env bash
#
# Print release notes for a tag to stdout: one Markdown bullet per non-merge
# commit since the previous vX.Y.Z tag (the bot's own changelog commits dropped).
#
# This is the SINGLE source of truth for "what changed" — kept byte-identical in
# cinefin and cinefin-playout, and called by every release workflow (GitHub and
# Gitea) so the notes can't drift between forges. Callers add their own headings
# and any project-specific sections (e.g. a Binaries blurb).
#
# Usage: scripts/changelog.sh <tag>          # e.g. scripts/changelog.sh v0.2.0
# Needs full history + tags — check out with fetch-depth: 0.
set -euo pipefail

REF="${1:?usage: changelog.sh <tag>}"

# The numerically-previous vX.Y.Z tag (empty for the very first release): walk the
# version-sorted tag list and take the entry right after the current one.
PREV="$(git tag --list 'v*' --sort=-version:refname \
          | awk -v cur="${REF}" 'found { print; exit } $0 == cur { found = 1 }')"
if [ -n "${PREV}" ]; then RANGE="${PREV}..${REF}"; else RANGE="${REF}"; fi

# One bullet per non-merge commit; drop the CHANGELOG bot's own commits so they
# never show up as "changes".
NOTES="$(git log --no-merges --invert-grep --grep='^Update CHANGELOG for ' \
           --pretty='format:- %s (%h)' "${RANGE}")"
[ -n "${NOTES}" ] || NOTES="- No code changes."
printf '%s\n' "${NOTES}"
