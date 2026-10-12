#!/usr/bin/env python3
import concurrent.futures
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

def ident(): return str(uuid4())

import task_state as n

class NativeLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name).resolve()
        self.repo=self.root/'map';self.repo.mkdir()
        self.git('init','-b','main');self.git('config','user.name','Diagnostic');self.git('config','user.email','diagnostic@example.invalid')
        self.git('remote','add','origin','https://github.com/paulshorey/map.git')
        (self.repo/'source.txt').write_text('baseline\n')
        self.git('add','.');self.git('commit','-m','baseline')
        self.base=self.git('rev-parse','HEAD');self.owner=ident()
        self.paths=patch.object(n,'STATE_ROOT',self.root/'private');self.paths.start()
        self.ctx=n.Project(self.repo,'paulshorey/map')
        n.bind_project(self.ctx,'local-test-project')
        self.pass_id=n.begin(self.ctx,self.owner)['pass']['id']
        self.prompt=n.state(self.ctx)/'request.txt';self.prompt.write_text('Implement only the scoped repair')

    def git(self,*args):
        return subprocess.run(['git','-C',str(self.repo),*args],capture_output=True,text=True,check=True).stdout.strip()

    def tearDown(self):
        self.paths.stop();self.tmp.cleanup()
    def prepared(self,scope='repair'):
            return n.prepare_task(self.ctx,scope,self.base,str(self.prompt),'human request','affected checks')['task']['id']

    def admitted(self):
            task=self.prepared()
            n.claim_task(self.ctx,task,self.pass_id)
            return task

    def test_concurrent_passes_never_reclaim_on_age(self):
            n.end(self.ctx,self.pass_id,'done')
            with concurrent.futures.ThreadPoolExecutor(4) as pool:
                results=list(pool.map(lambda _:n.begin(self.ctx,ident()),range(4)))
            self.assertEqual(sum(r['status']=='claimed' for r in results),1)
            self.assertEqual(sum(r['status']=='blocked' for r in results),3)
            self.assertEqual(n.begin(self.ctx,ident())['status'],'blocked')

    def test_duplicate_scope_and_ambiguous_dispatch(self):
            task=self.admitted()
            self.assertEqual(self.prepared(),task)
            with self.assertRaises(ValueError): n.claim_task(self.ctx,task,self.pass_id)
            self.assertEqual(n.task(self.ctx,task)['state'],'dispatching')
            self.assertEqual(Path(n.task(self.ctx,task)['prompt_path']).stat().st_mode & 0o777,0o600)

    def test_worktree_must_be_clean_correct_base_and_linked(self):
            task=self.admitted()
            thread=ident()
            with self.assertRaises(ValueError): n.start_task(self.ctx,task,self.repo,thread)
            self.assertEqual(n.task(self.ctx,task)['thread_id'],thread)
            self.assertEqual(n.task(self.ctx,task)['admission'],'blocked')
            worktree=self.root / 'coding'
            self.git('worktree','add','--detach',str(worktree),self.base)
            (worktree/'untracked.txt').write_text('human change')
            with self.assertRaises(ValueError): n.start_task(self.ctx,task,worktree,thread)
            (worktree/'untracked.txt').unlink()
            subprocess.run(['git','-C',str(worktree),'commit','--allow-empty','-m','different base'],check=True,capture_output=True)
            with self.assertRaises(ValueError): n.start_task(self.ctx,task,worktree,thread)
            subprocess.run(['git','-C',str(worktree),'checkout','--detach',self.base],check=True,capture_output=True)
            result=n.start_task(self.ctx,task,worktree,thread)
            self.assertEqual(result['admission'],'verified')
            self.assertEqual(n.task(self.ctx,task)['admission'],'verified')
            with self.assertRaises(ValueError): n.attach_task(self.ctx,task,ident(),'local')
            self.assertEqual(n.attach_task(self.ctx,task,thread,'local')['task']['cwd'],str(worktree.resolve()))

    def test_attach_race_only_one_thread_wins(self):
            task=self.admitted()
            def attach(_):
                try: n.attach_task(self.ctx,task,ident(),'local'); return True
                except ValueError: return False
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                self.assertEqual(sum(pool.map(attach,range(2))),1)

    def test_wrong_origin_rejected(self):
        self.git('remote','set-url','origin','https://github.com/other/map.git')
        with self.assertRaises(ValueError): self.prepared()
        with self.assertRaises(ValueError): n.Project(self.repo,'paulshorey/map')

    def test_worktrees_share_ownership_but_other_repositories_do_not(self):
        worktree=self.root/'coding';self.git('worktree','add','--detach',str(worktree),self.base)
        self.assertEqual(n.Project(worktree).state_path,self.ctx.state_path)
        other=self.root/'other'
        subprocess.run(['git','clone','--quiet',str(self.repo),str(other)],check=True)
        subprocess.run(['git','-C',str(other),'remote','set-url','origin','https://github.com/paulshorey/notes.git'],check=True)
        self.assertNotEqual(n.Project(other).state_path,self.ctx.state_path)

if __name__=='__main__':
    os.umask(0o077);unittest.main(verbosity=2)
