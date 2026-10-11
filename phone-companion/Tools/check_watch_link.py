"""Compile the real watch-link source with a fake Garmin transport on macOS."""
import argparse
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--sdk-headers', required=True, type=Path,
                    help='Headers folder inside the official ConnectIQ.xcframework')
args = parser.parse_args()
headers = args.sdk_headers.resolve()
if not (headers / 'ConnectIQ.h').is_file():
    parser.error('ConnectIQ.h was not found in --sdk-headers')
root = Path(__file__).resolve().parents[2]
link = root / 'DrowsyApp/DrowsyAlert/ios-companion'
with tempfile.TemporaryDirectory(prefix='drowsy-watch-checks-') as work:
    work = Path(work)
    (work / 'ConnectIQ').symlink_to(headers, target_is_directory=True)
    executable = work / 'checks'
    subprocess.run([
        'xcrun', 'clang', '-fobjc-arc', '-fblocks',
        '-Wno-incomplete-implementation', '-Wno-objc-property-implementation',
        '-framework', 'Foundation', '-framework', 'CoreBluetooth',
        '-I', str(work), '-I', str(link),
        str(root / 'phone-companion/Tests/watch_link_checks.m'),
        str(link / 'DrowsyWatchLink.m'), '-o', str(executable),
    ], check=True)
    subprocess.run([str(executable)], check=True)
