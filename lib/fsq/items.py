# fsq -- a python library for manipulating and introspecting FSQ queues
# @author: Matthew Story <matt.story@axialmarket.com>
#
# fsq/items.py -- provides items classes for fsq: FSQItem, FSQEnqueueItem
#
#     fsq is all unicode internally, if you pass in strings,
#     they will be explicitly coerced to unicode.
#
# This software is for POSIX compliant systems only.
import errno
import datetime

from . import FSQ_LOCK, FSQ_FAIL_PERM, FSQ_TTL, FSQ_MAX_TRIES, FSQ_TIMEFMT,\
              path as fsq_path, deconstruct, FSQMalformedEntryError,\
              FSQTimeFmtError, FSQWorkItemError, fail, success, done,\
              fail_tmp, fail_perm
from .internal import rationalize_file, wrap_io_os_err, check_ttl_max_tries

class FSQEnqueueItem(object):
    '''Stub for Streamable Enqueue object, e.g.

        foo = FSQEnqueueItem('foo', 'bar', 'baz', 'bang')
        try:
            for i in ['a', 'b', 'c']:
                foo.item.write(i)
            foo.commit()
        except Exception, e:
            foo.abort()
        finally:
            del foo
    '''
    pass

class FSQWorkItem(object):
    '''An FSQWorkItem object.  FSQWorkItem stores an open and potentially
       exclusive-locked file to a work file as the attribute self.item, opened
       in read-only mode.

       FSQWorkItem is intended to a minimalist object, capable of reverse
       engineering to a C struct.  The C struct will support all attributes,
       but the methods will not be available, they will be available as
       include level functions taking a *WorkItem struct as their first
       argument.

       BEWARE: If you choose not to lock, the item you are working on may be
       worked on by others, and may be moved (on failure or success) out from
       underneath you.  Should you send lock=False, it is assumed you are
       guarenteeing concurrency of 1 on the queue through some other
       mechanism.'''
    ####### MAGICAL METHODS AND ATTRS #######
    def __init__(self, trg_queue, item_id, max_tries=None, ttl=None,
                 lock=None):
        '''Construct an FSQWorkItem object from an item_id (file-name), and
           queue-name.  The lock kwarg will override the default locking
           preference (taken from environment).'''

        self.id = item_id
        self.queue = trg_queue
        self.max_tries = FSQ_MAX_TRIES if max_tries is None else max_tries
        self.ttl = FSQ_TTL if ttl is None else ttl
        self.lock = FSQ_LOCK if lock is None else lock

        # open file immediately
        try:
            self.item = rationalize_file(fsq_path.item(trg_queue, item_id),
                                         lock=self.lock)
        except (OSError, IOError, ), e:
            if e.errno == errno.ENOENT:
                raise FSQWorkItemError(e.errno, u'no such item in queue {0}:'\
                                       u' {1}'.format(trg_queue, item_id))
            raise FSQWorkItemError(e.errno, wrap_io_os_err(e))
        try:
            self.delimiter, arguments = deconstruct(item_id)
            try:
                # construct datetime.datetime from enqueued_at
                self.enqueued_at = datetime.datetime.strptime(arguments[0],
                                                              FSQ_TIMEFMT)
                self.entropy = arguments[1]
                self.pid = arguments[2]
                self.hostname = arguments[3]
                self.tries = arguments[4]
                self.arguments = tuple(arguments[5:])
            except IndexError, e:
                raise FSQMalformedEntryError(fail_perm, u'needed at least 4'\
                                             u' arguments to unpack, got:'\
                                             u' {0}'.format(len(arguments)))
            except ValueError, e:
                raise FSQTimeFmtError(fail_perm, u'invalid date string for'\
                                      u' strptime fmt {0}:'\
                                      u' {1}'.format(FSQ_TIMEFMT,
                                                     arguments[0]))
            check_ttl_max_tries(self.tries, self.enqueued_at, self.max_tries,
                                self.ttl, FSQ_FAIL_PERM)
        except Exception, e:
            try:
                # unhandled exceptions are perm failures
                fail_type = getattr(e, 'errno', FSQ_FAIL_PERM)
                self.fail(fail_type)
            finally:
                self.item.close()
            raise e

    def __del__(self):
        '''Always close the file when the ref count drops to 0'''
        if hasattr(self, 'item'):
            self.item.close()

    ####### EXPOSED METHODS AND ATTRS #######
    def done(self, done_type=None):
        '''Complete an item, either successfully or with failure'''
        return done(self, done_type)

    def success(self):
        '''Complete an item successfully'''
        return success(self)

    def fail(self, fail_type=None):
        '''Fail this item either temporarily or permanantly.'''
        return fail(self, fail_type)

    def fail_tmp(self):
        '''Fail an item temporarily (either retry, or escalate to perm)'''
        return fail_tmp(self)

    def fail_perm(self):
        return fail_perm(self)
