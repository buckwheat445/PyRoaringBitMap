cimport croaring
from libc.stdint cimport uint32_t, uint64_t, int64_t
from libcpp cimport bool
from libcpp.vector cimport vector
from libc.stdlib cimport free, malloc

from cpython cimport array
import array

try:
    range = xrange
except NameError: # python 3
    pass

cdef AbstractBitMap create_from_ptr(croaring.roaring_bitmap_t *r):
    bm = <AbstractBitMap>AbstractBitMap.__new__(AbstractBitMap, no_init=True)
    bm._c_bitmap = r
    return bm

cdef AbstractBitMap binary_operation(AbstractBitMap left, AbstractBitMap right, (croaring.roaring_bitmap_t*)func(const croaring.roaring_bitmap_t*, const croaring.roaring_bitmap_t*)):
    cdef croaring.roaring_bitmap_t *r = func(left._c_bitmap, right._c_bitmap)
    return create_from_ptr(r)

cdef AbstractBitMap binary_or(AbstractBitMap left, AbstractBitMap right):
    return binary_operation(left, right, croaring.roaring_bitmap_or)

cdef AbstractBitMap binary_and(AbstractBitMap left, AbstractBitMap right):
    return binary_operation(left, right, croaring.roaring_bitmap_and)

cdef AbstractBitMap binary_xor(AbstractBitMap left, AbstractBitMap right):
    return binary_operation(left, right, croaring.roaring_bitmap_xor)

cdef AbstractBitMap binary_sub(AbstractBitMap left, AbstractBitMap right):
    return binary_operation(left, right, croaring.roaring_bitmap_andnot)

cdef binary_ior(AbstractBitMap left, AbstractBitMap right):
    croaring.roaring_bitmap_or_inplace(left._c_bitmap, right._c_bitmap)
    return left

cdef binary_iand(AbstractBitMap left, AbstractBitMap right):
    croaring.roaring_bitmap_and_inplace(left._c_bitmap, right._c_bitmap)
    return left

cdef binary_ixor(AbstractBitMap left, AbstractBitMap right):
    croaring.roaring_bitmap_xor_inplace(left._c_bitmap, right._c_bitmap)
    return left

cdef binary_isub(AbstractBitMap left, AbstractBitMap right):
    croaring.roaring_bitmap_andnot_inplace(left._c_bitmap, right._c_bitmap)
    return left

cdef croaring.roaring_bitmap_t *deserialize_ptr(char *buff):
    cdef croaring.roaring_bitmap_t *ptr
    ptr = croaring.roaring_bitmap_portable_deserialize(buff)
    return ptr

cdef class AbstractBitMap:
    """
    An efficient and light-weight ordered set of 32 bits integers.
    """
    cdef croaring.roaring_bitmap_t* _c_bitmap

    def __cinit__(self, values=None, copy_on_write=False, no_init=False):
        if no_init:
            assert values is None and not copy_on_write
            return
        cdef vector[uint32_t] buff_vect
        cdef unsigned[:] buff
        if values is None:
            self._c_bitmap = croaring.roaring_bitmap_create()
        elif isinstance(values, AbstractBitMap):
            self._c_bitmap = croaring.roaring_bitmap_copy((<AbstractBitMap?>values)._c_bitmap)
        elif isinstance(values, range):
            _, (start, stop, step) = values.__reduce__()
            if step < 0:
                values = range(min(values), max(values)+1, -step)
                _, (start, stop, step) = values.__reduce__()
            if start >= stop:
                self._c_bitmap = croaring.roaring_bitmap_create()
            else:
                self._c_bitmap = croaring.roaring_bitmap_from_range(start, stop, step)
        elif isinstance(values, array.array):
            size = len(values)
            if size == 0:
                self._c_bitmap = croaring.roaring_bitmap_create()
            else:
                buff = <array.array> values
                self._c_bitmap = croaring.roaring_bitmap_of_ptr(size, &buff[0])
        else:
            self._c_bitmap = croaring.roaring_bitmap_create()
            buff_vect = values
            croaring.roaring_bitmap_add_many(self._c_bitmap, len(values), &buff_vect[0])
        if not isinstance(values, AbstractBitMap):
            self._c_bitmap.copy_on_write = copy_on_write

    def __init__(self, values=None, copy_on_write=False):
        """
        Construct a AbstractBitMap object, either empry or from an iterable.

        Copy on write can be enabled with the field copy_on_write.

        >>> BitMap()
        BitMap([])
        >>> BitMap([1, 123456789, 27])
        BitMap([1, 27, 123456789])
        >>> BitMap([1, 123456789, 27], copy_on_write=True)
        BitMap([1, 27, 123456789])
        """

    @property
    def copy_on_write(self):
        """
        True if and only if the bitmap has "copy on write" optimization enabled.

        >>> BitMap(copy_on_write=False).copy_on_write
        False
        >>> BitMap(copy_on_write=True).copy_on_write
        True
        """
        return self._c_bitmap.copy_on_write

    def __dealloc__(self):
        if self._c_bitmap is not NULL:
            croaring.roaring_bitmap_free(self._c_bitmap)

    def __check_compatibility(self, AbstractBitMap other):
        if self._c_bitmap.copy_on_write != other._c_bitmap.copy_on_write:
            raise ValueError('Cannot have interactions between bitmaps with and without copy_on_write.\n')

    def __contains__(self, uint32_t value):
        return croaring.roaring_bitmap_contains(self._c_bitmap, value)

    def __bool__(self):
        return not croaring.roaring_bitmap_is_empty(self._c_bitmap)

    def __len__(self):
        return croaring.roaring_bitmap_get_cardinality(self._c_bitmap)

    def __richcmp__(self, other, int op):
        self.__check_compatibility(other)
        if op == 0: # <
            return croaring.roaring_bitmap_is_strict_subset((<AbstractBitMap?>self)._c_bitmap, (<AbstractBitMap?>other)._c_bitmap)
        elif op == 1: # <=
            return croaring.roaring_bitmap_is_subset((<AbstractBitMap?>self)._c_bitmap, (<AbstractBitMap?>other)._c_bitmap)
        elif op == 2: # ==
            return croaring.roaring_bitmap_equals((<AbstractBitMap?>self)._c_bitmap, (<AbstractBitMap?>other)._c_bitmap)
        elif op == 3: # !=
            return not (self == other)
        elif op == 4: # >
            return croaring.roaring_bitmap_is_strict_subset((<AbstractBitMap?>other)._c_bitmap, (<AbstractBitMap?>self)._c_bitmap)
        else:         # >=
            assert op == 5
            return croaring.roaring_bitmap_is_subset((<AbstractBitMap?>other)._c_bitmap, (<AbstractBitMap?>self)._c_bitmap)

    def __iter__(self):
        cdef croaring.roaring_uint32_iterator_t *iterator = croaring.roaring_create_iterator(self._c_bitmap)
        try:
            while iterator.has_value:
                yield iterator.current_value
                croaring.roaring_advance_uint32_iterator(iterator)
        finally:
            croaring.roaring_free_uint32_iterator(iterator)

    def __repr__(self):
        return str(self)

    def __str__(self):
        values = ', '.join([str(n) for n in self])
        return '%s([%s])' % (self.__class__.__name__, values)

    def flip(self, uint64_t start, uint64_t end):
        """
        Compute the negation of the bitmap within the specified interval.

        Areas outside the range are passed unchanged.

        >>> bm = BitMap([3, 12])
        >>> bm.flip(10, 15)
        BitMap([3, 10, 11, 13, 14])
        """
        return create_from_ptr(croaring.roaring_bitmap_flip(self._c_bitmap, start, end))

    @classmethod
    def union(cls, *bitmaps):
        """
        Return the union of the bitmaps.

        >>> BitMap.union(BitMap([3, 12]), BitMap([5]), BitMap([0, 10, 12]))
        BitMap([0, 3, 5, 10, 12])
        """
        size = len(bitmaps)
        cdef croaring.roaring_bitmap_t *result
        cdef AbstractBitMap bm
        cdef vector[const croaring.roaring_bitmap_t*] buff
        if size <= 1:
            return cls(*bitmaps)
        elif size == 2:
            return bitmaps[0] | bitmaps[1]
        else:
            for bm in bitmaps:
                bitmaps[0].__check_compatibility(bm)
                buff.push_back(bm._c_bitmap)
            result = croaring.roaring_bitmap_or_many(size, &buff[0])
            return create_from_ptr(result)

    @classmethod
    def intersection(cls, *bitmaps): # FIXME could be more efficient
        """
        Return the intersection of the bitmaps.

        >>> BitMap.intersection(BitMap(range(0, 15)), BitMap(range(5, 20)), BitMap(range(10, 25)))
        BitMap([10, 11, 12, 13, 14])
        """
        size = len(bitmaps)
        cdef AbstractBitMap result, bm
        if size <= 1:
            return cls(*bitmaps)
        else:
            result = AbstractBitMap(bitmaps[0])
            for bm in bitmaps[1:]:
                result &= bm
            return result

    def __or__(self, other):
        self.__check_compatibility(other)
        return binary_or(self, <AbstractBitMap?>other)

    def __ior__(self, other):
        self.__check_compatibility(other)
        return binary_ior(self, <AbstractBitMap?>other)

    def __and__(self, other):
        self.__check_compatibility(other)
        return binary_and(self, <AbstractBitMap?>other)

    def __iand__(self, other):
        self.__check_compatibility(other)
        return binary_iand(self, <AbstractBitMap?>other)

    def __xor__(self, other):
        self.__check_compatibility(other)
        return binary_xor(self, <AbstractBitMap?>other)

    def __ixor__(self, other):
        self.__check_compatibility(other)
        return binary_ixor(self, <AbstractBitMap?>other)

    def __sub__(self, other):
        self.__check_compatibility(other)
        return binary_sub(self, <AbstractBitMap?>other)

    def __isub__(self, other):
        self.__check_compatibility(other)
        return binary_isub(self, <AbstractBitMap?>other)

    def union_cardinality(self, AbstractBitMap other):
        """
        Return the number of elements in the union of the two bitmaps.

        It is equivalent to len(self | other), but faster.

        >>> BitMap([3, 12]).union_cardinality(AbstractBitMap([3, 5, 8]))
        4
        """
        self.__check_compatibility(other)
        return croaring.roaring_bitmap_or_cardinality(self._c_bitmap, other._c_bitmap)

    def intersection_cardinality(self, AbstractBitMap other):
        """
        Return the number of elements in the intersection of the two bitmaps.

        It is equivalent to len(self & other), but faster.

        >>> BitMap([3, 12]).intersection_cardinality(BitMap([3, 5, 8]))
        1
        """
        self.__check_compatibility(other)
        return croaring.roaring_bitmap_and_cardinality(self._c_bitmap, other._c_bitmap)

    def difference_cardinality(self, AbstractBitMap other):
        """
        Return the number of elements in the difference of the two bitmaps.

        It is equivalent to len(self - other), but faster.

        >>> BitMap([3, 12]).difference_cardinality(BitMap([3, 5, 8]))
        1
        """
        self.__check_compatibility(other)
        return croaring.roaring_bitmap_andnot_cardinality(self._c_bitmap, other._c_bitmap)

    def symmetric_difference_cardinality(self, AbstractBitMap other):
        """
        Return the number of elements in the symmetric difference of the two bitmaps.

        It is equivalent to len(self ^ other), but faster.

        >>> BitMap([3, 12]).symmetric_difference_cardinality(BitMap([3, 5, 8]))
        3
        """
        self.__check_compatibility(other)
        return croaring.roaring_bitmap_xor_cardinality(self._c_bitmap, other._c_bitmap)

    def intersect(self, AbstractBitMap other):
        """
        Return True if and only if the two bitmaps have elements in common.

        It is equivalent to len(self & other) > 0, but faster.

        >>> BitMap([3, 12]).intersect(BitMap([3, 18]))
        True
        >>> BitMap([3, 12]).intersect(BitMap([5, 18]))
        False
        """
        self.__check_compatibility(other)
        return croaring.roaring_bitmap_intersect(self._c_bitmap, other._c_bitmap)

    def jaccard_index(self, AbstractBitMap other):
        """
        Compute the Jaccard index of the two bitmaps.

        It is equivalent to len(self&other)/len(self|other), but faster.
        See https://en.wikipedia.org/wiki/Jaccard_index
        
        >>> BitMap([3, 10, 12]).jaccard_index(BitMap([3, 18]))
        0.25
        """
        self.__check_compatibility(other)
        return croaring.roaring_bitmap_jaccard_index(self._c_bitmap, other._c_bitmap)

    def get_statistics(self):
        """
        Return relevant metrics about the bitmap.

        >>> stats = BitMap(range(18, 66000, 2)).get_statistics()
        >>> stats['cardinality']
        32991
        >>> stats['max_value']
        65998
        >>> stats['min_value']
        18
        >>> stats['n_array_containers']
        1
        >>> stats['n_bitset_containers']
        1
        >>> stats['n_bytes_array_containers']
        464
        >>> stats['n_bytes_bitset_containers']
        8192
        >>> stats['n_bytes_run_containers']
        0
        >>> stats['n_containers']
        2
        >>> stats['n_run_containers']
        0
        >>> stats['n_values_array_containers']
        232
        >>> stats['n_values_bitset_containers']
        32759
        >>> stats['n_values_run_containers']
        0
        >>> stats['sum_value'] 
        1088966928
        """
        cdef croaring.roaring_statistics_t stat
        croaring.roaring_bitmap_statistics(self._c_bitmap, &stat)
        return stat

    def min(self):
        """
        Return the minimum element of the bitmap.

        It is equivalent to min(self), but faster.

        >>> BitMap([3, 12]).min()
        3
        """
        if len(self) == 0:
            raise ValueError('Empty roaring bitmap, there is no minimum.')
        else:
            return croaring.roaring_bitmap_minimum(self._c_bitmap)

    def max(self):
        """
        Return the maximum element of the bitmap.

        It is equivalent to max(self), but faster.

        >>> BitMap([3, 12]).max()
        12
        """
        if len(self) == 0:
            raise ValueError('Empty roaring bitmap, there is no maximum.')
        else:
            return croaring.roaring_bitmap_maximum(self._c_bitmap)

    def rank(self, uint32_t value):
        """
        Return the rank of the element in the bitmap.

        >>> BitMap([3, 12]).rank(12)
        2
        """
        return croaring.roaring_bitmap_rank(self._c_bitmap, value)

    cdef int64_t _shift_index(self, int64_t index) except -1:
        cdef int64_t size = len(self)
        if index >= size or index < -size:
            raise IndexError('Index out of bound')
        if index < 0:
            return (index + size)
        else:
            return index

    cdef uint32_t _get_elt(self, int64_t index) except? 0:
        cdef uint64_t s_index = self._shift_index(index)
        cdef uint32_t elt
        cdef bool valid = croaring.roaring_bitmap_select(self._c_bitmap, s_index, &elt)
        if not valid:
            raise ValueError('Invalid rank')
        return elt

    cdef _get_slice(self, sl):
        start, stop, step = sl.indices(len(self))
        sign = 1 if step > 0 else -1
        if (sign > 0 and start >= stop) or (sign < 0 and start <= stop):
            return self.__class__()
        if abs(step) == 1:
            first_elt = self._get_elt(start)
            last_elt  = self._get_elt(stop-sign)
            values = range(first_elt, last_elt+sign, step)
            result = self.__class__(values, copy_on_write=self.copy_on_write)
            result &= self
            return result
        else:
            return self.__class__(self.to_array()[sl]) # could be more efficient...

    def __getitem__(self, value):
        if isinstance(value, int):
            return self._get_elt(value)
        elif isinstance(value, slice):
            return self._get_slice(value)
        else:
            return TypeError('Indices must be integers or slices, not %s' % type(value))

    def serialize(self):
        """
        Return the serialization of the bitmap. See AbstractBitMap.deserialize for the reverse operation.

        >>> BitMap.deserialize(BitMap([3, 12]).serialize())
        BitMap([3, 12])
        """
        cdef size_t size = croaring.roaring_bitmap_portable_size_in_bytes(self._c_bitmap)
        cdef char *buff = <char*>malloc(size)
        cdef real_size = croaring.roaring_bitmap_portable_serialize(self._c_bitmap, buff)
        result = buff[:size]
        free(buff)
        return result


    @classmethod
    def deserialize(cls, char *buff):
        """
        Generate a bitmap from the given serialization. See AbstractBitMap.serialize for the reverse operation.

        >>> BitMap.deserialize(BitMap([3, 12]).serialize())
        BitMap([3, 12])
        """
        return create_from_ptr(deserialize_ptr(buff))

    def __getstate__(self):
        return self.serialize()

    def __setstate__(self, state):
        try:                                            # compatibility between Python2 and Python3 (see #27)
            self._c_bitmap = deserialize_ptr(state)
        except TypeError:
            self._c_bitmap = deserialize_ptr(state.encode())

    def to_array(self):
        """
        Return an array.array containing the elements of the bitmap, in increasing order.

        It is equivalent to array.array('I', self), but more efficient.

        >>> BitMap([3, 12]).to_array()
        array('I', [3, 12])
        """
        cdef int64_t size = len(self)
        if size == 0:
            return array.array('I', [])
        cdef array.array result = array.array('I')
        array.resize(result, size)
        cdef unsigned[:] buff = result
        croaring.roaring_bitmap_to_uint32_array(self._c_bitmap, &buff[0])
        return result
