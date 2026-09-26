#!/usr/bin/env bash
#
# Print release notes for a ref to stdout: one Markdown bullet per non-merge
# commit since the previous vX.Y.Z tag (the bot's own changelog commits dropped).
#
# This is the SINGLE source of truth for "what changed" — kept byte-identical in
# cinefin and cinefin-playout, and called by every release workflow (GitHub and
# Gitea) so the notes can't drift between forges. Callers add their own headings
# and any project-specific sections (e.g. a Binaries blurb).
#
# Usage: scripts/changelog.sh <ref> [max]
#   <ref>  a release tag -> notes since the numerically-previous vX.Y.Z tag; OR
#          a branch / HEAD (the rolling "edge" notes) -> notes since the LATEST
#          vX.Y.Z tag, i.e. everything not yet in a stable release.
#   [max]  cap the list to the newest <max> bullets, appending "- …and N more"
#          (0 or omitted = uncapped; stable releases pass nothing, edge caps).
# Needs full history + tags — check out with fetch-depth: 0.
set -euo pipefail

REF="${1:?usage: changelog.sh <ref> [max]}"
MAX="${2:-0}"

# The base to diff against: if REF is itself a release tag, the tag numerically
# before it; otherwise (a branch / HEAD for the edge notes) the latest tag.
if git tag --list 'v*' | grep -Fxq "${REF}"; then
    PREV="$(git tag --list 'v*' --sort=-version:refname \
              | awk -v cur="${REF}" 'found { print; exit } $0 == cur { found = 1 }')"
else
    PREV="$(git tag --list 'v*' --sort=-version:refname | head -n1)"
fi
if [ -n "${PREV}" ]; then RANGE="${PREV}..${REF}"; else RANGE="${REF}"; fi

# One bullet per non-merge commit; drop the CHANGELOG bot's own commits so they
# never show up as "changes".
mapfile -t LINES < <(git log --no-merges --invert-grep --grep='^Update CHANGELOG for ' \
                       --pretty='format:- %s (%h)' "${RANGE}")

if [ "${#LINES[@]}" -eq 0 ]; then
    printf -- '- No code changes.\n'
elif [ "${MAX}" -gt 0 ] && [ "${#LINES[@]}" -gt "${MAX}" ]; then
    printf '%s\n' "${LINES[@]:0:MAX}"
    printf -- '- …and %d more\n' "$((${#LINES[@]} - MAX))"
else
    printf '%s\n' "${LINES[@]}"
fi
