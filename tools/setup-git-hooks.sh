#!/bin/sh
# Run explicitly in each clone. Never change the user's global Git settings.
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(git -C "$script_dir" rev-parse --show-toplevel)
current_hooks=$(git -C "$repo_root" config --get core.hooksPath || true)

if [ -n "$current_hooks" ] && [ "$current_hooks" != '.githooks' ]; then
    printf '%s\n' '기존 core.hooksPath가 있어 덮어쓰지 않았습니다. 기존 hook과 통합 후 설정하세요.' >&2
    exit 1
fi

default_hooks_dir=$(git -C "$repo_root" rev-parse --git-path hooks)
case "$default_hooks_dir" in
    /*) ;;
    *) default_hooks_dir="$repo_root/$default_hooks_dir" ;;
esac
if [ -z "$current_hooks" ]; then
    for existing_hook in "$default_hooks_dir"/*; do
        [ -f "$existing_hook" ] || continue
        case "$existing_hook" in
            *.sample) continue ;;
        esac
        if [ -x "$existing_hook" ]; then
            printf '%s\n' '기존 .git/hooks의 활성 hook이 있어 설정하지 않았습니다. 기존 hook과 통합하세요.' >&2
            exit 1
        fi
    done
fi

chmod +x "$repo_root/.githooks/pre-push"
git -C "$repo_root" config --local core.hooksPath .githooks
printf '%s\n' '이 clone의 main 직접 push 차단 hook을 활성화했습니다.'
