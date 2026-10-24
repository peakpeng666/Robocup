"""Linux exclusively-created IPC backend; UNEXECUTED until isolation is approved.
No attach-existing path, permission repair, sudo, global cleanup, or peer launch.
Import is inert. Instantiate only inside the separately verified isolation scope.
"""
import ctypes
import errno
from dataclasses import dataclass


@dataclass
class Memory:
    identifier: int
    address: int
    size: int
    live: bool = True
    removed: bool = False


@dataclass
class Semaphore:
    name: bytes
    pointer: int
    live: bool = True
    unlinked: bool = False


class LinuxIpc:
    def __init__(self):
        self.lib = ctypes.CDLL(None, use_errno=True)
        self.lib.shmget.argtypes=[ctypes.c_int,ctypes.c_size_t,ctypes.c_int]
        self.lib.shmget.restype=ctypes.c_int
        self.lib.shmat.argtypes=[ctypes.c_int,ctypes.c_void_p,ctypes.c_int]
        self.lib.shmat.restype=ctypes.c_void_p
        self.lib.shmdt.argtypes=[ctypes.c_void_p]
        self.lib.shmdt.restype=ctypes.c_int
        self.lib.shmctl.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_void_p]
        self.lib.shmctl.restype=ctypes.c_int
        self.lib.sem_open.argtypes=[ctypes.c_char_p,ctypes.c_int,ctypes.c_uint,ctypes.c_uint]
        self.lib.sem_open.restype=ctypes.c_void_p
        for name in ('sem_post','sem_trywait','sem_close'):
            getattr(self.lib,name).argtypes=[ctypes.c_void_p]
            getattr(self.lib,name).restype=ctypes.c_int
        self.lib.sem_unlink.argtypes=[ctypes.c_char_p]
        self.lib.sem_unlink.restype=ctypes.c_int
        self.memories={}
        self.semaphores={}

    @staticmethod
    def _error(operation):
        code=ctypes.get_errno()
        return OSError(code, operation+' failed; no attach/repair/retry attempted')

    def create_memory(self,key,size):
        identifier=self.lib.shmget(key,size,0o1000|0o2000|0o600) # IPC_CREAT|IPC_EXCL
        if identifier<0:raise self._error('exclusive shmget')
        address=self.lib.shmat(identifier,None,0)
        if address is None or address==ctypes.c_void_p(-1).value:
            error=self._error('shmat owned object')
            self.lib.shmctl(identifier,0,None) # only newly-created shmid
            raise error
        handle=Memory(identifier,address,size)
        self.memories[id(handle)]=handle
        ctypes.memset(address,0,size)
        return handle

    def create_semaphore(self,name):
        encoded=name.encode('ascii')
        # Linux named semaphore ABI: O_CREAT=64, O_EXCL=128. Vendor uses no slash.
        pointer=self.lib.sem_open(encoded,64|128,0o600,0)
        if pointer is None or pointer==ctypes.c_void_p(-1).value:
            raise self._error('exclusive sem_open')
        handle=Semaphore(encoded,pointer)
        self.semaphores[id(handle)]=handle
        return handle

    def _memory(self,h):
        if self.memories.get(id(h)) is not h or not h.live:raise ValueError('memory not owned/live')

    def _semaphore(self,h):
        if self.semaphores.get(id(h)) is not h or not h.live:raise ValueError('semaphore not owned/live')

    def write(self,h,data):
        self._memory(h)
        if len(data)>h.size:raise ValueError('write exceeds owned segment')
        ctypes.memmove(h.address,data,len(data))

    def read(self,h,size):
        self._memory(h)
        if not 0<=size<=h.size:raise ValueError('read exceeds owned segment')
        return ctypes.string_at(h.address,size)

    def post(self,h):
        self._semaphore(h)
        if self.lib.sem_post(h.pointer):raise self._error('sem_post')

    def try_wait(self,h):
        self._semaphore(h)
        if self.lib.sem_trywait(h.pointer)==0:return True
        if ctypes.get_errno()==errno.EAGAIN:return False
        raise self._error('sem_trywait') # EINTR propagated, no hidden retry loop

    def destroy_memory(self,h):
        self._memory(h)
        # Remove by retained shmid, never lookup/remove by possibly-colliding key.
        if not h.removed:
            if self.lib.shmctl(h.identifier,0,None):raise self._error('owned shmctl RMID')
            h.removed=True
        if self.lib.shmdt(h.address):raise self._error('owned shmdt')
        h.live=False
        del self.memories[id(h)]

    def destroy_semaphore(self,h):
        self._semaphore(h)
        # Requires peer stopped + isolated ownership; do not use in shared namespace.
        if not h.unlinked:
            if self.lib.sem_unlink(h.name):raise self._error('owned sem_unlink')
            h.unlinked=True
        if self.lib.sem_close(h.pointer):raise self._error('owned sem_close')
        h.live=False
        del self.semaphores[id(h)]
