import sys, os, errno, glob
import vars
from helpers import unlink, debug2, mkdirp


def init():
    # FIXME: just wiping out all the locks is kind of cheating.  But we
    # only do this from the toplevel redo process, so unless the user
    # deliberately starts more than one redo on the same repository, it's
    # sort of ok.
    mkdirp('%s/.redo' % vars.BASE)
    for f in glob.glob('%s/.redo/lock*' % vars.BASE):
        os.unlink(f)
    for f in glob.glob('%s/.redo/mark^*' % vars.BASE):
        os.unlink(f)
    for f in glob.glob('%s/.redo/built^*' % vars.BASE):
        os.unlink(f)


def relpath(t, base):
    t = os.path.normpath(os.path.join(os.getcwd(), t))
    tparts = t.split('/')
    bparts = base.split('/')
    for tp,bp in zip(tparts,bparts):
        if tp != bp:
            break
        tparts.pop(0)
        bparts.pop(0)
    while bparts:
        tparts.insert(0, '..')
        bparts.pop(0)
    return '/'.join(tparts)


def _sname(typ, t):
    # FIXME: t.replace(...) is non-reversible and non-unique here!
    tnew = relpath(t, vars.BASE)
    v = vars.BASE + ('/.redo/%s^%s' % (typ, tnew.replace('/', '^')))
    debug2('sname: (%r) %r -> %r\n' % (os.getcwd(), t, tnew))
    return v


def add_dep(t, mode, dep):
    debug2('add-dep(%r)\n' % t)
    open(_sname('dep', t), 'a').write('%s %s\n'
                                      % (mode, relpath(dep, vars.BASE)))


def deps(t):
    for line in open(_sname('dep', t)).readlines():
        assert(line[0] in ('c','m'))
        assert(line[1] == ' ')
        assert(line[-1] == '\n')
        mode = line[0]
        name = line[2:-1]
        yield mode,name


def _stampname(t):
    return _sname('stamp', t)
    

def stamp(t):
    built(t)
    mark(t)
    stampfile = _stampname(t)
    newstampfile = _sname('stamp' + str(os.getpid()), t)
    depfile = _sname('dep', t)
    if not os.path.exists(vars.BASE + '/.redo'):
        # .redo might not exist in a 'make clean' target
        return
    open(newstampfile, 'w').close()
    try:
        mtime = os.stat(t).st_mtime
    except OSError:
        mtime = 0
    os.utime(newstampfile, (mtime, mtime))
    os.rename(newstampfile, stampfile)
    open(depfile, 'a').close()


def unstamp(t):
    unlink(_stampname(t))


def stamped(t):
    try:
        stamptime = os.stat(_stampname(t)).st_mtime
    except OSError, e:
        if e.errno == errno.ENOENT:
            return None
        else:
            raise
    return stamptime


def built(t):
    try:
        open(_sname('built', t), 'w').close()
    except IOError, e:
        if e.errno == errno.ENOENT:
            pass  # may happen if someone deletes our .redo dir
        else:
            raise


_builts = {}
def isbuilt(t):
    if _builts.get(t):
        return True
    if os.path.exists(_sname('built', t)):
        _builts[t] = True
        return True


def mark(t):
    try:
        open(_sname('mark', t), 'w').close()
    except IOError, e:
        if e.errno == errno.ENOENT:
            pass  # may happen if someone deletes our .redo dir
        else:
            raise


_marks = {}
def ismarked(t):
    if _marks.get(t):
        return True
    if os.path.exists(_sname('mark', t)):
        _marks[t] = True
        return True


def is_generated(t):
    return os.path.exists(_sname('gen', t))


def start(t):
    unstamp(t)
    open(_sname('dep', t), 'w').close()
    open(_sname('gen', t), 'w').close()  # it's definitely a generated file


class Lock:
    def __init__(self, t):
        self.owned = False
        self.lockname = _sname('lock', t)
        self.tmpname = _sname('lock%d' % os.getpid(), t)

    def __del__(self):
        if self.owned:
            self.unlock()

    def trylock(self):
        try:
            os.mkfifo(self.lockname, 0600)
            self.owned = True
        except OSError, e:
            if e.errno == errno.EEXIST:
                pass
            else:
                raise

    def waitlock(self):
        while not self.owned:
            self.wait()
            self.trylock()
        assert(self.owned)
            
    def unlock(self):
        if not self.owned:
            raise Exception("can't unlock %r - we don't own it" 
                            % self.lockname)
        # make sure no readers can connect
        try:
            os.rename(self.lockname, self.tmpname)
        except OSError, e:
            if e.errno == errno.ENOENT: # 'make clean' might do this
                self.owned = False
                return
        try:
            # ping any connected readers
            os.close(os.open(self.tmpname, os.O_WRONLY|os.O_NONBLOCK))
        except OSError, e:
            if e.errno == errno.ENXIO: # no readers open; that's ok
                pass
            else:
                raise
        os.unlink(self.tmpname)
        self.owned = False

    def wait(self):
        if self.owned:
            raise Exception("can't wait on %r - we own it" % self.lockname)
        try:
            # open() will finish only when a writer exists and does close()
            os.close(os.open(self.lockname, os.O_RDONLY))
        except OSError, e:
            if e.errno == errno.ENOENT:
                pass  # it's not even unlocked or was unlocked earlier
            else:
                raise
