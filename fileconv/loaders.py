import re
import os

import json
import yaml
import plistlib
from xml.parsers.expat import ExpatError, ErrorString

import sublime

from sublime_lib.view import OutputPanel, coorded_substr, base_scope
from sublime_lib.path import path_to_dict

appendix_regex = r'(?i)\.([^\.\-]+?)(?:-([^\.]+))?$'


def _join_multiline(string):
    return " ".join([line.strip() for line in string.split("\n")])


class LoaderProto(object):
    """Prototype class for data loaders of different types.

        Classes derived from this class (and in this file) will be appended
        to the module's ``get`` variable (a dict) with ``self.ext`` as their key.

        Variables to define:

            name (str)
                The loaders name, e.g. "JSON" or "Property List".

            ext (str)
                The default file extension.

            scope (str; optional)
                If the view's base scope equals this the file will be considered
                "valid" and then parsed.

            file_regex (str; optional)
                Regex to be applied to your output string in ``parse()``.

                This is used to determine the problem's position in the file and
                lets the user browse the errors with F4 and Shift+F4.
                Define up to three groups:
                    1: file path
                    2: line number
                    3: column

                For reference, see the "result_file_regex" key in a view's
                settings() or compare to build systems.

            output_panel_name (str; optional)
                If this is specified it will be used as the output panel's
                reference name.
                Defaults to ``"aaa_package_dev"``.

            ext_regex (str; optional)
                This regex will be used by get_ext_appendix() to determine the
                extension's appendix. The appendix should be in group 1.
                Defaults to ``r'(?i)\.%s(?:-([^\.]+))?$' % self.ext``.


        Methods to implement:

            parse(self, *args, **kwargs)
                This is called when the actual parsing should happen.

                The file to be read from is defined in ``self.file_path``.
                The parsed data should be returned.
                To output problems, use ``self.output.write_line(str)`` and use a
                string matched by ``self.file_regex`` if possible.

                *args, **kwargs parameters are passed from
                ``load(self, *args, **kwargs)``. If you want to specify any options
                or opntional parsing, use these.

        Methods you can override/implement
        (please read their documentation/code to understand their purposes):

            @classmethod
            _pre_init_(cls)

            @classmethod
            get_ext_appendix(cls, file_name)

            @classmethod
            get_new_file_ext(cls, view, file_name=None)

            new_file_ext(self)

            @classmethod
            file_is_valid(cls, view, file_name=None)

            is_valid(self)

            load(self, *args, **kwargs)
    """
    name   = ""
    ext    = ""
    scope  = None
    file_regex = ""
    output_panel_name = "aaa_package_dev"

    def __init__(self, window, view, file_path=None, output=None, *args, **kwargs):
        """Mirror the parameters to ``self``, do "init" stuff.
        """
        super(LoaderProto, self).__init__()  # object.__init__ takes no parameters

        self.window = window or view.window() or sublime.active_window()
        self.view = view
        self.file_path = file_path or view.file_name()

        path = os.path.split(self.file_path)[0]
        if isinstance(output, OutputPanel):
            output.set_path(path, self.file_regex)
            self.output = output
        else:
            self.output = OutputPanel(self.window, self.output_panel_name, file_regex=self.file_regex, path=path)
            self.output.clear()

    @classmethod
    def _pre_init_(cls):
        """Assign attributes that depend on other attributes defined by subclasses.
        """
        if not hasattr(cls, 'ext_regex'):
            cls.ext_regex = r'(?i)\.%s(?:-([^\.]+))?$' % cls.ext

    @classmethod
    def get_ext_appendix(cls, file_name):
        """Returns the appendix part of a file_name in style ".json-Appendix",
        "json" being ``self.ext`` respectively, or ``None``.
        """
        if file_name:
            ret = re.search(cls.ext_regex, file_name)
            if ret and ret.group(1):
                return ret.group(1)
        return None

    @classmethod
    def get_new_file_ext(cls, view, file_path=None):
        """Returns a tuple in style (str(ext), bool(prepend_ext)).

        The first part is the extension string, which may be ``None``.
        The second part is a boolean value that indicates whether the dumper
        (or the handler) should use the value of the first part as appendix
        and prepend the actual "new" file type.

        See also get_ext_appendix().
        """
        file_path = file_path or view and view.file_name()
        if not file_path:
            return (None, False)

        appendix = cls.get_ext_appendix(file_path)
        if appendix:
            return ('.' + appendix, False)

        ext = os.path.splitext(file_path)[1]
        if not ext == '.' + cls.ext and cls.file_is_valid(view, file_path):
            return (ext, True)

        return (None, False)

    def new_file_ext(self):
        """Instance method wrapper for ``cls.get_new_file_ext``.
        """
        return self.__class__.get_new_file_ext(self.view, self.file_path)

    @classmethod
    def file_is_valid(cls, view, file_path=None):
        """Returns a boolean whether ``file_path`` is a valid file for
        this loader.
        """
        file_path = file_path or view and view.file_name()
        if not file_path:
            return None

        return (cls.get_ext_appendix(file_path) is not None
                or path_to_dict(file_path).ext == '.' + cls.ext
                or (cls.scope is not None and view
                    and base_scope(view) == cls.scope))

    def is_valid(self):
        """Instance method wrapper for ``cls.file_is_valid``.
        """
        return self.__class__.file_is_valid(self.view, self.file_path)

    def load(self, *args, **kwargs):
        """Wraps ``self.parse(*args, **kwargs)`` and calls some other functions
        similar for almost every loader.

        This function is called by the handler directly.
        """
        if not self.is_valid():
            raise NotImplementedError("Not a %s file." % self.name)

        self.output.write_line("Parsing %s... (%s)" % (self.name, self.file_path))

        return self.parse(*args, **kwargs)

    def parse(self, *args, **kwargs):
        """To be implemented. Should return the parsed data from
        ``self.file_path`` as a Python object.
        """
        pass


class JSONLoader(LoaderProto):
    name   = "JSON"
    ext    = "json"
    scope  = "source.json"
    debug_base = 'Error parsing ' + name + ' "%s": %s'
    file_regex = debug_base % (r'(.*?)', r'.+? line (\d+) column (\d+)')

    # No parameters needed.
    def parse(self, *args, **kwargs):
        try:
            with open(self.file_path) as f:
                data = json.load(f)
        except ValueError, e:
            self.output.write_line(self.debug_base % (self.file_path, str(e)))
        except IOError, e:
            self.output.write_line('Error opening "%s": %s' % (self.file_path, str(e)))
            # TODO: Use buffer's contents instead?
        else:
            return data


class PlistLoader(LoaderProto):
    name = "Property List"
    ext  = "plist"
    debug_base = 'Error parsing ' + name + ' "%s": %s, line %s, column %s'
    file_regex = re.escape(debug_base).replace(r'\%', '%') % (r'(.*?)', r'.*?', r'(\d+)', r'(\d+)')
    DOCTYPE = "<!DOCTYPE plist"

    @classmethod
    def file_is_valid(cls, view, file_path=None):
        file_path = file_path or view and view.file_name()
        if not file_path:
            return None

        if (cls.get_ext_appendix(file_path) is not None
            or os.path.splitext(file_path)[1] == '.' + cls.ext):
            return True

        # Plists have no scope (syntax definition) since they are XML.
        # Instead, check for the DOCTYPE in the first two lines.
        if view:
            for i in range(2):  # This would be a really terrible one-liner
                text = coorded_substr(view, (i, 0), (i, len(cls.DOCTYPE)))
                if text == cls.DOCTYPE:
                    return True
        else:
            # Check in the file if view is not available
            with open(file_path) as f:
                i = 0
                for line in f:
                    i += 1
                    if i == 2:
                        break
                    if line.startswith(cls.DOCTYPE):
                        return True
        return False

    def parse(self, *args, **kwargs):
        try:
            data = plistlib.readPlist(self.file_path)
        except ExpatError, e:
            self.output.write_line(self.debug_base
                                % (self.file_path,
                                   ErrorString(e.code),
                                   e.lineno,
                                   e.offset)
                               )
        except BaseException, e:
            # Whatever could happen here ...
            self.output.write_line(self.debug_base % (self.file_path, str(e)))
        else:
            return data


class YAMLLoader(LoaderProto):
    name   = "YAML"
    ext    = "yaml"
    scope  = "source.yaml"
    debug_base = "Error parsing YAML: %s"
    file_regex = re.escape(debug_base).replace(r'\%', '%') % r'.+? in "(.*?)", line (\d+), column (\d+)'

    # No parameters needed.
    def parse(self, *args, **kwargs):
        try:
            with open(self.file_path) as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError, e:
            self.output.write_line(self.debug_base % _join_multiline(str(e)))
        except IOError, e:
            self.output.write_line('Error opening "%s": %s' % (self.file_path, str(e)))
            # TODO: Use buffer's contents instead?
        else:
            return data


###############################################################################


# Collect all the loaders and assign them to `get`
get = dict()
for type_name in dir():
    try:
        t = globals()[type_name]
        if t.__bases__:
            if issubclass(t, LoaderProto) and not t is LoaderProto:
                t._pre_init_()
                get[t.ext] = t

    except AttributeError:
        pass