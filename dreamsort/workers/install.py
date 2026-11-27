# install worker

import os
import shutil
import time

from ..gamebanana.policy import manifest_at_root
from ..helpers.archive import safe_extract
from ..helpers.layout import classify_layout, find_mod_root, sanitize_name
from ..install.commit import commit_mod
from .thread_worker import Worker

try:
    import py7zr
    PY7ZR_SUPPORT = True
except ImportError:  # optional dependency
    py7zr = None
    PY7ZR_SUPPORT = False

REPORT_INTERVAL = 0.04


class InstallWorker(Worker):
    # extract staged archives, then commit them into place

    def __init__(self, jobs):
        super().__init__(lambda: None)
        self.jobs = list(jobs)

    @staticmethod
    def _count_tree(path):
        total = 0
        for _root, _dirs, files in os.walk(path):
            total += len(files)
        return total

    def _copy_tree(self, src, dest, report):
        total = self._count_tree(src) or 1
        done = [0]

        def copy_file(source, target, *, follow_symlinks=True):
            shutil.copy2(source, target, follow_symlinks=follow_symlinks)
            done[0] += 1
            report(done[0], total)

        shutil.copytree(src, dest, dirs_exist_ok=True,
                        copy_function=copy_file)

    def _reporter(self, index, total, label):
        # one flat 0..1 bar across every job
        base = (index - 1) / float(total or 1)
        span = 1.0 / float(total or 1)
        last = [0.0]

        def report(done, of):
            part = (float(done) / of) if of else 0.0
            value = base + min(max(part, 0.0), 1.0) * span
            now = time.monotonic()
            if value < 1.0 and now - last[0] < REPORT_INTERVAL:
                return
            last[0] = now
            self.progress.emit({"index": index, "total": total,
                                "text": label, "fraction": value})

        return report

    def _run_job(self, job, report):
        kind = job["kind"]
        src = job["src"]
        dest = job["dest"]
        os.makedirs(dest, exist_ok=True)

        if kind in ("zip", "7z", "rar"):
            safe_extract(src, dest, allow_scripts=bool(job.get("allow_scripts")),
                         progress=report)
        elif kind == "copy_tree":
            self._copy_tree(src, dest, report)
        elif kind == "copy_file":
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
            report(1, 1)
        else:
            raise ValueError("unknown install job kind: %r" % (kind,))

    def _commit_job(self, job):
        commit = job.get("commit")
        if not commit:
            return None
        layout = find_mod_root(job["dest"])
        source = layout["source"]
        if job.get("require_manifest") and not manifest_at_root(source):
            raise ValueError(
                "no manifest.json or manifest.txt at the mod root; "
                "GameBanana installs need one")
        dest_name = (commit.get("display_name") or layout["name"]
                     or commit.get("dest_name"))
        dest_name = sanitize_name(dest_name)
        job["layout_kind"] = classify_layout(source)
        return commit_mod(source, commit["target_dir"], dest_name,
                          record=commit.get("record"))

    def run(self):
        try:
            done = []
            errors = []
            total = len(self.jobs)
            for index, job in enumerate(self.jobs, 1):
                label = job.get("label") or os.path.basename(job.get("src", ""))
                report = self._reporter(index, total, label)
                report(0, 1)
                try:
                    self._run_job(job, report)
                    job["final_dest"] = self._commit_job(job)
                except Exception as exc:  # surfaced to the user
                    errors.append("Could not install '%s':\n%s" % (label, exc))
                    continue
                done.append(job)
            self.finished.emit({"done": done, "errors": errors})
        except Exception as exc:
            self.fail(exc)
