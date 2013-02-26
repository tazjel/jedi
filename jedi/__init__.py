"""
Jedi is an autocompletion tool for Python that can be used in IDEs/editors.
Jedi works. Jedi is fast. It understands all of the basic Python syntax
elements including many builtin functions.

Additionaly, Jedi suports two different goto functions and has support for
renaming as well as Pydoc support and some other IDE features.

Jedi uses a very simple API to connect with IDE's. There's a reference
implementation as a `VIM-Plugin <http://github.com/davidhalter/jedi-vim>`_,
which uses Jedi's autocompletion.  I encourage you to use Jedi in your IDEs.
It's really easy. If there are any problems (also with licensing), just contact
me.

To give you a simple example how you can use the Jedi library, here is an
example for the autocompletion feature:

>>> import jedi
>>> source = '''import json; json.l'''
>>> script = jedi.Script(source, 1, 19, 'example.py')
>>> script
<Script: 'example.py'>
>>> completions = script.complete()
>>> completions
[<Completion: load>, <Completion: loads>]
>>> print(completions[0].complete)
oad
>>> print(completions[0].word)
load

As you see Jedi is pretty simple and allows you to concentrate on writing a
good text editor, while still having very good IDE features for Python.
"""

import sys

# python imports are hell sometimes. Especially the combination of relative
# imports and circular imports... Just avoid it:
sys.path.insert(0, __path__[0])

from .api import Script, NotFoundError, set_debug_function, _quick_complete
from . import settings

sys.path.pop(0)
