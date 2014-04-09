import re
import os.path

from django.conf import settings

class BaseFixtureCompiler(object):
    fixtures = None  # Pre-req fixtures for testing runtime, if required
    filename = None  # Generated automatically from class name if not given
    format = 'json'

    dumpdata_excludes = [
        # appnames for things that shouldn't get wildly duplicated throughout all fixtures

        # Things that live on the non-default db
        'aec_remrate',
        'customer_neea',

        # Django stuff
        'auth.permission',
        'contenttypes',
        'flatpages',
        'sites',

        # Third-party static data
        'dynamicsites',
    ]

    def populate_database(self, **options):
        """ Loads arbitrary data to the blank database. """

    def get_fixture_dir(self):
        """ Gets the path to this app's "fixtures/" directory. """
        names = self.__module__.split('.')
        n = len(names)
        for i in range(n):
            if '.'.join(names[:(n-i)]) in settings.INSTALLED_APPS:
                return os.path.join(*(names[:(n-i)] + ['fixtures']))
        raise ValueError("Fixture compiler '{}.{}' does not appear to live in an installed app.  "
                         "Cannot automatically determine a fixture directory.".format(
                         self.__module__, self.__class__.__name__))

    def get_fixture_path(self):
        """ Returns the full path to which the compiler intends to write its content. """
        return os.path.join(self.get_fixture_dir(), self.get_filename())

    def get_filename(self):
        """
        Returns the declared filename, or else the class name converted to snake_case, and stripped
        of any trailing "_fixture_compiler" suffix.
        """
        if self.filename:
            return self.filename

        # Convert the class name to snake_case
        name = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', self.__class__.__name__)
        name = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', name).lower()

        # Remove trailing "_fixture_compiler"
        name = re.sub(r'_fixture_compiler$', '', name)

        if not name:
            raise ValueError("Fixture compiler '{}.{}' is not specific enough to automatically "
                             "generate a filename.".format(self.__module__, self.__class__, __name__))

        return os.path.join(*(['compiled'] + ['{}.{}'.format(name, self.format)]))
