"""
This module is responsible for setup of executors defined in buildtest
configuration. The BuildExecutor class initializes the executors and chooses the
executor class (LocalExecutor, LSFExecutor, SlurmExecutor, CobaltExecutor) to call depending
on executor name.
"""

import logging
import multiprocessing as mp
import os
import time

from buildtest.builders.base import BuilderBase
from buildtest.defaults import BUILDTEST_EXECUTOR_DIR, console
from buildtest.exceptions import ExecutorError
from buildtest.executors.base import BaseExecutor
from buildtest.executors.cobalt import CobaltExecutor
from buildtest.executors.local import LocalExecutor
from buildtest.executors.lsf import LSFExecutor
from buildtest.executors.pbs import PBSExecutor
from buildtest.executors.slurm import SlurmExecutor
from buildtest.tools.modules import get_module_commands
from buildtest.utils.file import create_dir, write_file
from buildtest.utils.tools import deep_get
from rich.table import Table

logger = logging.getLogger(__name__)


class BuildExecutor:
    """A BuildExecutor is responsible for initialing executors from buildtest configuration
    file which provides a list of executors. This class keeps track of all executors and provides
    the following methods:

    - **setup**: This method will  write executor's ``before_script.sh``  that is sourced in each test upon calling executor.
    - **run**: Responsible for invoking executor's **run** method based on builder object which is of type BuilderBase.
    - **poll**: This is responsible for invoking ``poll`` method for corresponding executor from the builder object by checking job state
    """

    def __init__(self, site_config, account=None, maxpendtime=None, pollinterval=None):
        """Initialize executors, meaning that we provide the buildtest
        configuration that are validated, and can instantiate
        each executor to be available.

        Args:
            site_config (buildtest.config.SiteConfiguration): instance of SiteConfiguration class that has the buildtest configuration
            account (str, optional): pass account name to charge batch jobs.
            maxpendtime (int, optional): maximum pend time in second until job is cancelled.
            pollinterval (int, optional): Number of seconds to wait until polling batch jobs
        """

        # stores a list of builders objects
        self.builders = []

        # default poll interval if not specified
        default_interval = 30

        self.configuration = site_config

        self.pollinterval = (
            pollinterval
            or deep_get(
                self.configuration.target_config,
                "executors",
                "defaults",
                "pollinterval",
            )
            or default_interval
        )

        self._completed = set()
        self._cancelled = set()

        self._pending = []

        # store a list of valid builders
        self._validbuilders = []

        self.executors = {}
        logger.debug("Getting Executors from buildtest settings")

        if site_config.valid_executors["local"]:
            for name in self.configuration.valid_executors["local"].keys():
                self.executors[name] = LocalExecutor(
                    name=name,
                    settings=self.configuration.valid_executors["local"][name][
                        "setting"
                    ],
                    site_configs=self.configuration,
                )

        if site_config.valid_executors["slurm"]:
            for name in self.configuration.valid_executors["slurm"]:
                self.executors[name] = SlurmExecutor(
                    name=name,
                    account=account,
                    settings=self.configuration.valid_executors["slurm"][name][
                        "setting"
                    ],
                    site_configs=self.configuration,
                    maxpendtime=maxpendtime,
                )

        if self.configuration.valid_executors["lsf"]:
            for name in self.configuration.valid_executors["lsf"]:
                self.executors[name] = LSFExecutor(
                    name=name,
                    account=account,
                    settings=self.configuration.valid_executors["lsf"][name]["setting"],
                    site_configs=self.configuration,
                    maxpendtime=maxpendtime,
                )

        if self.configuration.valid_executors["pbs"]:
            for name in self.configuration.valid_executors["pbs"]:
                self.executors[name] = PBSExecutor(
                    name=name,
                    account=account,
                    settings=self.configuration.valid_executors["pbs"][name]["setting"],
                    site_configs=self.configuration,
                    maxpendtime=maxpendtime,
                )

        if self.configuration.valid_executors["cobalt"]:
            for name in self.configuration.valid_executors["cobalt"]:
                self.executors[name] = CobaltExecutor(
                    name=name,
                    account=account,
                    settings=self.configuration.valid_executors["cobalt"][name][
                        "setting"
                    ],
                    site_configs=self.configuration,
                    maxpendtime=maxpendtime,
                )
        self.setup()

    def __str__(self):
        return "[buildtest-executor]"

    def __repr__(self):
        return "[buildtest-executor]"

    def names(self):
        """Return a list of executor names"""
        return list(self.executors.keys())

    def get(self, name):
        """Given the name of an executor return the executor object which is of subclass of `BaseExecutor`"""
        return self.executors.get(name)

    def get_validbuilders(self):
        """Return a list of valid builders that were run"""
        return self._validbuilders

    def cancelled(self):
        """Return a list of cancelled builders"""
        return self._cancelled

    def completed(self):
        return self._completed

    def _choose_executor(self, builder):
        """Choose executor is called at the onset of a run and poll stage. Given a builder
        object we retrieve the executor property ``builder.executor`` of the builder and check if
        there is an executor object and of type `BaseExecutor`.

        Args:
            builder (buildtest.buildsystem.base.BuilderBase): An instance object of BuilderBase type
        """

        # Get the executor by name, and add the builder to it
        executor = self.get(builder.executor)
        if not isinstance(executor, BaseExecutor):
            raise ExecutorError(
                f"{executor} is not a valid executor because it is not of type BaseExecutor class."
            )

        return executor

    def setup(self):
        """This method creates directory ``var/executors/<executor-name>`` for every executor defined
        in buildtest configuration and write scripts `before_script.sh` if the field ``before_script``
        is specified in executor section. This method is called after executors are initialized in the
        class **__init__** method.
        """

        for executor_name in self.names():
            create_dir(os.path.join(BUILDTEST_EXECUTOR_DIR, executor_name))
            executor_settings = self.executors[executor_name]._settings

            # if before_script field defined in executor section write content to var/executors/<executor>/before_script.sh
            file = os.path.join(
                BUILDTEST_EXECUTOR_DIR, executor_name, "before_script.sh"
            )
            module_cmds = get_module_commands(executor_settings.get("module"))

            content = "#!/bin/bash" + "\n"

            if module_cmds:
                content += "\n".join(module_cmds) + "\n"

            content += executor_settings.get("before_script") or ""
            write_file(file, content)

    def run(self, builders):
        """This method is responsible for running the build script for each builder async and
        gather the results. We setup a pool of worker settings by invoking ``multiprocessing.pool.Pool``
        and use `multiprocessing.pool.Pool.apply_sync() <https://docs.python.org/3/library/multiprocessing.html#multiprocessing.pool.Pool.apply_async>`_
        method for running test async which returns
        an object of type `multiprocessing.pool.AsyncResult <https://docs.python.org/3/library/multiprocessing.html#multiprocessing.pool.AsyncResult>`_
        which holds the result. Next we wait for results to arrive using `multiprocessing.pool.AsyncResult.get() <https://docs.python.org/3/library/multiprocessing.html#multiprocessing.pool.AsyncResult.get>`_
        method in a infinite loop until all test results are retrieved. The return type is the same builder object which is added to list
        of valid builders that is returned at end of method.
        """

        for builder in builders:
            executor = self._choose_executor(builder)
            executor.add_builder(builder)
            self.builders.append(builder)

        results = []

        num_workers = self.configuration.target_config.get("numprocs") or os.cpu_count()
        # in case user specifies more process than available CPU count use the min of the two numbers
        num_workers = min(num_workers, os.cpu_count())

        workers = mp.Pool(num_workers)

        console.print(f"Spawning {num_workers} processes for processing builders")

        for builder in self.builders:
            # console.print(
            #    f"[blue]{builder}[/]: Running Test script via command {builder.metadata['command']}[cyan]"
            # )

            executor = self._choose_executor(builder)
            if executor.type == "local":
                # local_builders.append(builder)
                result = workers.apply_async(executor.run, args=(builder,))
            else:
                # batch_builders.append(builder)
                result = workers.apply_async(executor.dispatch, args=(builder,))

            results.append(result)

        # loop until all async results are complete. results is a list of multiprocessing.pool.AsyncResult objects
        while results:
            async_results_ready = []
            for result in results:
                try:
                    # line below will raise TimeoutError if result is not ready, if its ready we append item to list and break
                    task = result.get(0.1)
                except mp.TimeoutError:
                    continue

                async_results_ready.append(result)

                # the task object could be None if it fails to submit job therefore we only add items that are valid builders
                if isinstance(task, BuilderBase):
                    self._validbuilders.append(task)

            # remove result that are complete
            for result in async_results_ready:
                results.remove(result)

        # close the worker pool by preventing any more tasks from being submitted
        workers.close()

        # terminate all worker processes
        workers.join()

        for builder in self._validbuilders:
            # returns True if attribute builder.job is an instance of class Job
            if builder.is_batch_job():
                self._pending.append(builder)

    def poll(self):
        """Poll all until all jobs are complete. At each poll interval, we poll each builder
        job state. If job is complete or failed we remove job from pending queue. In each interval we sleep
        and poll jobs until there is no pending jobs."""
        # only add builders that are batch jobs

        # poll until all pending jobs are complete
        while self._pending:
            print(f"Polling Jobs in {self.pollinterval} seconds")

            time.sleep(self.pollinterval)

            # store list of cancelled and completed job at each interval
            cancelled = []
            completed = []

            # for every pending job poll job and mark if job is finished or cancelled
            for builder in self._pending:

                # get executor instance for corresponding builder. This would be one of the following: SlurmExecutor, PBSExecutor, LSFExecutor, CobaltExecutor
                executor = self.get(builder.executor)
                # if builder is local executor we shouldn't be polling so we set job to
                # complete and return

                executor.poll(builder)

                if builder.is_complete():
                    completed.append(builder)
                elif builder.is_failure():
                    cancelled.append(builder)

            # remove completed jobs from pending queue
            if completed:
                for builder in completed:
                    self._pending.remove(builder)
                    self._completed.add(builder)

            # remove cancelled jobs from pending queue
            if cancelled:
                for builder in cancelled:
                    self._pending.remove(builder)
                    self._cancelled.add(builder)
                    # need to remove builder from self._validbuilders when job is cancelled because these builders are ones
                    # that have completed

                    self._validbuilders.remove(builder)

            self.print_pending_jobs()

        if self._cancelled:
            print("\nCancelled Jobs:", list(self._cancelled))

    def print_pending_jobs(self):
        """Print pending jobs in table format during each poll step"""
        table = Table(
            "[blue]Builder",
            "[blue]executor",
            "[blue]JobID",
            "[blue]JobState",
            "[blue]runtime",
            title="Pending Jobs",
        )
        for builder in self._pending:
            table.add_row(
                str(builder),
                builder.executor,
                builder.job.get(),
                builder.job.state(),
                str(builder.timer.duration()),
            )
        console.print(table)

    def print_polled_jobs(self):

        if not self._completed:
            return

        table = Table(
            "[blue]Builder",
            "[blue]executor",
            "[blue]JobID",
            "[blue]JobState",
            "[blue]runtime",
            title="Completed Jobs",
        )
        for builder in self._completed:
            table.add_row(
                str(builder),
                builder.executor,
                builder.job.get(),
                builder.job.state(),
                str(builder.metadata["result"]["runtime"]),
            )
        console.print(table)
