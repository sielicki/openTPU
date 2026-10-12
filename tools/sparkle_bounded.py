"""Run one local heavy job at a time, with kernel-enforced process-tree limits.

Requires noninteractive sudo for systemd-run/setpriv. Fails closed if the cgroup
limits cannot be verified. Commands execute as the calling user, never as root.
This noninteractive runner reserves stdin for its environment hand-off.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

MAX_MIB = 3072
TASKS = 64
BUSY = 75


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def cgroup():
    entry = next(line for line in Path('/proc/self/cgroup').read_text().splitlines()
                 if line.startswith('0::'))
    relative = entry.split('::', 1)[1].lstrip('/')
    require(Path(relative).name.startswith('opentpu-heavy-'), 'outside bounded job scope')
    return Path('/sys/fs/cgroup') / relative


def bounded_environment(inherited):
    return dict(inherited, OTPU_VERILATOR_JOBS='1', LEAN_NUM_THREADS='1',
                OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MAKEFLAGS='-j1',
                OTPU_BUILD_JOBS='1', OTPU_COMPILE_AHEAD='1')


def inside(args):
    require(os.getuid() == args.uid != 0, 'job must run as the requesting non-root user')
    group = cgroup()
    limits = {key: (group / key).read_text().strip() for key in
              ('memory.max', 'memory.swap.max', 'memory.oom.group', 'pids.max', 'cpu.max')}
    require(int(limits['memory.max']) == args.memory_mib * 1024**2, 'RAM cap differs')
    require(limits['memory.swap.max'] == '0', 'swap must be disabled')
    require(limits['memory.oom.group'] == '1', 'OOM must terminate the whole job')
    require(int(limits['pids.max']) == TASKS, 'task cap differs')
    quota, period = map(int, limits['cpu.max'].split())
    require(quota == 2 * period, 'CPU quota must be two CPUs')
    # If unrelated host demand causes global pressure below our own ceiling,
    # prefer killing this job rather than the user's other applications.
    Path('/proc/self/oom_score_adj').write_text('1000')
    require(Path('/proc/self/oom_score_adj').read_text().strip() == '1000', 'OOM priority differs')
    print('BOUNDED ' + json.dumps({'cgroup': str(group), 'limits': limits}),
          file=sys.stderr, flush=True)
    # Restore the caller's environment only after dropping privileges. Sending
    # it through stdin avoids privileged environment handling, argv exposure,
    # and persistent files containing environment credentials.
    env = bounded_environment(json.loads(sys.stdin.buffer.readline()))
    start = time.monotonic()
    result = subprocess.run(args.command, env=env)
    print('BOUNDED_RESULT ' + json.dumps({
        'exit_code': result.returncode, 'elapsed_seconds': time.monotonic() - start,
        'memory_peak': int((group / 'memory.peak').read_text()),
        'memory_events': (group / 'memory.events').read_text().splitlines(),
    }), file=sys.stderr, flush=True)
    return result.returncode if result.returncode >= 0 else 128 - result.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--memory-mib', type=int, default=MAX_MIB)
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--uid', type=int, help=argparse.SUPPRESS)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command[:1] == ['--']:
        args.command = args.command[1:]
    if not args.command or not 32 <= args.memory_mib <= MAX_MIB:
        parser.error(f'provide a command and a memory limit between 32 and {MAX_MIB} MiB')
    if args.inside:
        return inside(args)
    if os.getuid() == 0:
        parser.error('invoke as the ordinary workspace user')
    lock_path = Path('/tmp') / f'opentpu-heavy-{os.getuid()}.lock'
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another bounded openTPU job is running; no work launched.', file=sys.stderr)
            return BUSY
        # A fixed unit name also prevents overlap if the lock-holder crashes
        # while a descendant survives. systemd rejects an already active unit.
        unit = f'opentpu-heavy-{os.getuid()}'
        def property_value(name):
            return subprocess.run(['systemctl', 'show', '--value', '-p', name, unit + '.scope'],
                                  capture_output=True, text=True).stdout.strip()
        if property_value('ActiveState') in ('active', 'activating', 'deactivating', 'reloading'):
            print('A previous bounded scope is still active; no work launched.', file=sys.stderr)
            return BUSY
        owner = f'openTPU bounded job {os.getpid()} {time.time_ns()}'
        command = ['sudo', '-n', 'systemd-run', '--scope', '--quiet',
                   '--collect', '--unit=' + unit,
                   '--property=Description=' + owner,
                   f'--property=MemoryMax={args.memory_mib}M',
                   '--property=MemorySwapMax=0', '--property=OOMPolicy=kill',
                   f'--property=TasksMax={TASKS}', '--property=CPUQuota=200%',
                   'setpriv', f'--reuid={os.getuid()}', f'--regid={os.getgid()}',
                   '--init-groups', '--no-new-privs', sys.executable,
                   str(Path(__file__).resolve()), '--inside', '--uid', str(os.getuid()),
                   '--memory-mib', str(args.memory_mib), '--', *args.command]
        received_signal = signal.SIGINT
        def interrupted(number, _frame):
            nonlocal received_signal
            received_signal = number
            raise KeyboardInterrupt
        previous = {number: signal.signal(number, interrupted)
                    for number in (signal.SIGTERM, signal.SIGINT)}
        try:
            result = subprocess.run(command, input=json.dumps(dict(os.environ)) + '\n', text=True).returncode
            result = result if result >= 0 else 128 - result
            print('BOUNDED_EXIT ' + json.dumps({'exit_code': result,
                  'status': 'killed' if result == 137 else 'passed' if result == 0 else 'failed'}),
                  file=sys.stderr, flush=True)
            return result
        except KeyboardInterrupt:
            return 128 + received_signal
        finally:
            # Stop any surviving descendants before releasing the shared lock.
            # A completed --collect scope may already have disappeared.
            if property_value('Description') == owner:
                subprocess.run(['sudo', '-n', 'systemctl', 'stop', unit + '.scope'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for number, handler in previous.items():
                signal.signal(number, handler)


if __name__ == '__main__':
    raise SystemExit(main())
