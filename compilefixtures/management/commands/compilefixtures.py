from __future__ import unicode_literals

import os
import os.path
import importlib
import inspect

from django.core import management
from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command
from django.test.simple import DjangoTestSuiteRunner
from django.conf import settings

class Command(BaseCommand):
    """
    Iterates installed apps (or the supplied list of apps) and examines their tests/factories.py
    file to find a class ``FixtureCompiler()``, which execute all python factories that
    it wants to load into the database state.  See the base class in core/tests/factories.py for
    a simple example of how the class configures itself.

    After a visit to an app's FixtureCompiler, this command will serialize the database state and
    dump it to a file, whose name is specified by the compiler class.  The filename is treated as a
    path relative to ``appname/fixtures/``.  The database state is then wiped.

    If multiple apps are given in the argument list to this command, each one will get a clean
    database set up for it to execute upon, making it similar to the testing environment.
    """

    args = '<appname appname ...>'
    help = 'Generates fixure files based on factories we would like to use in testing.'
    requires_model_validation = False

    test_runner = None

    # Utilities to get these checks factored out of the main handle()
    def _ensure_db_built(self):
        if not self.test_runner:
            self.test_runner = DjangoTestSuiteRunner()
            self.old_config = self.test_runner.setup_databases()

    def _get_module_name(self, app):
        return app + '.tests.fixturecompilers'

    def _get_module_path(self, app):
        return self._get_module_name(app).replace('.', '/') + '.py'

    def _has_factories(self, app):
        return os.path.isfile(self._get_module_path(app))

    def _get_fixture_compilers(self, module):
        from apps.core.tests.fixturecompilers import BaseFixtureCompiler
        compilers = []
        for name in dir(module):
            item = getattr(module, name)
            if inspect.isclass(item) and item is not BaseFixtureCompiler and \
                    issubclass(item, BaseFixtureCompiler):
                compilers.append(item)
        return compilers

    def _get_compiler_module(self, dotted_path, explicit_list):
        module = None
        explicit_compiler = None
        names = dotted_path.split('.')

        # Import a, then a.b, then a.b.c until we reach the end or find an ImportError
        for i in range(1, len(names) + 1):
            try:
                module = importlib.import_module('.'.join(names[:i]))
            except ImportError:
                if i < len(names):
                    raise

                explicit_compiler = getattr(module, names[-1])

                # We're at the end anyway, but use break so for..else clause doesn't execute
                break
        else:
            # If we imported everything in the chain without error, we're sitting on a module
            # object that might contain fixture compilers.  However, if an abbreviated dotted
            # path was given, we have to dig deeper into the default location for these
            # compilers.
            if dotted_path in settings.INSTALLED_APPS:
                try:
                    module = importlib.import_module(self._get_module_name(dotted_path))
                except ImportError:
                    if explicit_list:
                        # Only raise the exception of it arose because of the user explicitly
                        # asking for this dotted path.
                        raise
                    # If all installed apps are being investigated, this error only means that
                    # the app doesn't implement any fixture compilers.
                    return None, None
        return module, explicit_compiler

    def handle(self, *apps, **options):
        # A trick from south/managements/commands/__init__.py to force "syncdb" to mean the built-in
        # Django version of it, not the one south uses to prevent migration apps from syncing.
        management.get_commands()
        management._commands['syncdb'] = 'django.core'

        explicit_list = len(apps) > 0
        if not apps:
            apps = list(settings.INSTALLED_APPS)

        if not explicit_list:
            # In the case of compiling ALL app fixtures, remove apps that don't have fixtures.py
            apps = list(filter(self._has_factories, apps))
            self.stdout.write("Found {} apps with tests/fixturecompilers.py".format(len(apps)))
            self.stdout.write("")

        quantity = self.process_apps(apps, options, explicit_list)
        self.stdout.write("")
        self.stdout.write("======================================")
        self.stdout.write("{} fixture compilers finished running.".format(quantity))
        self.stdout.write("")

        if self.test_runner:
            self.test_runner.teardown_databases(self.old_config)

    def process_apps(self, dotted_paths, options, explicit_list):
        compilers_processed = 0
        for dotted_path in dotted_paths:
            module, explicit_compiler = self._get_compiler_module(dotted_path, explicit_list)

            if module is None:
                continue

            if not explicit_compiler:
                # Find all fixture compilers in the module
                compilers = self._get_fixture_compilers(module)
                if not compilers:
                    # self.stdout.write("{} does not contain any fixture compilers.".format(module.__name__))
                    continue
                self.stdout.write("{} contains {} fixture compilers.".format(module.__name__, len(compilers)))
            else:
                compilers = [explicit_compiler]

            # Run the code that generates the fixture data
            for FixtureCompiler in compilers:
                # Deferred db construction, to allow faster detection of problems on first run
                self._ensure_db_built()

                compiler = FixtureCompiler()
                # Make certain we know where the "fixtures/" folder will be
                base_dir = compiler.get_fixture_dir()
                if not base_dir:
                    self.stderr.write("Cannot determine app label for {}".format(dotted_path))
                    # This will fail identically for all compilers in the same dottedpath, so we
                    # can break out of this loop so the outer loop continues more quickly.
                    break

                self.compile_fixture(compiler, base_dir, options)
                compilers_processed += 1
                call_command('flush', interactive=False, load_initial_data=True)

        return compilers_processed

    def compile_fixture(self, compiler, base_dir, options):

        filename = compiler.get_filename()
        path = os.path.join(base_dir, filename)
        dirname = os.path.dirname(path)

        self.stdout.write(" => Compiling {} to '{}'".format(compiler.__class__.__name__, path))
        compiler.populate_database(**options)

        if not os.path.isdir(dirname):
            os.makedirs(dirname)

        with open(path, 'w') as f:
            # Dump all database content after running the population function.
            call_command('dumpdata', exclude=compiler.dumpdata_excludes,
                         format=compiler.format, use_natural_keys=True,
                         traceback=True, indent=4, stdout=f, stderr=self.stderr)

        return True
