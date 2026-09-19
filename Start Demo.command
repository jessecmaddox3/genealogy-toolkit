#!/bin/sh
cd "$(dirname "$0")" || exit 1
for demo_python in python3 python; do
  if command -v "$demo_python" >/dev/null 2>&1 && "$demo_python" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
    "$demo_python" start_demo.py "$@"
    demo_status=$?
    if [ "$demo_status" -ne 0 ]; then printf '\nPress Return to close.'; read -r demo_reply; fi
    exit "$demo_status"
  fi
done
printf 'Install Python 3.12 or newer from https://www.python.org/downloads/, then try again.\nPress Return to close.'
read -r demo_reply
exit 2
