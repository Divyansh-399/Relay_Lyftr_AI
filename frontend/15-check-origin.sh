#!/bin/sh
set -eu
# Only interpolate a plain, single-line HTTP origin into the Nginx template.
case "$API_BASE_URL" in
    *[!A-Za-z0-9.:/-]*) echo "Invalid API_BASE_URL" >&2; exit 1 ;;
esac
printf '%s\n' "$API_BASE_URL" | grep -Eq '^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?$' || {
    echo "API_BASE_URL must be an HTTP origin without a trailing slash" >&2
    exit 1
}
