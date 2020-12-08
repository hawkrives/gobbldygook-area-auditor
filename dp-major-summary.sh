#!/bin/bash

set -e -o pipefail

CODE="$1"

cargo build --bin dp-major-summary
time ./target/debug/dp-major-summary ./testbed_db.db "$CODE" --as-html > "summary-${CODE}.html"
scp "summary-${CODE}.html" "ola:/home/www/sis/dp-report/summary-${CODE}.html"