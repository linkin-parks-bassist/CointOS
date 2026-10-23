"""Publication on real Git, including process death and messy editor workspaces."""
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from cointos import git
from tests import support


def files(root):
    return {str(p.relative_to(root)): (p.lstat().st_mode, os.readlink(p) if p.is_symlink() else p.read_bytes())
            for p in root.rglob('*') if '.git' not in p.relative_to(root).parts
            and (p.is_file() or p.is_symlink())}


class Publication(unittest.TestCase):
    def setup_repo(self):
        repo = support.repository(self)
        (repo / 'code.txt').write_text('old\n')
        base = support.commit(repo)
        git.run(repo, 'switch', '-q', '-c', 'candidate')
        (repo / 'code.txt').write_text('new\n')
        (repo / 'collision.txt').write_text('accepted\n')
        candidate = support.commit(repo)
        git.run(repo, 'switch', '-q', 'main')
        return repo, base, candidate

    def test_clean_checkout_refreshes(self):
        repo, base, candidate = self.setup_repo()
        with git.repository_lock(repo):
            git.publish(repo, 'main', candidate, base)
        self.assertEqual(git.head(repo), candidate)
        self.assertTrue(git.clean(repo))

    def test_mechanical_git_ignores_blocking_hooks_without_changing_editor_config(self):
        repo, base, candidate = self.setup_repo()
        hooks = repo / '.git/hooks'
        marker = repo / '.git/hook-running'
        script = ('#!/usr/bin/env python3\nimport signal\nfrom pathlib import Path\n'
                  f'Path({str(marker)!r}).write_text("editor hook ran")\nsignal.pause()\n')
        for name in ('post-checkout', 'pre-commit', 'post-commit', 'reference-transaction'):
            path = hooks / name
            path.write_text(script)
            path.chmod(0o755)
        global_config = repo.parent / 'editor.gitconfig'
        global_config.write_text(f'[core]\n\thooksPath = {hooks}\n')
        env = {**os.environ, 'GIT_CONFIG_GLOBAL': str(global_config)}
        local_before = (repo / '.git/config').read_bytes()
        global_before = global_config.read_bytes()
        code = '''import sys
from pathlib import Path
from cointos import git
repo,base=sys.argv[1:]
git.run(repo,"worktree","add","--detach",str(Path(repo).parent/"check"),base)
git.run(repo,"switch","-q","candidate")
(Path(repo)/"mechanical.txt").write_text("mechanical edit")
git.run(repo,"add","mechanical.txt")
git.run(repo,"commit","-qm","mechanical commit")
git.run(repo,"update-ref","refs/heads/mechanical",git.head(repo))
'''
        child = subprocess.Popen([sys.executable, '-c', code, str(repo), base], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            output = child.communicate(timeout=5)
            self.assertEqual(child.returncode, 0, output)
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.communicate(timeout=5)
        self.assertFalse(marker.exists(), 'CointOS mechanical operations must not execute the hooks')
        self.assertEqual(git.head(repo, 'mechanical'), git.head(repo))
        editor = subprocess.Popen(['git', '-C', str(repo), 'switch', '-q', 'main'], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            deadline = time.monotonic() + 5
            while not marker.exists() and editor.poll() is None and time.monotonic() < deadline:
                time.sleep(.005)
            self.assertTrue(marker.exists(), 'ordinary editor Git must still execute its configured hook')
            self.assertIsNone(editor.poll())
            self.assertEqual(marker.read_text(), 'editor hook ran')
        finally:
            if editor.poll() is None:
                os.killpg(editor.pid, signal.SIGKILL)
            editor.communicate(timeout=5)
        self.assertEqual((repo / '.git/config').read_bytes(), local_before)
        self.assertEqual(global_config.read_bytes(), global_before)

    def test_seeded_dirty_checkouts_preserve_files_modes_and_index(self):
        rng = random.Random(8173)
        for seed in range(32):
            with self.subTest(seed=seed):
                repo, base, candidate = self.setup_repo()
                (repo / 'code.txt').write_bytes(rng.randbytes(80))
                if seed % 2:
                    git.run(repo, 'add', 'code.txt')
                    (repo / 'code.txt').write_bytes(rng.randbytes(60))
                (repo / 'collision.txt').write_bytes(b'local\0' + rng.randbytes(20))
                (repo / 'space ü.txt').write_text('local')
                (repo / 'link').symlink_to('code.txt')
                (repo / 'code.txt').chmod(0o755)
                before, index = files(repo), git.run(repo, 'write-tree')
                with git.repository_lock(repo):
                    result = git.publish(repo, 'main', candidate, base)
                self.assertTrue(result['draft'].startswith('work/draft-'))
                self.assertEqual(git.head(repo), base)
                self.assertEqual(git.head(repo, 'main'), candidate)
                self.assertEqual(files(repo), before)
                # Git may refresh stat-cache bytes; the staged tree is the authority.
                self.assertEqual(git.run(repo, 'write-tree'), index)
                self.assertEqual(git.publish(repo, 'main', candidate, candidate), {'commit': candidate})

    def test_switched_checkout_is_independent(self):
        repo, base, candidate = self.setup_repo()
        git.run(repo, 'switch', '-q', '-c', 'editor')
        (repo / 'code.txt').write_text('local')
        before = files(repo)
        git.publish(repo, 'main', candidate, base)
        self.assertEqual(git.head(repo), base)
        self.assertEqual(files(repo), before)
        self.assertEqual(git.head(repo, 'main'), candidate)

    def test_editor_commit_cannot_race_dirty_head_handoff(self):
        repo, base, candidate = self.setup_repo()
        (repo / 'code.txt').write_text('editor staged work\n')
        git.run(repo, 'add', 'code.txt')
        before, index = files(repo), git.run(repo, 'write-tree')
        replace = os.replace
        attempts = []
        def handoff(source, target):
            attempts.append(git.result(repo, 'commit', '-qm', 'editor racing handoff'))
            self.assertEqual(git.head(repo), base)
            self.assertEqual(git.run(repo, 'branch', '--show-current'), 'main')
            self.assertEqual(files(repo), before)
            self.assertEqual(git.run(repo, 'write-tree'), index)
            replace(source, target)
        with patch.object(git.os, 'replace', side_effect=handoff):
            publication = git.publish(repo, 'main', candidate, base)
        self.assertEqual(len(attempts), 1)
        self.assertNotEqual(attempts[0].returncode, 0)
        self.assertIn('HEAD.lock', attempts[0].stderr)
        self.assertEqual(git.head(repo), base)
        self.assertEqual(git.head(repo, 'main'), candidate)
        self.assertEqual(files(repo), before)
        self.assertEqual(git.run(repo, 'write-tree'), index)
        self.assertFalse((repo / '.git/HEAD.lock').exists())
        committed = support.commit(repo, 'editor after handoff')
        self.assertEqual(git.head(repo, publication['draft']), committed)
        self.assertEqual(git.head(repo, 'main'), candidate)

    def test_editor_commit_before_head_lock_refuses_without_changing_identity(self):
        repo, base, candidate = self.setup_repo()
        (repo / 'code.txt').write_text('editor staged work\n')
        git.run(repo, 'add', 'code.txt')
        link = os.link
        committed = []
        def linked(source, target):
            committed.append(support.commit(repo, 'editor before handoff lock'))
            return link(source, target)
        with patch.object(git.os, 'link', side_effect=linked):
            with self.assertRaisesRegex(ValueError, 'workspace changed'):
                git.publish(repo, 'main', candidate, base)
        self.assertEqual(len(committed), 1)
        self.assertEqual(git.head(repo), committed[0])
        self.assertEqual(git.head(repo, 'main'), committed[0])
        self.assertEqual(git.run(repo, 'branch', '--show-current'), 'main')
        self.assertEqual((repo / 'code.txt').read_text(), 'editor staged work\n')
        self.assertTrue(git.clean(repo))
        self.assertFalse((repo / '.git/HEAD.lock').exists())

    def test_existing_head_lock_is_not_removed_on_refusal(self):
        repo, base, candidate = self.setup_repo()
        (repo / 'code.txt').write_text('local\n')
        lock = repo / '.git/HEAD.lock'
        lock.write_bytes(b'editor owns this lock')
        before = files(repo)
        with self.assertRaisesRegex(ValueError, 'HEAD is locked'):
            git.publish(repo, 'main', candidate, base)
        self.assertEqual(lock.read_bytes(), b'editor owns this lock')
        self.assertEqual(git.head(repo), base)
        self.assertEqual(git.run(repo, 'branch', '--show-current'), 'main')
        self.assertEqual(files(repo), before)

    def test_handoff_cleanup_does_not_remove_next_writers_lock(self):
        repo, base, candidate = self.setup_repo()
        (repo / 'code.txt').write_text('local\n')
        replace = os.replace
        def handed_off(source, target):
            replace(source, target)
            Path(source).write_bytes(b'next Git operation')
        with patch.object(git.os, 'replace', side_effect=handed_off):
            publication = git.publish(repo, 'main', candidate, base)
        self.assertEqual((repo / '.git/HEAD.lock').read_bytes(), b'next Git operation')
        self.assertEqual(git.run(repo, 'branch', '--show-current'), publication['draft'])

    def test_failed_head_replacement_cleans_its_lock_and_preserves_workspace(self):
        repo, base, candidate = self.setup_repo()
        (repo / 'code.txt').write_text('local staged\n')
        git.run(repo, 'add', 'code.txt')
        before, index = files(repo), git.run(repo, 'write-tree')
        with patch.object(git.os, 'replace', side_effect=OSError('fixture failed replacement')):
            with self.assertRaisesRegex(OSError, 'failed replacement'):
                git.publish(repo, 'main', candidate, base)
        self.assertEqual(git.head(repo), base)
        self.assertEqual(git.run(repo, 'branch', '--show-current'), 'main')
        self.assertEqual(files(repo), before)
        self.assertEqual(git.run(repo, 'write-tree'), index)
        self.assertFalse((repo / '.git/HEAD.lock').exists())

    def kill_handoff(self, repo, base, candidate, phase):
        code = '''import signal,sys
from cointos import git
link,replace=git.os.link,git.os.replace
phase=sys.argv[4]
def stop():
    print("OWNED",flush=True)
    signal.pause()
def linked(source,target):
    if phase=="before-link":stop()
    link(source,target)
    if phase=="after-link":stop()
def replaced(source,target):
    if phase=="before-replace":stop()
    replace(source,target)
    if phase=="after-replace":stop()
git.os.link,git.os.replace=linked,replaced
with git.repository_lock(sys.argv[1]):
    git.publish(sys.argv[1],"main",sys.argv[2],sys.argv[3])
'''
        child = subprocess.Popen([sys.executable, '-c', code, str(repo), candidate, base, phase],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'OWNED')
            child.kill()
            child.communicate(timeout=5)
            self.assertEqual(child.returncode, -signal.SIGKILL)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=5)

    def test_killed_handoff_recovers_every_owned_lock_window(self):
        for phase in ('before-link', 'after-link', 'before-replace', 'after-replace'):
            with self.subTest(phase=phase):
                repo, base, candidate = self.setup_repo()
                (repo / 'code.txt').write_text('editor staged\n')
                git.run(repo, 'add', 'code.txt')
                before, index = files(repo), git.run(repo, 'write-tree')
                self.kill_handoff(repo, base, candidate, phase)
                self.assertTrue((repo / '.git/HEAD.cointos-publication').exists())
                if phase in ('after-link', 'before-replace'):
                    self.assertNotEqual(git.result(repo, 'commit', '-qm', 'blocked editor').returncode, 0)
                with git.repository_lock(repo):
                    git.publish(repo, 'main', candidate, base)
                self.assertEqual(git.head(repo), base)
                self.assertEqual(git.head(repo, 'main'), candidate)
                self.assertEqual(files(repo), before)
                self.assertEqual(git.run(repo, 'write-tree'), index)
                self.assertFalse((repo / '.git/HEAD.lock').exists())
                self.assertFalse((repo / '.git/HEAD.cointos-publication').exists())
                self.assertEqual(git.result(repo, 'commit', '-qm', 'editor resumes after recovery').returncode, 0)

    def test_killed_owned_lock_recovers_before_clean_checkout_publication(self):
        repo, base, candidate = self.setup_repo()
        (repo / 'code.txt').write_text('editor work\n')
        self.kill_handoff(repo, base, candidate, 'after-link')
        # Index/file operations can make the checkout clean without acquiring
        # HEAD.lock. Recovery must happen before choosing that clean path.
        git.run(repo, 'read-tree', base)
        (repo / 'code.txt').write_text('old\n')
        self.assertTrue(git.clean(repo))
        with git.repository_lock(repo):
            git.publish(repo, 'main', candidate, base)
        self.assertEqual(git.head(repo), candidate)
        self.assertTrue(git.clean(repo))
        self.assertFalse((repo / '.git/HEAD.cointos-publication').exists())

    def test_owned_artifact_never_authorizes_removing_external_git_lock(self):
        repo, base, candidate = self.setup_repo()
        (repo / 'code.txt').write_text('local\n')
        owned = repo / '.git/HEAD.cointos-publication'
        owned.write_bytes(b'abandoned CointOS artifact')
        lock = repo / '.git/HEAD.lock'
        lock.write_bytes(b'external Git owns this lock')
        inode = lock.stat().st_ino
        with git.repository_lock(repo):
            with self.assertRaisesRegex(ValueError, 'HEAD is locked'):
                git.publish(repo, 'main', candidate, base)
        self.assertEqual(lock.stat().st_ino, inode)
        self.assertEqual(lock.read_bytes(), b'external Git owns this lock')
        self.assertFalse(owned.exists())
        self.assertEqual(git.run(repo, 'branch', '--show-current'), 'main')
        self.assertEqual((repo / 'code.txt').read_text(), 'local\n')

    def test_linked_main_checkout_with_newline_path(self):
        repo, base, candidate = self.setup_repo()
        git.run(repo, 'switch', '-q', '--detach')
        linked = repo.parent / 'linked ü\ncheckout'
        git.run(repo, 'worktree', 'add', '-q', str(linked), 'main')
        (linked / 'code.txt').write_text('local')
        before = files(linked)
        self.kill_handoff(repo, base, candidate, 'after-link')
        with git.repository_lock(repo):
            publication = git.publish(repo, 'main', candidate, base)
        self.assertEqual(publication['workspace'], str(linked))
        self.assertEqual(files(linked), before)
        self.assertEqual(git.head(linked), base)
        self.assertEqual(git.head(repo, 'main'), candidate)

    def test_two_publishers_have_one_winner(self):
        repo, base, candidate = self.setup_repo()
        git.run(repo, 'switch', '-q', '-c', 'other')
        (repo / 'other').write_text('other')
        other = support.commit(repo)
        git.run(repo, 'switch', '-q', 'main')
        barrier, outcomes = threading.Barrier(2), []
        def publish(commit):
            barrier.wait()
            try:
                with git.repository_lock(repo):
                    git.publish(repo, 'main', commit, base)
                outcomes.append(('accepted', commit))
            except ValueError:
                outcomes.append(('refused', commit))
        threads = [threading.Thread(target=publish, args=(commit,)) for commit in (candidate, other)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(10)
        self.assertFalse(any(t.is_alive() for t in threads), 'publication deadlock')
        self.assertEqual(sorted(o[0] for o in outcomes), ['accepted', 'refused'])
        self.assertEqual(git.head(repo, 'main'), next(c for status, c in outcomes if status == 'accepted'))

    def test_unresolved_editor_merge_is_preserved_while_main_publishes(self):
        repo, base, candidate = self.setup_repo()
        (repo / 'code.txt').write_text('conflicting main\n')
        main = support.commit(repo)
        git.result(repo, 'merge', 'candidate')
        before, index = files(repo), git.run(repo, 'ls-files', '--stage', '-z')
        merge_head = (repo / '.git/MERGE_HEAD').read_bytes()
        combined = git.run(repo, 'commit-tree', git.run(repo, 'rev-parse', f'{candidate}^{{tree}}'),
                           '-p', main, '-p', candidate, '-m', 'verified fixture')
        self.kill_handoff(repo, main, combined, 'before-replace')
        with git.repository_lock(repo):
            publication = git.publish(repo, 'main', combined, main)
        self.assertTrue(publication['draft'].startswith('work/draft-'))
        self.assertEqual(git.head(repo), main)
        self.assertEqual(git.head(repo, 'main'), combined)
        self.assertEqual(files(repo), before)
        self.assertEqual(git.run(repo, 'ls-files', '--stage', '-z'), index)
        self.assertEqual((repo / '.git/MERGE_HEAD').read_bytes(), merge_head)

    def test_compare_and_swap_refuses_a_concurrent_writer(self):
        repo, base, candidate = self.setup_repo()
        git.run(repo, 'switch', '-q', '-c', 'other')
        (repo / 'other').write_text('other')
        other = support.commit(repo)
        git.run(repo, 'switch', '-q', 'main')
        original = git.run
        def race(where, *args):
            if args[:2] == ('update-ref', 'refs/heads/main'):
                original(where, 'update-ref', 'refs/heads/main', other, base)
            return original(where, *args)
        with patch.object(git, 'run', side_effect=race):
            with self.assertRaises(ValueError):
                git.publish(repo, 'main', candidate, base)
        self.assertEqual(git.head(repo, 'main'), other)

    def test_process_death_after_ref_leaves_safe_detached_checkout(self):
        repo, base, candidate = self.setup_repo()
        code = '''import os, sys
from cointos import git
original = git.run
def crash(repo, *args):
    result = original(repo, *args)
    if args[:2] == ('update-ref', 'refs/heads/main'): os._exit(43)
    return result
git.run = crash
git.publish(sys.argv[1], 'main', sys.argv[2], sys.argv[3])
'''
        result = subprocess.run([sys.executable, '-c', code, str(repo), candidate, base])
        self.assertEqual(result.returncode, 43)
        self.assertEqual(git.head(repo, 'main'), candidate)
        self.assertEqual(git.head(repo), base)
        self.assertEqual((repo / 'code.txt').read_text(), 'old\n')
        self.assertEqual(git.publish(repo, 'main', candidate, candidate), {'commit': candidate})
