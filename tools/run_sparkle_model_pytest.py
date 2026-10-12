"""Run model tests with CPU intra/inter-op threads pinned; parent authenticates dependencies."""
import sys


def main():
    import torch
    if torch.version.cuda is not None:
        raise RuntimeError('Model qualification requires CPU-only Torch')
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    print(f'MODEL_RUNTIME torch={torch.__version__} cuda={torch.version.cuda} '
          f'intra_threads={torch.get_num_threads()} inter_threads={torch.get_num_interop_threads()}',
          flush=True)
    import pytest
    return pytest.main(sys.argv[1:])


if __name__ == '__main__':
    raise SystemExit(main())
