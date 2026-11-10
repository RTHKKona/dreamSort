# install worker

import os
import shutil
import zipfile

from .thread_worker import Worker

try:
    import py7zr
    PY7ZR_SUPPORT = True
except ImportError:  # pragma: no cover - optional dependency
    py7zr = None
    PY7ZR_SUPPORT = False


class InstallWorker(Worker):
    # run the jobs

    def __init__(self, jobs):
        super().__init__(lambda: None)
        self.jobs = list(jobs)

    def _remove_destination(self, dest):
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        elif os.path.exists(dest):
            os.remove(dest)

    def _run_job(self, job):
        kind = job["kind"]
        src = job["src"]
        dest = job["dest"]
        if job.get("replace") and os.path.exists(dest):
            self._remove_destination(dest)
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        if kind == "zip":
            with zipfile.ZipFile(src, "r") as archive:
                archive.extractall(dest)
        elif kind == "7z":
            if py7zr is None:
                raise RuntimeError("Install 'py7zr' to extract .7z files.")
            # TODO: handle missing py7zr
            os.makedirs(dest, exist_ok=True)
            with py7zr.SevenZipFile(src, mode="r") as archive:
                archive.extractall(path=dest)
        elif kind == "copy_tree":
            shutil.copytree(src, dest, dirs_exist_ok=True)
        elif kind == "copy_file":
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
        else:
            raise ValueError("unknown install job kind: %r" % (kind,))

    def run(self):
        done = []
        errors = []
        total = len(self.jobs)
        for index, job in enumerate(self.jobs, 1):
            label = job.get("label") or os.path.basename(job.get("src", ""))
            self.progress.emit({"index": index, "total": total, "text": label})
            try:
                self._run_job(job)
            except Exception as exc:  # noqa: BLE001 - surfaced to the user
                errors.append("Could not install '%s':\n%s" % (label, exc))
                continue
            done.append(job)
        self.finished.emit({"done": done, "errors": errors})
