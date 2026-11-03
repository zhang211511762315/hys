"""Wait for accepted HTTP connections using socket metadata only (run as root)."""
import json
from pathlib import Path
import subprocess
import sys
import time

name = sys.argv[1]
port = int(sys.argv[2])
assert name in {'hys-release-web', 'wewe-rss', 'mobile-rp-sillytavern'}
deadline = time.monotonic() + 300
zeros = 0
while True:
    pid = int(subprocess.check_output(['docker', 'inspect', '--format', '{{.State.Pid}}', name]))
    if pid <= 0:
        raise RuntimeError('application is not running; do not force replacement')
    count = 0
    for protocol in ['tcp', 'tcp6']:
        for line in Path(f'/proc/{pid}/net/{protocol}').read_text().splitlines()[1:]:
            fields = line.split()
            if int(fields[1].rsplit(':', 1)[1], 16) == port and fields[3] not in {'0A', '06', '07'}:
                count += 1
    zeros = zeros + 1 if count == 0 else 0
    if zeros >= 3:
        print(json.dumps({'container':name,'accepted_connections':count,'idle_samples':zeros}))
        break
    if time.monotonic() >= deadline:
        raise RuntimeError('accepted connections remain; do not force termination')
    time.sleep(2)
