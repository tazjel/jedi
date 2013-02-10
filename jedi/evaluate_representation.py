"""
Like described in the :mod:`parsing_representation` module, there's a need for
an ast like module to represent the states of parsed modules.

But now there are also structures in Python that need a little bit more than
that. An ``Instance`` for example is only a ``Class`` before it is
instantiated. This class represents these cases.

So, why is there also a ``Class`` class here? Well, there are decorators and
they change classes in Python 3.
"""
import sys
import copy
import itertools

from _compatibility import property, use_metaclass, next, hasattr
import parsing_representation as pr
import imports
import docstrings
import cache
import builtin
import dynamic
import helpers
import recursion
import debug
import evaluate
import common


class DecoratorNotFound(LookupError):
    """
    Decorators are sometimes not found, if that happens, that error is raised.
    """
    pass


class Executable(pr.Base):
    """
    An instance is also an executable - because __init__ is called
    :param var_args: The param input array, consist of `pr.Array` or list.
    """
    def __init__(self, base, var_args=[]):
        self.base = base
        self.var_args = var_args

    def get_parent_until(self, *args, **kwargs):
        return self.base.get_parent_until(*args, **kwargs)

    @property
    def parent(self):
        return self.base.parent


class Instance(use_metaclass(cache.CachedMetaClass, Executable)):
    """ This class is used to evaluate instances. """
    def __init__(self, base, var_args=[]):
        super(Instance, self).__init__(base, var_args)
        if str(base.name) in ['list', 'set'] \
                    and builtin.Builtin.scope == base.get_parent_until():
            # compare the module path with the builtin name.
            self.var_args = dynamic.check_array_instances(self)
        else:
            # need to execute the __init__ function, because the dynamic param
            # searching needs it.
            try:
                self.execute_subscope_by_name('__init__', self.var_args)
            except KeyError:
                pass
        # Generated instances are classes that are just generated by self
        # (No var_args) used.
        self.is_generated = False

    @cache.memoize_default()
    def get_init_execution(self, func):
        func = InstanceElement(self, func, True)
        return Execution(func, self.var_args)

    def get_func_self_name(self, func):
        """
        Returns the name of the first param in a class method (which is
        normally self
        """
        try:
            return func.params[0].used_vars[0].names[0]
        except IndexError:
            return None

    def get_self_properties(self):
        def add_self_dot_name(name):
            n = copy.copy(name)
            n.names = n.names[1:]
            names.append(InstanceElement(self, n))

        names = []
        # This loop adds the names of the self object, copies them and removes
        # the self.
        for sub in self.base.subscopes:
            if isinstance(sub, pr.Class):
                continue
            # Get the self name, if there's one.
            self_name = self.get_func_self_name(sub)
            if self_name:
                # Check the __init__ function.
                if sub.name.get_code() == '__init__':
                    sub = self.get_init_execution(sub)
                for n in sub.get_set_vars():
                    # Only names with the selfname are being added.
                    # It is also important, that they have a len() of 2,
                    # because otherwise, they are just something else
                    if n.names[0] == self_name and len(n.names) == 2:
                        add_self_dot_name(n)

        for s in self.base.get_super_classes():
            if s == self.base:
                # I don't know how this could happen... But saw it once.
                continue
            names += Instance(s).get_self_properties()

        return names

    def get_subscope_by_name(self, name):
        sub = self.base.get_subscope_by_name(name)
        return InstanceElement(self, sub, True)

    def execute_subscope_by_name(self, name, args=[]):
        method = self.get_subscope_by_name(name)
        return Execution(method, args).get_return_types()

    def get_descriptor_return(self, obj):
        """ Throws a KeyError if there's no method. """
        # Arguments in __get__ descriptors are obj, class.
        # `method` is the new parent of the array, don't know if that's good.
        args = [obj, obj.base] if isinstance(obj, Instance) else [None, obj]
        return self.execute_subscope_by_name('__get__', args)

    @cache.memoize_default([])
    def get_defined_names(self):
        """
        Get the instance vars of a class. This includes the vars of all
        classes
        """
        names = self.get_self_properties()

        class_names = self.base.get_defined_names()
        for var in class_names:
            names.append(InstanceElement(self, var, True))
        return names

    def scope_generator(self):
        """
        An Instance has two scopes: The scope with self names and the class
        scope. Instance variables have priority over the class scope.
        """
        yield self, self.get_self_properties()

        names = []
        class_names = self.base.get_defined_names()
        for var in class_names:
            names.append(InstanceElement(self, var, True))
        yield self, names

    def get_index_types(self, index=None):
        args = [] if index is None else [index]
        try:
            return self.execute_subscope_by_name('__getitem__', args)
        except KeyError:
            debug.warning('No __getitem__, cannot access the array.')
            return []

    def __getattr__(self, name):
        if name not in ['start_pos', 'end_pos', 'name', 'get_imports',
                                                        'docstr', 'asserts']:
            raise AttributeError("Instance %s: Don't touch this (%s)!"
                                    % (self, name))
        return getattr(self.base, name)

    def __repr__(self):
        return "<e%s of %s (var_args: %s)>" % \
                (type(self).__name__, self.base, len(self.var_args or []))


class InstanceElement(use_metaclass(cache.CachedMetaClass)):
    """
    InstanceElement is a wrapper for any object, that is used as an instance
    variable (e.g. self.variable or class methods).
    """
    def __init__(self, instance, var, is_class_var=False):
        if isinstance(var, pr.Function):
            var = Function(var)
        elif isinstance(var, pr.Class):
            var = Class(var)
        self.instance = instance
        self.var = var
        self.is_class_var = is_class_var

    @property
    @cache.memoize_default()
    def parent(self):
        par = self.var.parent
        if isinstance(par, Class) and par == self.instance.base \
                        or isinstance(par, pr.Class) \
                            and par == self.instance.base.base:
            par = self.instance
        elif not isinstance(par, pr.Module):
            par = InstanceElement(self.instance, par, self.is_class_var)
        return par

    def get_parent_until(self, *args, **kwargs):
        return pr.Simple.get_parent_until(self, *args, **kwargs)

    def get_decorated_func(self):
        """ Needed because the InstanceElement should not be stripped """
        func = self.var.get_decorated_func()
        if func == self.var:
            return self
        return func

    def get_commands(self):
        # Copy and modify the array.
        origin = self.var.get_commands()
        # Delete parent, because it isn't used anymore.
        new = helpers.fast_parent_copy(origin)
        par = InstanceElement(self.instance, origin.parent_stmt,
                                                    self.is_class_var)
        new.parent_stmt = par
        return new

    def __getattr__(self, name):
        return getattr(self.var, name)

    def isinstance(self, *cls):
        return isinstance(self.var, cls)

    def __repr__(self):
        return "<%s of %s>" % (type(self).__name__, self.var)


class Class(use_metaclass(cache.CachedMetaClass, pr.Base)):
    """
    This class is not only important to extend `pr.Class`, it is also a
    important for descriptors (if the descriptor methods are evaluated or not).
    """
    def __init__(self, base):
        self.base = base

    @cache.memoize_default(default=[])
    def get_super_classes(self):
        supers = []
        # TODO care for mro stuff (multiple super classes).
        for s in self.base.supers:
            # Super classes are statements.
            for cls in evaluate.follow_statement(s):
                if not isinstance(cls, Class):
                    debug.warning('Received non class, as a super class')
                    continue  # Just ignore other stuff (user input error).
                supers.append(cls)
        if not supers and self.base.parent != builtin.Builtin.scope:
            # add `object` to classes
            supers += evaluate.find_name(builtin.Builtin.scope, 'object')
        return supers

    @cache.memoize_default(default=[])
    def get_defined_names(self):
        def in_iterable(name, iterable):
            """ checks if the name is in the variable 'iterable'. """
            for i in iterable:
                # Only the last name is important, because these names have a
                # maximal length of 2, with the first one being `self`.
                if i.names[-1] == name.names[-1]:
                    return True
            return False

        result = self.base.get_defined_names()
        super_result = []
        # TODO mro!
        for cls in self.get_super_classes():
            # Get the inherited names.
            for i in cls.get_defined_names():
                if not in_iterable(i, result):
                    super_result.append(i)
        result += super_result
        return result

    def get_subscope_by_name(self, name):
        for sub in reversed(self.subscopes):
            if sub.name.get_code() == name:
                return sub
        raise KeyError("Couldn't find subscope.")

    @property
    def name(self):
        return self.base.name

    def __getattr__(self, name):
        if name not in ['start_pos', 'end_pos', 'parent', 'subscopes',
                    'get_imports', 'get_parent_until', 'docstr', 'asserts']:
            raise AttributeError("Don't touch this (%s)!" % name)
        return getattr(self.base, name)

    def __repr__(self):
        return "<e%s of %s>" % (type(self).__name__, self.base)


class Function(use_metaclass(cache.CachedMetaClass, pr.Base)):
    """
    Needed because of decorators. Decorators are evaluated here.
    """
    def __init__(self, func, is_decorated=False):
        """ This should not be called directly """
        self.base_func = func
        self.is_decorated = is_decorated

    @property
    @cache.memoize_default()
    def _decorated_func(self):
        """
        Returns the function, that is to be executed in the end.
        This is also the places where the decorators are processed.
        """
        f = self.base_func

        # Only enter it, if has not already been processed.
        if not self.is_decorated:
            for dec in reversed(self.base_func.decorators):
                debug.dbg('decorator:', dec, f)
                dec_results = evaluate.follow_statement(dec)
                if not len(dec_results):
                    debug.warning('decorator func not found: %s in stmt %s' %
                                                        (self.base_func, dec))
                    return None
                if len(dec_results) > 1:
                    debug.warning('multiple decorators found', self.base_func,
                                                            dec_results)
                decorator = dec_results.pop()
                # Create param array.
                old_func = Function(f, is_decorated=True)

                wrappers = Execution(decorator, (old_func,)).get_return_types()
                if not len(wrappers):
                    debug.warning('no wrappers found', self.base_func)
                    return None
                if len(wrappers) > 1:
                    debug.warning('multiple wrappers found', self.base_func,
                                                                wrappers)
                # This is here, that the wrapper gets executed.
                f = wrappers[0]

                debug.dbg('decorator end', f)
        if f != self.base_func and isinstance(f, pr.Function):
            f = Function(f)
        return f

    def get_decorated_func(self):
        if self._decorated_func is None:
            raise DecoratorNotFound()
        if self._decorated_func == self.base_func:
            return self
        return self._decorated_func

    def get_magic_method_names(self):
        return builtin.Builtin.magic_function_scope.get_defined_names()

    def get_magic_method_scope(self):
        return builtin.Builtin.magic_function_scope

    def __getattr__(self, name):
        return getattr(self.base_func, name)

    def __repr__(self):
        dec = ''
        if self._decorated_func != self.base_func:
            dec = " is " + repr(self._decorated_func)
        return "<e%s of %s%s>" % (type(self).__name__, self.base_func, dec)


class Execution(Executable):
    """
    This class is used to evaluate functions and their returns.

    This is the most complicated class, because it contains the logic to
    transfer parameters. It is even more complicated, because there may be
    multiple calls to functions and recursion has to be avoided. But this is
    responsibility of the decorators.
    """
    def follow_var_arg(self, index):
        try:
            stmt = self.var_args[index]
        except IndexError:
            return []
        else:
            if isinstance(stmt, pr.Statement):
                return evaluate.follow_statement(stmt)
            else:
                return [stmt]  # just some arbitrary object

    @cache.memoize_default(default=[])
    @recursion.ExecutionRecursionDecorator
    def get_return_types(self, evaluate_generator=False):
        """ Get the return types of a function. """
        stmts = []
        if self.base.parent == builtin.Builtin.scope \
                and not isinstance(self.base, (Generator, Array)):
            func_name = str(self.base.name)

            # some implementations of builtins:
            if func_name == 'getattr':
                # follow the first param
                try:
                    objects = self.follow_var_arg(0)
                    names = self.follow_var_arg(1)
                except IndexError:
                    debug.warning('getattr() called with to few args.')
                    return []

                for obj in objects:
                    if not isinstance(obj, (Instance, Class)):
                        debug.warning('getattr called without instance')
                        continue

                    for name in names:
                        key = name.var_args.get_only_subelement()
                        stmts += evaluate.follow_path(iter([key]), obj,
                                                        self.base)
                return stmts
            elif func_name == 'type':
                # otherwise it would be a metaclass
                if len(self.var_args) == 1:
                    objects = self.follow_var_arg(0)
                    return [o.base for o in objects if isinstance(o, Instance)]
            elif func_name == 'super':
                # TODO make this able to detect multiple inheritance supers
                accept = (pr.Function,)
                func = self.var_args.get_parent_until(accept)
                if func.isinstance(*accept):
                    cls = func.get_parent_until(accept + (pr.Class,),
                                                    include_current=False)
                    if isinstance(cls, pr.Class):
                        cls = Class(cls)
                        su = cls.get_super_classes()
                        if su:
                            return [Instance(su[0])]
                return []

        if self.base.isinstance(Class):
            # There maybe executions of executions.
            stmts = [Instance(self.base, self.var_args)]
        elif isinstance(self.base, Generator):
            return self.base.iter_content()
        else:
            # Don't do this with exceptions, as usual, because some deeper
            # exceptions could be catched - and I wouldn't know what happened.
            try:
                self.base.returns
            except (AttributeError, DecoratorNotFound):
                if hasattr(self.base, 'execute_subscope_by_name'):
                    try:
                        stmts = self.base.execute_subscope_by_name('__call__',
                                                                self.var_args)
                    except KeyError:
                        debug.warning("no __call__ func available", self.base)
                else:
                    debug.warning("no execution possible", self.base)
            else:
                stmts = self._get_function_returns(evaluate_generator)

        debug.dbg('exec result: %s in %s' % (stmts, self))

        return imports.strip_imports(stmts)

    def _get_function_returns(self, evaluate_generator):
        """ A normal Function execution """
        # Feed the listeners, with the params.
        for listener in self.base.listeners:
            listener.execute(self.get_params())
        func = self.base.get_decorated_func()
        if func.is_generator and not evaluate_generator:
            return [Generator(func, self.var_args)]
        else:
            stmts = docstrings.find_return_types(func)
            for r in self.returns:
                if r is not None:
                    stmts += evaluate.follow_statement(r)
            return stmts

    @cache.memoize_default(default=[])
    def get_params(self):
        """
        This returns the params for an Execution/Instance and is injected as a
        'hack' into the pr.Function class.
        This needs to be here, because Instance can have __init__ functions,
        which act the same way as normal functions.
        """
        def gen_param_name_copy(param, keys=[], values=[], array_type=None):
            """
            Create a param with the original scope (of varargs) as parent.
            """
            # TODO remove array and param and just put the values of the \
            # statement into the values of the param - it's as simple as that.
            if isinstance(self.var_args, pr.Array):
                parent = self.var_args.parent
                start_pos = self.var_args.start_pos
            else:
                parent = self.base
                start_pos = None

            new_param = copy.copy(param)
            new_param.is_generated = True
            if parent is not None:
                new_param.parent = parent

            # create an Array (-> needed for *args/**kwargs tuples/dicts)
            arr = pr.Array(self.module, start_pos, array_type, parent)
            arr.values = values
            key_stmts = []
            for key in keys:
                stmt = pr.Statement(self.module, 'XXX code', [], [], [], [],
                                    start_pos, None)
                stmt._commands = [key]
                key_stmts.append(stmt)
            arr.keys = key_stmts
            arr.type = array_type

            new_param._commands = [arr]

            name = copy.copy(param.get_name())
            name.parent = new_param
            return name

        result = []
        start_offset = 0
        if isinstance(self.base, InstanceElement):
            # Care for self -> just exclude it and add the instance
            start_offset = 1
            self_name = copy.copy(self.base.params[0].get_name())
            self_name.parent = self.base.instance
            result.append(self_name)

        param_dict = {}
        for param in self.base.params:
            param_dict[str(param.get_name())] = param
        # There may be calls, which don't fit all the params, this just ignores
        # it.
        var_arg_iterator = self.get_var_args_iterator()

        non_matching_keys = []
        keys_used = set()
        keys_only = False
        for param in self.base.params[start_offset:]:
            # The value and key can both be null. There, the defaults apply.
            # args / kwargs will just be empty arrays / dicts, respectively.
            # Wrong value count is just ignored. If you try to test cases that
            # are not allowed in Python, Jedi will maybe not show any
            # completions.
            key, value = next(var_arg_iterator, (None, None))
            while key:
                keys_only = True
                try:
                    key_param = param_dict[str(key)]
                except KeyError:
                    non_matching_keys.append((key, value))
                else:
                    keys_used.add(str(key))
                    result.append(gen_param_name_copy(key_param,
                                                        values=[value]))
                key, value = next(var_arg_iterator, (None, None))

            commands = param.get_commands()
            keys = []
            values = []
            array_type = None
            ignore_creation = False
            if commands[0] == '*':
                # *args param
                array_type = pr.Array.TUPLE
                if value:
                    values.append(value)
                for key, value in var_arg_iterator:
                    # Iterate until a key argument is found.
                    if key:
                        var_arg_iterator.push_back((key, value))
                        break
                    values.append(value)
            elif commands[0] == '**':
                # **kwargs param
                array_type = pr.Array.DICT
                if non_matching_keys:
                    keys, values = zip(*non_matching_keys)
            elif not keys_only:
                # normal param
                if value is not None:
                    values = [value]
                else:
                    if param.assignment_details:
                        # No value: return the default values.
                        ignore_creation = True
                        result.append(param.get_name())
                        param.is_generated=True
                    else:
                        # If there is no assignment detail, that means there is
                        # no assignment, just the result. Therefore nothing has
                        # to be returned.
                        values = []

            # Just ignore all the params that are without a key, after one
            # keyword argument was set.
            if not ignore_creation and (not keys_only or commands[0] == '**'):
                keys_used.add(str(key))
                result.append(gen_param_name_copy(param, keys=keys,
                                        values=values, array_type=array_type))

        if keys_only:
            # sometimes param arguments are not completely written (which would
            # create an Exception, but we have to handle that).
            for k in set(param_dict) - keys_used:
                result.append(gen_param_name_copy(param_dict[k]))
        return result

    def get_var_args_iterator(self):
        """
        Yields a key/value pair, the key is None, if its not a named arg.
        """
        def iterate():
            # `var_args` is typically an Array, and not a list.
            for stmt in self.var_args:
                if not isinstance(stmt, pr.Statement):
                    yield None, stmt
                # *args
                elif stmt.get_commands()[0] == '*':
                    arrays = evaluate.follow_call_list(stmt.get_commands()[1:])
                    # *args must be some sort of an array, otherwise -> ignore
                    for array in arrays:
                        for field_stmt in array:  # yield from plz!
                            yield None, field_stmt
                # **kwargs
                elif stmt.get_commands()[0] == '**':
                    arrays = evaluate.follow_call_list(stmt.get_commands()[1:])
                    for array in arrays:
                        for key_stmt, value_stmt in array.items():
                            # first index, is the key if syntactically correct
                            call = key_stmt.get_commands()[0]
                            if isinstance(call, pr.Name):
                                yield call, value_stmt
                            elif type(call) == pr.Call:
                                yield call.name, value_stmt
                            else:
                                # `pr`.[Call|Function|Class] lookup.
                                # TODO remove?
                                yield key_stmt[0].name, value_stmt
                # Normal arguments (including key arguments).
                else:
                    if stmt.assignment_details:
                        key_arr, op = stmt.assignment_details[0]
                        # named parameter
                        if key_arr and isinstance(key_arr[0], pr.Call):
                            yield key_arr[0].name, stmt
                    else:
                        yield None, stmt

        return iter(common.PushBackIterator(iterate()))

    def get_set_vars(self):
        return self.get_defined_names()

    def get_defined_names(self):
        """
        Call the default method with the own instance (self implements all
        the necessary functions). Add also the params.
        """
        return self.get_params() + pr.Scope.get_set_vars(self)

    def copy_properties(self, prop):
        """
        Literally copies a property of a Function. Copying is very expensive,
        because it is something like `copy.deepcopy`. However, these copied
        objects can be used for the executions, as if they were in the
        execution.
        """
        try:
            # Copy all these lists into this local function.
            attr = getattr(self.base, prop)
            objects = []
            for element in attr:
                if element is None:
                    copied = element
                else:
                    copied = helpers.fast_parent_copy(element)
                    copied.parent = self._scope_copy(copied.parent)
                    if isinstance(copied, pr.Function):
                        copied = Function(copied)
                objects.append(copied)
            return objects
        except AttributeError:
            raise common.MultiLevelAttributeError(sys.exc_info())

    def __getattr__(self, name):
        if name not in ['start_pos', 'end_pos', 'imports', 'module']:
            raise AttributeError('Tried to access %s: %s. Why?' % (name, self))
        return getattr(self.base, name)

    @cache.memoize_default()
    def _scope_copy(self, scope):
        try:
            """ Copies a scope (e.g. if) in an execution """
            # TODO method uses different scopes than the subscopes property.

            # just check the start_pos, sometimes it's difficult with closures
            # to compare the scopes directly.
            if scope.start_pos == self.start_pos:
                return self
            else:
                copied = helpers.fast_parent_copy(scope)
                copied.parent = self._scope_copy(copied.parent)
                return copied
        except AttributeError:
            raise common.MultiLevelAttributeError(sys.exc_info())

    @property
    @cache.memoize_default()
    def returns(self):
        return self.copy_properties('returns')

    @property
    @cache.memoize_default()
    def asserts(self):
        return self.copy_properties('asserts')

    @property
    @cache.memoize_default()
    def statements(self):
        return self.copy_properties('statements')

    @property
    @cache.memoize_default()
    def subscopes(self):
        return self.copy_properties('subscopes')

    def get_statement_for_position(self, pos):
        return pr.Scope.get_statement_for_position(self, pos)

    def __repr__(self):
        return "<%s of %s>" % \
                (type(self).__name__, self.base)


class Generator(use_metaclass(cache.CachedMetaClass, pr.Base)):
    """ Cares for `yield` statements. """
    def __init__(self, func, var_args):
        super(Generator, self).__init__()
        self.func = func
        self.var_args = var_args

    def get_defined_names(self):
        """
        Returns a list of names that define a generator, which can return the
        content of a generator.
        """
        names = []
        none_pos = (0, 0)
        executes_generator = ('__next__', 'send')
        for n in ('close', 'throw') + executes_generator:
            name = pr.Name(builtin.Builtin.scope, [(n, none_pos)],
                                none_pos, none_pos)
            if n in executes_generator:
                name.parent = self
            names.append(name)
        debug.dbg('generator names', names)
        return names

    def iter_content(self):
        """ returns the content of __iter__ """
        return Execution(self.func, self.var_args).get_return_types(True)

    def get_index_types(self, index=None):
        debug.warning('Tried to get array access on a generator', self)
        return []

    @property
    def parent(self):
        return self.func.parent

    def __repr__(self):
        return "<%s of %s>" % (type(self).__name__, self.func)


class Array(use_metaclass(cache.CachedMetaClass, pr.Base)):
    """
    Used as a mirror to pr.Array, if needed. It defines some getter
    methods which are important in this module.
    """
    def __init__(self, array):
        self._array = array

    def get_index_types(self, index_arr=None):
        """ Get the types of a specific index or all, if not given """
        if index_arr is not None:
            if index_arr and [x for x in index_arr if ':' in x.get_commands()]:
                # array slicing
                return [self]

            index_possibilities = self._follow_values(index_arr)
            if len(index_possibilities) == 1:
                # This is indexing only one element, with a fixed index number,
                # otherwise it just ignores the index (e.g. [1+1]).
                index = index_possibilities[0]
                if isinstance(index, Instance) \
                            and str(index.name) in ['int', 'str'] \
                            and len(index.var_args) == 1:
                    try:
                        return self.get_exact_index_types(index.var_args[0])
                    except (KeyError, IndexError):
                        pass

        result = list(self._follow_values(self._array.values))
        result += dynamic.check_array_additions(self)
        return set(result)

    def get_exact_index_types(self, mixed_index):
        """ Here the index is an int/str. Raises IndexError/KeyError """
        index = mixed_index
        if self.type == pr.Array.DICT:
            index = None
            for i, key_statement in enumerate(self._array.keys):
                # Because we only want the key to be a string.
                key_commands = key_statement.get_commands()
                if len(key_commands) == 1:
                    key = key_commands[0]
                    key.get_code()
                    try:
                        str_key = key.get_code()
                    except AttributeError:
                        str_key = None
                    if mixed_index == str_key:
                        index = i
                        break
            if index is None:
                raise KeyError('No key found in dictionary')

        # Can raise an IndexError
        values = [self._array.values[index]]
        return self._follow_values(values)

    def _follow_values(self, values):
        """ helper function for the index getters """
        return list(itertools.chain.from_iterable(evaluate.follow_statement(v)
                                                  for v in values))

    def get_defined_names(self):
        """
        This method generates all `ArrayMethod` for one pr.Array.
        It returns e.g. for a list: append, pop, ...
        """
        # `array.type` is a string with the type, e.g. 'list'.
        scope = evaluate.find_name(builtin.Builtin.scope, self._array.type)[0]
        scope = Instance(scope)
        names = scope.get_defined_names()
        return [ArrayMethod(n) for n in names]

    @property
    def parent(self):
        return builtin.Builtin.scope

    def get_parent_until(self):
        return builtin.Builtin.scope

    def __getattr__(self, name):
        if name not in ['type', 'start_pos', 'get_only_subelement', 'parent',
                        'get_parent_until', 'items']:
            raise AttributeError('Strange access on %s: %s.' % (self, name))
        return getattr(self._array, name)

    def __getitem__(self):
        return self._array.__getitem__()

    def __iter__(self):
        return self._array.__iter__()

    def __len__(self):
        return self._array.__len__()

    def __repr__(self):
        return "<e%s of %s>" % (type(self).__name__, self._array)


class ArrayMethod(object):
    """
    A name, e.g. `list.append`, it is used to access the original array
    methods.
    """
    def __init__(self, name):
        super(ArrayMethod, self).__init__()
        self.name = name

    def __getattr__(self, name):
        # Set access privileges:
        if name not in ['parent', 'names', 'start_pos', 'end_pos', 'get_code']:
            raise AttributeError('Strange accesson %s: %s.' % (self, name))
        return getattr(self.name, name)

    def get_parent_until(self):
        return builtin.Builtin.scope

    def __repr__(self):
        return "<%s of %s>" % (type(self).__name__, self.name)
