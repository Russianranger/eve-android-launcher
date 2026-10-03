import pathlib
import shutil
import subprocess
import tempfile
import unittest


class ClientNetworkPolicyTests(unittest.TestCase):
    def test_compiled_destination_policy(self):
        compiler = shutil.which('cc')
        if not compiler:
            self.skipTest('C compiler unavailable')
        root = pathlib.Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as temporary:
            binary = pathlib.Path(temporary) / 'client-network-policy'
            subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                            str(root / 'tests/client-network-policy.c'), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, capture_output=True, text=True)

    def test_compiled_tracee_callback(self):
        compiler = shutil.which('cc')
        if not compiler:
            self.skipTest('C compiler unavailable')
        root = pathlib.Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as temporary:
            include = pathlib.Path(temporary) / 'include'
            for relative in ('extension/extension.h', 'tracee/tracee.h',
                             'tracee/abi.h', 'tracee/mem.h', 'syscall/sysnum.h'):
                header = include / relative
                header.parent.mkdir(parents=True, exist_ok=True)
                header.write_text('/* API supplied by proot-network-fixture.h */\n')
            binary = pathlib.Path(temporary) / 'client-network-callback'
            subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-I', str(include), str(root / 'tests/client-network-callback.c'),
                            '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, capture_output=True, text=True)
