# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""I totally stole most of this from melange, thx guys!!!"""

import datetime
import inspect
import re
import signal
import sys
import time
import urlparse
import uuid
import os
import shutil

from eventlet import event
from eventlet import greenthread
from eventlet import semaphore
from eventlet.green import subprocess
from eventlet.timeout import Timeout

from reddwarf.common import exception
from reddwarf.openstack.common import importutils
from reddwarf.openstack.common import log as logging
from reddwarf.openstack.common import processutils
from reddwarf.openstack.common import timeutils
from reddwarf.openstack.common import utils as openstack_utils
from reddwarf.openstack.common.gettextutils import _

LOG = logging.getLogger(__name__)
import_class = importutils.import_class
import_object = importutils.import_object
import_module = importutils.import_module
bool_from_string = openstack_utils.bool_from_string
execute = processutils.execute
isotime = timeutils.isotime


def create_method_args_string(*args, **kwargs):
    """Returns a string representation of args and keyword args.

    I.e. for args=1,2,3 and kwargs={'a':4, 'b':5} you'd get: "1,2,3,a=4,b=5"
    """
    # While %s turns a var into a string but in some rare cases explicit
    # repr() is less likely to raise an exception.
    arg_strs = [repr(arg) for arg in args]
    arg_strs += ['%s=%s' % (repr(key), repr(value))
                 for (key, value) in kwargs.items()]
    return ', '.join(arg_strs)


def stringify_keys(dictionary):
    if dictionary is None:
        return None
    return dict((str(key), value) for key, value in dictionary.iteritems())


def exclude(key_values, *exclude_keys):
    if key_values is None:
        return None
    return dict((key, value) for key, value in key_values.iteritems()
                if key not in exclude_keys)


def generate_uuid():
    return str(uuid.uuid4())


def utcnow():
    return datetime.datetime.utcnow()


def raise_if_process_errored(process, exception):
    try:
        err = process.stderr.read()
        if err:
            raise exception(err)
    except OSError:
        pass


def clean_out(folder):
    for root, dirs, files in os.walk(folder):
        for f in files:
            os.unlink(os.path.join(root, f))
        for d in dirs:
            shutil.rmtree(os.path.join(root, d))


class cached_property(object):
    """A decorator that converts a function into a lazy property.

    Taken from : https://github.com/nshah/python-memoize
    The function wrapped is called the first time to retrieve the result
    and than that calculated result is used the next time you access
    the value:

        class Foo(object):

            @cached_property
            def bar(self):
                # calculate something important here
                return 42

    """

    def __init__(self, func, name=None, doc=None):
        self.func = func
        self.__name__ = name or func.__name__
        self.__doc__ = doc or func.__doc__

    def __get__(self, obj, type=None):
        if obj is None:
            return self
        value = self.func(obj)
        setattr(obj, self.__name__, value)
        return value


class MethodInspector(object):

    def __init__(self, func):
        self._func = func

    @cached_property
    def required_args(self):
        return self.args[0:self.required_args_count]

    @cached_property
    def optional_args(self):
        keys = self.args[self.required_args_count: len(self.args)]
        return zip(keys, self.defaults)

    @cached_property
    def defaults(self):
        return self.argspec.defaults or ()

    @cached_property
    def required_args_count(self):
        return len(self.args) - len(self.defaults)

    @cached_property
    def args(self):
        args = self.argspec.args
        if inspect.ismethod(self._func):
            args.pop(0)
        return args

    @cached_property
    def argspec(self):
        return inspect.getargspec(self._func)

    def __str__(self):
        optionals = ["[{0}=<{0}>]".format(k) for k, v in self.optional_args]
        required = ["{0}=<{0}>".format(arg) for arg in self.required_args]
        args_str = ' '.join(required + optionals)
        return "%s %s" % (self._func.__name__, args_str)


class LoopingCallDone(Exception):
    """Exception to break out and stop a LoopingCall.

    The poll-function passed to LoopingCall can raise this exception to
    break out of the loop normally. This is somewhat analogous to
    StopIteration.

    An optional return-value can be included as the argument to the exception;
    this return-value will be returned by LoopingCall.wait()

    """

    def __init__(self, retvalue=True):
        """:param retvalue: Value that LoopingCall.wait() should return."""
        super(LoopingCallDone, self).__init__()
        self.retvalue = retvalue


class LoopingCall(object):
    """Nabbed from nova."""
    def __init__(self, f=None, *args, **kw):
        self.args = args
        self.kw = kw
        self.f = f
        self._running = False

    def start(self, interval, now=True):
        self._running = True
        done = event.Event()

        def _inner():
            if not now:
                greenthread.sleep(interval)
            try:
                while self._running:
                    self.f(*self.args, **self.kw)
                    if not self._running:
                        break
                    greenthread.sleep(interval)
            except LoopingCallDone, e:
                self.stop()
                done.send(e.retvalue)
            except Exception:
                LOG.exception(_('in looping call'))
                done.send_exception(*sys.exc_info())
                return
            else:
                done.send(True)

        self.done = done

        greenthread.spawn(_inner)
        return self.done

    def stop(self):
        self._running = False

    def wait(self):
        return self.done.wait()


def poll_until(retriever, condition=lambda value: value,
               sleep_time=1, time_out=None):
    """Retrieves object until it passes condition, then returns it.

    If time_out_limit is passed in, PollTimeOut will be raised once that
    amount of time is eclipsed.

    """
    start_time = time.time()

    def poll_and_check():
        obj = retriever()
        if condition(obj):
            raise LoopingCallDone(retvalue=obj)
        if time_out is not None and time.time() > start_time + time_out:
            raise exception.PollTimeOut
    lc = LoopingCall(f=poll_and_check).start(sleep_time, True)
    return lc.wait()


# Copied from nova.api.openstack.common in the old code.
def get_id_from_href(href):
    """Return the id or uuid portion of a url.

    Given: 'http://www.foo.com/bar/123?q=4'
    Returns: '123'

    Given: 'http://www.foo.com/bar/abc123?q=4'
    Returns: 'abc123'

    """
    return urlparse.urlsplit("%s" % href).path.split('/')[-1]


def execute_with_timeout(*args, **kwargs):
    time = kwargs.get('timeout', 30)

    def cb_timeout():
        msg = _("Time out after waiting"
                " %(time)s seconds when running proc: %(args)s"
                " %(kwargs)s") % locals()
        LOG.error(msg)
        raise exception.ProcessExecutionError(msg)

    timeout = Timeout(time)
    try:
        return execute(*args, **kwargs)
    except Timeout as t:
        if t is not timeout:
            LOG.error("Timeout reached but not from our timeout. This is bad!")
            raise
        else:
            msg = _("Time out after waiting "
                    "%(time)s seconds when running proc: %(args)s"
                    " %(kwargs)s") % locals()
            LOG.error(msg)
            raise exception.ProcessExecutionError(msg)
    finally:
        timeout.cancel()
