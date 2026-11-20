#!/usr/bin/env bash
set -euo pipefail

git_dir="$(git -C "$(dirname -- "${BASH_SOURCE[0]}")" rev-parse --path-format=absolute --git-common-dir)"
root="${git_dir%/.git}"
env_file="${DEHPS_NEXT_ARK_ENV_FILE:-$root/.env}"
image="${DEHPS_NEXT_ARK_IMAGE:-dehps-next:ark-cache}"

exec docker run --rm --init --pull never --network dehps-next-p0p1 \
  --env-file "$env_file" --env PYTHONUNBUFFERED=1 --env OMP_NUM_THREADS=1 --env OPENBLAS_NUM_THREADS=1 --env MKL_NUM_THREADS=1 \
  --cgroup-parent dehpsnext.slice --cpuset-cpus 0-19 --cpus 2 --memory 768m \
  --pids-limit 64 --read-only --tmpfs /tmp:size=64m --cap-drop ALL \
  --security-opt no-new-privileges --entrypoint dehps-next "$image" ark-cache "$@"
