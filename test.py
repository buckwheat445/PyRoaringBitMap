#! /usr/bin/env python3

import unittest
import random
import functools
import os
import sys
import pickle
from hypothesis import given
import hypothesis.strategies as st
from pyroaring import BitMap

is_python2 = sys.version_info < (3, 0)

try: # Python2 compatibility
    range = xrange
except NameError:
    pass

uint18 = st.integers(min_value=0, max_value=2**18)
uint32 = st.integers(min_value=0, max_value=2**32-1)
integer = st.integers(min_value=0, max_value=2**31-1)

range_max_size = 2**18

range_big_step = uint18.flatmap(lambda n:
    st.builds(range, st.just(n),
                     st.integers(min_value=n+1, max_value=n+range_max_size),
                     st.integers(min_value=2**8, max_value=range_max_size//8)))

range_small_step = uint18.flatmap(lambda n:
    st.builds(range, st.just(n),
                     st.integers(min_value=n+1, max_value=n+range_max_size),
                     st.integers(min_value=1, max_value=2**8)))

range_power2_step = uint18.flatmap(lambda n:
     st.builds(range, st.just(n),
                      st.integers(min_value=n+1, max_value=n+range_max_size),
                      st.integers(min_value=0, max_value=8).flatmap(
                        lambda n: st.just(2**n)
                      )))

hyp_range = range_big_step | range_small_step | range_power2_step
hyp_set = st.builds(set, hyp_range) # would be great to build a true random set, but it takes too long and hypothesis does a timeout...
hyp_collection = hyp_range | hyp_set
hyp_many_collections = st.lists(hyp_collection, min_size=1, max_size=20)

class Util(unittest.TestCase):

    comparison_set = random.sample(range(2**8), 100) + random.sample(range(2**31-1), 50)

    def compare_with_set(self, bitmap, expected_set):
        self.assertEqual(len(bitmap), len(expected_set))
        self.assertEqual(bool(bitmap), bool(expected_set))
        self.assertEqual(set(bitmap), expected_set)
        self.assertEqual(sorted(list(bitmap)), sorted(list(expected_set)))
        self.assertEqual(BitMap(expected_set), bitmap)
        for value in self.comparison_set:
            if value in expected_set:
                self.assertIn(value, bitmap)
            else:
                self.assertNotIn(value, bitmap)

    @staticmethod
    def bitmap_sample(bitmap, size):
        indices = random.sample(range(len(bitmap)), size)
        return [bitmap[i] for i in indices]

class BasicTest(Util):

    @given(hyp_collection, st.booleans())
    def test_basic(self, values, cow):
        bitmap = BitMap(copy_on_write=cow)
        expected_set = set()
        self.compare_with_set(bitmap, expected_set)
        values = list(values)
        random.shuffle(values)
        size = len(values)
        for value in values[:size//2]:
            bitmap.add(value)
            expected_set.add(value)
        self.compare_with_set(bitmap, expected_set)
        for value in values[size//2:]:
            bitmap.add(value)
            expected_set.add(value)
        self.compare_with_set(bitmap, expected_set)
        for value in values[:size//2]:
            bitmap.remove(value)
            expected_set.remove(value)
        self.compare_with_set(bitmap, expected_set)
        for value in values[size//2:]:
            bitmap.remove(value)
            expected_set.remove(value)
        self.compare_with_set(bitmap, expected_set)


    @given(hyp_collection, st.booleans(), st.booleans())
    def test_bitmap_equality(self, values, cow1, cow2):
        bitmap1 = BitMap(values, copy_on_write=cow1)
        bitmap2 = BitMap(values, copy_on_write=cow2)
        self.assertEqual(bitmap1, bitmap2)

    @given(hyp_collection, hyp_collection, st.booleans(), st.booleans())
    def test_bitmap_unequality(self, values1, values2, cow1, cow2):
        st.assume(set(values1) != set(values2))
        bitmap1 = BitMap(values1, copy_on_write=cow1)
        bitmap2 = BitMap(values2, copy_on_write=cow2)
        self.assertNotEqual(bitmap1, bitmap2)

    @given(hyp_collection, st.booleans())
    def test_constructor_values(self, values, cow):
        bitmap = BitMap(values, copy_on_write=cow)
        expected_set = set(values)
        self.compare_with_set(bitmap, expected_set)

    @given(hyp_collection, uint32, st.booleans(), st.booleans())
    def test_constructor_copy(self, values, other_value, cow1, cow2):
        st.assume(other_value not in values)
        bitmap1 = BitMap(values, copy_on_write = cow1)
        bitmap2 = BitMap(bitmap1, copy_on_write = cow2) # should be robust even if cow2 != cow1
        self.assertEqual(bitmap1, bitmap2)
        bitmap1.add(other_value)
        self.assertNotEqual(bitmap1, bitmap2)

    @given(hyp_collection, hyp_collection, st.booleans())
    def test_update(self, initial_values, new_values, cow):
        bm = BitMap(initial_values, cow)
        expected = BitMap(bm)
        bm.update(new_values)
        expected |= BitMap(new_values)
        self.assertEqual(bm, expected)

    def wrong_op(self, op):
        bitmap = BitMap()
        with self.assertRaises(OverflowError):
            op(bitmap, -3)
        with self.assertRaises(OverflowError):
            op(bitmap, 2**33)
        with self.assertRaises(TypeError):
            op(bitmap, 'bla')

    def test_wrong_add(self):
        self.wrong_op(lambda bitmap, value: bitmap.add(value))

    def test_wrong_contain(self):
        self.wrong_op(lambda bitmap, value: bitmap.__contains__(value))

    def test_wrong_constructor_values(self):
        with self.assertRaises(TypeError): # this should fire a type error!
            bitmap = BitMap([3, 'bla', 3, 42])
        with self.assertRaises(ValueError):
            bitmap = BitMap(range(0, 10, 0))

class SelectRankTest(Util):

    @given(hyp_collection, st.booleans())
    def test_simple_select(self, values, cow):
        bitmap = BitMap(values, copy_on_write=cow)
        values = list(bitmap) # enforce sorted order
        for i in range(-len(values), len(values)):
            self.assertEqual(bitmap[i], values[i])

    @given(hyp_collection, uint32, st.booleans())
    def test_wrong_selection(self, values, n, cow):
        bitmap = BitMap(values, cow)
        with self.assertRaises(IndexError):
            bitmap[len(values)]
        with self.assertRaises(IndexError):
            bitmap[n + len(values)]
        with self.assertRaises(IndexError):
            bitmap[-len(values)-1]
        with self.assertRaises(IndexError):
            bitmap[-n - len(values) - 1]

    slice_arg = st.integers(min_value=-2**31, max_value=2**31-1) | st.none()
    @given(hyp_collection, slice_arg, slice_arg, slice_arg, st.booleans())
    def test_slice_select(self, values, start, stop, step, cow):
        st.assume(step != 0)
        bitmap = BitMap(values, copy_on_write=cow)
        values = list(bitmap) # enforce sorted order
        expected = values[start:stop:step]
        expected.sort()
        observed = list(bitmap[start:stop:step])
        self.assertEqual(expected, observed)

    @given(hyp_collection, st.booleans())
    def test_simple_rank(self, values, cow):
        bitmap = BitMap(values, copy_on_write=cow)
        for i, value in enumerate(sorted(values)):
            self.assertEqual(bitmap.rank(value), i+1)

    @given(hyp_collection, uint18, st.booleans())
    def test_general_rank(self, values, element, cow):
        bitmap = BitMap(values, copy_on_write=cow)
        observed_rank = bitmap.rank(element)
        expected_rank = len([n for n in set(values) if n <= element])
        self.assertEqual(expected_rank, observed_rank)

    @given(hyp_collection, st.booleans())
    def test_min(self, values, cow):
        bitmap = BitMap(values, copy_on_write=cow)
        self.assertEqual(bitmap.min(), min(values))

    def test_wrong_min(self):
        bitmap = BitMap()
        with self.assertRaises(ValueError):
            m = bitmap.min()

    @given(hyp_collection, st.booleans())
    def test_max(self, values, cow):
        bitmap = BitMap(values, copy_on_write=cow)
        self.assertEqual(bitmap.max(), max(values))

    def test_wrong_max(self):
        bitmap = BitMap()
        with self.assertRaises(ValueError):
            m = bitmap.max()

class BinaryOperationsTest(Util):

    @given(hyp_collection, hyp_collection, st.booleans(), st.booleans())
    def setUp(self, values1, values2, cow1, cow2):
        self.set1 = set(values1)
        self.set2 = set(values2)
        self.bitmap1 = BitMap(values1, cow1)
        self.bitmap2 = BitMap(values2, cow2)

    def do_test_binary_op(self, op):
        old_bitmap1 = BitMap(self.bitmap1)
        old_bitmap2 = BitMap(self.bitmap2)
        result_set = op(self.set1, self.set2)
        result_bitmap = op(self.bitmap1, self.bitmap2)
        self.assertEqual(self.bitmap1, old_bitmap1)
        self.assertEqual(self.bitmap2, old_bitmap2)
        self.compare_with_set(result_bitmap, result_set)

    def test_or(self):
        self.do_test_binary_op(lambda x,y : x|y)

    def test_and(self):
        self.do_test_binary_op(lambda x,y : x&y)

    def test_xor(self):
        self.do_test_binary_op(lambda x,y : x^y)

    def test_sub(self):
        self.do_test_binary_op(lambda x,y : x-y)

    def do_test_binary_op_inplace(self, op):
        old_bitmap2 = BitMap(self.bitmap2)
        op(self.set1, self.set2)
        op(self.bitmap1, self.bitmap2)
        self.assertEqual(self.bitmap2, old_bitmap2)
        self.compare_with_set(self.bitmap1, self.set1)

    def test_or_inplace(self):
        self.do_test_binary_op_inplace(lambda x,y : x.__ior__(y))

    def test_and_inplace(self):
        self.do_test_binary_op_inplace(lambda x,y : x.__iand__(y))

    def test_xor_inplace(self):
        self.do_test_binary_op_inplace(lambda x,y : x.__ixor__(y))

    def test_sub_inplace(self):
        self.do_test_binary_op_inplace(lambda x,y : x.__isub__(y))

class ComparisonTest(Util):

    @given(hyp_collection, hyp_collection, st.booleans(), st.booleans())
    def setUp(self, values1, values2, cow1, cow2):
        self.set1 = set(values1)
        self.set2 = set(values2)
        self.bitmap1 = BitMap(values1, copy_on_write=cow1)
        self.bitmap2 = BitMap(values2, copy_on_write=cow2)

    def do_test(self, op):
        self.assertEqual(op(self.bitmap1, self.bitmap1),
                         op(self.set1, self.set1))
        self.assertEqual(op(self.bitmap1, self.bitmap2),
                         op(self.set1, self.set2))
        self.assertEqual(op(self.bitmap1|self.bitmap2, self.bitmap2),
                         op(self.set1|self.set2, self.set2))
        self.assertEqual(op(self.set1, self.set1|self.set2),
                         op(self.set1, self.set1|self.set2))

    def test_le(self):
        self.do_test(lambda x,y: x <= y)

    def test_ge(self):
        self.do_test(lambda x,y: x >= y)

    def test_lt(self):
        self.do_test(lambda x,y: x < y)

    def test_gt(self):
        self.do_test(lambda x,y: x > y)

    @given(hyp_collection, hyp_collection, st.booleans(), st.booleans())
    def test_intersect(self, values1, values2, cow1, cow2):
        bm1 = BitMap(values1, copy_on_write=cow1)
        bm2 = BitMap(values2, copy_on_write=cow2)
        self.assertEqual(bm1.intersect(bm2), len(bm1&bm2) > 0)

class CardinalityTest(Util):

    @given(hyp_collection, hyp_collection, st.booleans(), st.booleans())
    def setUp(self, values1, values2, cow1, cow2):
        self.bitmap1 = BitMap(values1, copy_on_write=cow1)
        self.bitmap2 = BitMap(values2, copy_on_write=cow2)

    def do_test_cardinality(self, real_op, estimated_op):
        real_value = real_op(self.bitmap1, self.bitmap2)
        estimated_value = estimated_op(self.bitmap1, self.bitmap2)
        self.assertEqual(real_value, estimated_value)

    def test_or_card(self):
        self.do_test_cardinality(lambda x,y : len(x|y), lambda x,y: x.union_cardinality(y))

    def test_and_card(self):
        self.do_test_cardinality(lambda x,y : len(x&y), lambda x,y: x.intersection_cardinality(y))

    def test_andnot_card(self):
        self.do_test_cardinality(lambda x,y : len(x-y), lambda x,y: x.difference_cardinality(y))

    def test_xor_card(self):
        self.do_test_cardinality(lambda x,y : len(x^y), lambda x,y: x.symmetric_difference_cardinality(y))

    def test_jaccard_index(self):
        real_value = float(len(self.bitmap1&self.bitmap2))/float(max(1, len(self.bitmap1|self.bitmap2)))
        estimated_value = self.bitmap1.jaccard_index(self.bitmap2)
        self.assertAlmostEqual(real_value, estimated_value)

class ManyOperationsTest(Util):

    @given(hyp_many_collections)
    def test_union(self, all_values):
        cow = [random.choice([False, True]) for _ in range(len(all_values))]
        bitmaps = [BitMap(values, copy_on_write=cow[i]) for i, values in enumerate(all_values)]
        bitmaps_copy = [BitMap(bm) for bm in bitmaps]
        result = BitMap.union(*bitmaps)
        self.assertEqual(bitmaps_copy, bitmaps)
        expected_result = functools.reduce(lambda x, y: x|y, bitmaps)
        self.assertEqual(expected_result, result)

class SerializationTest(Util):

    @given(hyp_collection, st.booleans())
    def test_serialization(self, values, cow):
        old_bm = BitMap(values, copy_on_write=cow)
        buff = old_bm.serialize()
        new_bm = BitMap.deserialize(buff)
        self.assertEqual(old_bm, new_bm)
        # Checking that the C pointer are also different
        if len(old_bm) > 0:
            old_bm.remove(old_bm[0])
        else:
            old_bm.add(27)
        self.assertNotEqual(old_bm, new_bm)

    @given(hyp_collection, st.booleans(), st.integers(min_value=2, max_value=pickle.HIGHEST_PROTOCOL))
    def test_pickle_protocol(self, values, cow, protocol):
        old_bm = BitMap(values, copy_on_write=cow)
        pickled = pickle.dumps(old_bm, protocol=protocol)
        new_bm = pickle.loads(pickled)
        self.assertEqual(old_bm, new_bm)
        self.assertTrue(old_bm is not new_bm)
        # Checking that the C pointer are also different
        if len(old_bm) > 0:
            old_bm.remove(old_bm[0])
        else:
            old_bm.add(27)
        self.assertNotEqual(old_bm, new_bm)

class StatisticsTest(Util):

    @given(hyp_collection, st.booleans())
    def test_basic_properties(self, values, cow):
        bitmap = BitMap(values, copy_on_write=cow)
        stats = bitmap.get_statistics()
        self.assertEqual(stats['n_values_array_containers'] + stats['n_values_bitset_containers']
            + stats['n_values_run_containers'], len(bitmap))
        self.assertEqual(stats['n_bytes_array_containers'], 2*stats['n_values_array_containers'])
        self.assertEqual(stats['n_bytes_bitset_containers'], 2**13*stats['n_bitset_containers'])
        if len(values) > 0:
            self.assertEqual(stats['min_value'], bitmap[0])
            self.assertEqual(stats['max_value'], bitmap[len(bitmap)-1])
        self.assertEqual(stats['cardinality'], len(bitmap))
        self.assertEqual(stats['sum_value'], sum(values))

    def test_implementation_properties_array(self):
        values = range(2**16-10, 2**16+10, 2)
        stats = BitMap(values).get_statistics()
        self.assertEqual(stats['n_array_containers'], 2)
        self.assertEqual(stats['n_bitset_containers'], 0)
        self.assertEqual(stats['n_run_containers'], 0)
        self.assertEqual(stats['n_values_array_containers'], len(values))
        self.assertEqual(stats['n_values_bitset_containers'], 0)
        self.assertEqual(stats['n_values_run_containers'], 0)

    def test_implementation_properties_bitset(self):
        values = range(2**0, 2**17, 2)
        stats = BitMap(values).get_statistics()
        self.assertEqual(stats['n_array_containers'], 0)
        self.assertEqual(stats['n_bitset_containers'], 2)
        self.assertEqual(stats['n_run_containers'], 0)
        self.assertEqual(stats['n_values_array_containers'], 0)
        self.assertEqual(stats['n_values_bitset_containers'], len(values))
        self.assertEqual(stats['n_values_run_containers'], 0)

    def test_implementation_properties_run(self):
        values = range(2**0, 2**17, 1)
        stats = BitMap(values).get_statistics()
        self.assertEqual(stats['n_array_containers'], 0)
        self.assertEqual(stats['n_bitset_containers'], 0)
        self.assertEqual(stats['n_run_containers'], 2)
        self.assertEqual(stats['n_values_array_containers'], 0)
        self.assertEqual(stats['n_values_bitset_containers'], 0)
        self.assertEqual(stats['n_values_run_containers'], len(values))
        self.assertEqual(stats['n_bytes_run_containers'], 12)

class FlipTest(Util):

    def check_flip(self, bm_before, bm_after, start, end):
        size = 100
        iter_range = random.sample(range(start, end), min(size, len(range(start, end))))
        iter_before = self.bitmap_sample(bm_before, min(size, len(bm_before)))
        iter_after = self.bitmap_sample(bm_after, min(size, len(bm_after)))
        for elt in iter_range:
            if elt in bm_before:
                self.assertNotIn(elt, bm_after)
            else:
                self.assertIn(elt, bm_after)
        for elt in iter_before:
            if not (start <= elt < end):
                self.assertIn(elt, bm_after)
        for elt in iter_after:
            if not (start <= elt < end):
                self.assertIn(elt, bm_before)

    @given(hyp_collection, integer, integer, st.booleans())
    def test_flip_empty(self, values, start, end, cow):
        st.assume(start >= end)
        bm_before = BitMap(values, copy_on_write=cow)
        bm_copy = BitMap(bm_before)
        bm_after = bm_before.flip(start, end)
        self.assertEqual(bm_before, bm_copy)
        self.assertEqual(bm_before, bm_after)

    @given(hyp_collection, integer, integer, st.booleans())
    def test_flip(self, values, start, end, cow):
        st.assume(start < end)
        bm_before = BitMap(values, copy_on_write=cow)
        bm_copy = BitMap(bm_before)
        bm_after = bm_before.flip(start, end)
        self.assertEqual(bm_before, bm_copy)
        self.check_flip(bm_before, bm_after, start, end)

    @given(hyp_collection, integer, integer, st.booleans())
    def test_flip_inplace_empty(self, values, start, end, cow):
        st.assume(start >= end)
        bm_before = BitMap(values, copy_on_write=cow)
        bm_after = BitMap(bm_before)
        bm_after.flip_inplace(start, end)
        self.assertEqual(bm_before, bm_after)

    @given(hyp_collection, integer, integer, st.booleans())
    def test_flip_inplace(self, values, start, end, cow):
        st.assume(start < end)
        bm_before = BitMap(values, copy_on_write=cow)
        bm_after = BitMap(bm_before)
        bm_after.flip_inplace(start, end)
        self.check_flip(bm_before, bm_after, start, end)

if __name__ == "__main__":
    unittest.main()
