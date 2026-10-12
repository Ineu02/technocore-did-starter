#!/bin/bash
# Kibble RESULT sniper — runs the watch loop against the live room tail.
#
# Why: the v2 score formula multiplies job posts (x2) and attests (x1) by zero
# until the account has >=3 own results. The farm sat at score 1 for weeks
# because nothing ever delivered a result. This wrapper keeps the gate open.
#
# Cron contract: SILENT on a normal run. kibble_results.py prints nothing
# unless it actually delivered something.
cd /root/technocore-did-starter || exit 1
export POLL_SECONDS="${POLL_SECONDS:-300}"
exec /usr/bin/python3 kibble_results.py --watch
