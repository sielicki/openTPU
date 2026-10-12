"""Opt-in kernel limit checks; these intentionally launch tiny competing scopes."""
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(os.environ.get('OTPU_TEST_RESOURCE_LIMITS') != '1',
                               reason='requires local systemd and noninteractive sudo')
RUNNER = [sys.executable, str(Path(__file__).resolve().parents[1] /
                            'tools/sparkle_bounded.py'), '--memory-mib', '64', '--']


def run(*command):
    return subprocess.run(RUNNER + list(command), capture_output=True, text=True, timeout=15)


def test_descendants_inherit_limits():
    child = ('from pathlib import Path; import json; '
             'p=Path("/sys/fs/cgroup") / Path("/proc/self/cgroup").read_text().strip().split("::",1)[1].lstrip("/"); '
             'assert (p/"memory.max").read_text().strip()=="67108864"; '
             'assert (p/"memory.swap.max").read_text().strip()=="0"; '
             'assert Path("/proc/self/oom_score_adj").read_text().strip()=="1000"; print("child bounded")')
    result = run(sys.executable, '-c',
                 'import subprocess,sys; subprocess.run([sys.executable,"-c",sys.argv[1]],check=True)', child)
    assert result.returncode == 0, result.stderr
    assert 'child bounded' in result.stdout


def test_concurrent_job_rejected(tmp_path):
    marker = tmp_path / 'ready'
    command = 'from pathlib import Path; import sys,time; Path(sys.argv[1]).touch(); time.sleep(3)'
    first = subprocess.Popen(RUNNER + [sys.executable, '-c', command, str(marker)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and first.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert marker.exists(), 'first bounded job did not start'
        second = run('true')
        assert second.returncode == 75, second.stderr
        _, error = first.communicate(timeout=10)
        assert first.returncode == 0, error
    finally:
        if first.poll() is None:
            first.terminate()
            first.wait(timeout=10)


def test_over_limit_job_killed_and_next_job_recovers():
    result = run(sys.executable, '-c', 'x=bytearray(128*1024*1024); print("unexpected allocation")')
    assert result.returncode == 137, result.stderr
    assert 'unexpected allocation' not in result.stdout
    result = run('true')
    assert result.returncode == 0, result.stderr


def test_limit_cannot_be_raised():
    result = subprocess.run(RUNNER[:-1] + ['--memory-mib', '4096', '--', 'true'],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 2


def test_optimized_python_cannot_bypass_scope_check():
    result = subprocess.run([sys.executable, '-O', RUNNER[1], '--inside',
                             '--uid', str(os.getuid()), '--memory-mib', '64', '--',
                             sys.executable, '-c', 'print("unbounded launch")'],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode != 0
    assert 'outside bounded job scope' in result.stderr
    assert 'unbounded launch' not in result.stdout


def test_sigterm_cleans_up_descendants(tmp_path):
    marker = tmp_path / 'ready'
    command = ('import subprocess,sys,time; from pathlib import Path; '
               'subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
               'Path(sys.argv[1]).touch(); time.sleep(60)')
    first = subprocess.Popen(RUNNER + [sys.executable, '-c', command, str(marker)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and first.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert marker.exists(), 'first bounded job did not start'
        first.terminate()
        _, error = first.communicate(timeout=10)
        assert first.returncode == 143, error
        result = run('true')
        assert result.returncode == 0, result.stderr
    finally:
        if first.poll() is None:
            first.terminate()
            first.wait(timeout=10)


def test_crashed_launcher_does_not_allow_or_kill_another_job(tmp_path):
    marker = tmp_path / 'ready'
    command = 'from pathlib import Path; import sys,time; Path(sys.argv[1]).touch(); time.sleep(30)'
    unit = f'opentpu-heavy-{os.getuid()}.scope'
    first = subprocess.Popen(RUNNER + [sys.executable, '-c', command, str(marker)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and first.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert marker.exists(), 'first bounded job did not start'
        first.kill()
        first.wait(timeout=5)
        second = run('true')
        assert second.returncode == 75, second.stderr
        state = subprocess.run(['systemctl', 'is-active', '--quiet', unit])
        assert state.returncode == 0, 'second launcher stopped the surviving first job'
    finally:
        subprocess.run(['sudo', '-n', 'systemctl', 'stop', unit],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        if first.poll() is None:
            first.terminate()
        first.communicate(timeout=10)
    result = run('true')
    assert result.returncode == 0, result.stderr
