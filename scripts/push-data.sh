#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DEFAULT_BRANCH:-}" || "${GITHUB_REF:-}" != "refs/heads/$DEFAULT_BRANCH" ]]; then
    echo "::error::Scraped data and request reservations must use the repository's default branch."
    exit 1
fi

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
base=$(git rev-parse HEAD)
git add -- data/
if git diff --cached --quiet -- data/; then
    echo "No product data or checkpoint changes."
    exit 0
fi
message=${1:-"chore: update product data [$(date +'%Y-%m-%d')]"}
git commit -m "$message" --only -- data/

# Replay only this step's data commit. An explicit old base avoids
# merge-base discovery and downloading history in a shallow clone.
for attempt in 1 2 3; do
    git fetch --no-tags --depth=1 origin "$GITHUB_REF"
    remote_tip=$(git rev-parse FETCH_HEAD)
    if [[ "$base" != "$remote_tip" ]]; then
        # Budget accounting must not be text-merged from a stale snapshot.
        # An identical remote ledger is safe for an already-accepted push retry.
        if ! git diff --quiet "$base" "$remote_tip" -- data/request_budget.json &&
            ! git diff --quiet HEAD "$remote_tip" -- data/request_budget.json; then
            echo "::error::Request budget changed upstream; refusing to merge stale reservation accounting."
            exit 1
        fi
        if ! git rebase --onto "$remote_tip" "$base"; then
            git rebase --abort
            echo "::error::Data conflicts with a newer branch update; refusing to overwrite it."
            exit 1
        fi
    fi
    base=$remote_tip
    # Update only the checked default branch, never force-push.
    if git push origin "HEAD:$GITHUB_REF"; then
        exit 0
    fi
    echo "Push attempt $attempt failed; refreshing the branch before retrying."
done
echo "::error::Could not push product data and checkpoints after three attempts."
exit 1
