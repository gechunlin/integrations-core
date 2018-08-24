# (C) Datadog, Inc. 2018
# All rights reserved
# Licensed under a 3-clause BSD style license (see LICENSE)
import os

import click

from .utils import CONTEXT_SETTINGS, abort, echo_info, echo_success, echo_waiting
from ..constants import TESTABLE_FILE_EXTENSIONS, get_root
from ..git import files_changed
from ..utils import get_testable_checks
from ...subprocess import run_command
from ... import EnvVars
from ...utils import chdir, remove_path, running_on_ci


def check_namespace(check):
    if check == 'datadog_checks_base':
        return 'datadog_checks'
    elif check == 'datadog_checks_dev':
        return 'datadog_checks.dev'
    else:
        return 'datadog_checks.{}'.format(check)


def testable_files(files):
    """
    Given a list of files, return the files that have an extension listed in FILE_EXTENSIONS_TO_TEST
    """
    return [f for f in files if f.endswith(TESTABLE_FILE_EXTENSIONS)]


@click.command(
    context_settings=CONTEXT_SETTINGS,
    short_help='Run tests'
)
@click.argument('checks', nargs=-1)
@click.option('--bench', '-b', is_flag=True, help='Run only benchmarks')
@click.option('--cov', '-c', 'coverage', is_flag=True, help='Computes, then outputs coverage after testing')
@click.option('--keep-cov', '-kc', is_flag=True, help='Keep coverage reports')
@click.option('--verbose', '-v', count=True, help='Increase verbosity')
def test(checks, bench, coverage, keep_cov, verbose):
    """Run tests for Agent-based checks.

    If no checks are specified, this will only test checks that
    were changed compared to the master branch.
    """
    root = get_root()

    if not checks:
        # get the list of the files that changed compared to `master`
        changed_files = files_changed()

        # get the list of files that can change the implementation of a check
        files_requiring_tests = testable_files(changed_files)

        # get the integrations associated with changed files
        changed_checks = {line.split('/')[0] for line in files_requiring_tests}

        checks = sorted(changed_checks & get_testable_checks())
    else:
        checks = sorted(set(checks) & get_testable_checks())

    if not checks:
        echo_info('No checks to test!')
        return

    num_checks = len(checks)

    if bench:
        pytest_options = '--verbosity={} --benchmark-only --benchmark-cprofile=tottime'.format(verbose or 1)
    else:
        pytest_options = '--verbosity={} --benchmark-skip'.format(verbose or 1)

    if coverage:
        pytest_options = '{} {}'.format(
            pytest_options,
            '--cov={} '
            '--cov=tests '
            '--cov-config=../.coveragerc '
            '--cov-append '
            '--cov-report='
        )

    test_env_vars = {
        'TOX_TESTENV_PASSENV': 'PYTEST_ADDOPTS',
        'PYTEST_ADDOPTS': '',
    }

    for i, check in enumerate(checks, 1):
        check_dir = os.path.join(root, check)

        test_env_vars['PYTEST_ADDOPTS'] = (
            pytest_options.format(check_namespace(check)) if coverage else pytest_options
        )
        if verbose:
            echo_info('pytest options: `{}`'.format(test_env_vars['PYTEST_ADDOPTS']))

        with chdir(check_dir):
            env_list = run_command('tox --listenvs', capture='out').stdout
            env_list = [e.strip() for e in env_list.splitlines()]

            with EnvVars(test_env_vars):
                if bench:
                    benches = [e for e in env_list if 'bench' in e]
                    if benches:
                        wait_text = 'Running benchmarks for `{}`'.format(check)
                        echo_waiting(wait_text)
                        echo_waiting('-' * len(wait_text))

                        result = run_command('tox --develop -e {}'.format(','.join(benches)))
                        if result.code:
                            abort('\nFailed!', code=result.code)
                else:
                    non_benches = [e for e in env_list if 'bench' not in e]
                    if non_benches:
                        wait_text = 'Running tests for `{}`'.format(check)
                        echo_waiting(wait_text)
                        echo_waiting('-' * len(wait_text))

                        result = run_command('tox --develop -e {}'.format(','.join(non_benches)))
                        if result.code:
                            abort('\nFailed!', code=result.code)

            if coverage:
                echo_info('\n---------- Coverage report ----------\n')

                result = run_command('coverage report --rcfile=../.coveragerc')
                if result.code and check != 'datadog_checks_tests_helper':
                    abort('\nFailed!', code=result.code)

                if running_on_ci():
                    run_command('codecov -F {}'.format(check))
                else:
                    if not keep_cov:
                        remove_path(os.path.join(check_dir, '.coverage'))

        echo_success('\nPassed!{}'.format('' if i == num_checks else '\n'))
