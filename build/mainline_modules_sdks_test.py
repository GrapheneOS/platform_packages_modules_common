#!/usr/bin/env python3
#
# Copyright (C) 2021 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Unit tests for mainline_modules_sdks.py."""

from pathlib import Path
import os
import tempfile
import unittest
import zipfile

import mainline_modules_sdks as mm


class TestPopulateDist(unittest.TestCase):

    def create_snapshot_file(self, out_dir, name, version):
        sdks_out_dir = Path(out_dir, "soong/mainline-sdks")
        sdks_out_dir.mkdir(parents=True, exist_ok=True)
        zip_file = Path(sdks_out_dir, f"{name}-{version}.zip")
        with zipfile.ZipFile(zip_file, "w") as z:
            z.writestr("Android.bp", "")
            if name.endswith("-sdk"):
                z.writestr("sdk_library/public/removed.txt", "")
                z.writestr("sdk_library/public/source.srcjar", "")
                z.writestr("sdk_library/public/lib.jar", "")
                z.writestr("sdk_library/public/api.txt", "")

    def test(self):
        """Verify the dist/mainline-sdks directory is populated correctly"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_out_dir = os.path.join(tmp_dir, "out")
            os.mkdir(tmp_out_dir)
            tmp_dist_dir = os.path.join(tmp_dir, "dist")
            os.mkdir(tmp_dist_dir)

            modules = [
                mm.MAINLINE_MODULES_BY_APEX["com.android.art"],
                mm.MAINLINE_MODULES_BY_APEX["com.android.ipsec"],
            ]

            # Create input file structure.
            for module in modules:
                for sdk in module.sdks:
                    self.create_snapshot_file(tmp_out_dir, sdk, "current")

            producer = mm.SdkDistProducer(
                out_dir=tmp_out_dir,
                dist_dir=tmp_dist_dir,
            )

            sdk_versions = ["current"]
            producer.populate_dist(sdk_versions, modules)

            files = []
            for abs_dir, _, filenames in os.walk(tmp_dist_dir):
                rel_dir = os.path.relpath(abs_dir, tmp_dist_dir)
                for f in filenames:
                    files.append(os.path.join(rel_dir, f))
            # pylint: disable=line-too-long
            self.assertEqual([
                "mainline-sdks/current/com.android.art/host-exports/art-module-host-exports-current.zip",
                "mainline-sdks/current/com.android.art/sdk/art-module-sdk-current.zip",
                "mainline-sdks/current/com.android.art/test-exports/art-module-test-exports-current.zip",
                "mainline-sdks/current/com.android.ipsec/sdk/ipsec-module-sdk-current.zip",
                "stubs/com.android.art/sdk_library/public/api.txt",
                "stubs/com.android.art/sdk_library/public/lib.jar",
                "stubs/com.android.art/sdk_library/public/removed.txt",
                "stubs/com.android.art/sdk_library/public/source.srcjar",
                "stubs/com.android.ipsec/sdk_library/public/api.txt",
                "stubs/com.android.ipsec/sdk_library/public/lib.jar",
                "stubs/com.android.ipsec/sdk_library/public/removed.txt",
                "stubs/com.android.ipsec/sdk_library/public/source.srcjar",
            ], sorted(files))


def pathToTestData(relative_path):
    """Construct a path to a test data file.

    The relative_path is relative to the location of this file.
    """
    this_file = __file__
    # When running as a python_test_host (name=<x>) with an embedded launcher
    # the __file__ points to .../<x>/<x>.py but the .../<x> is not a directory
    # it is a binary with the launcher and the python file embedded inside. In
    # that case a test data file <rel> is at .../<x>_data/<rel>, not
    # .../<x>/<x>_data/<rel> so it is necessary to trim the base name (<x>.py)
    # from the file.
    if not os.path.isfile(this_file):
        this_file = os.path.dirname(this_file)
    # When the python file is at .../<x>.py (or in the case of an embedded
    # launcher at .../<x>/<x>.py) then the test data is at .../<x>_data/<rel>.
    this_file_without_ext, _ = os.path.splitext(this_file)
    return os.path.join(this_file_without_ext + "_data", relative_path)


def readTestData(relative_path):
    with open(pathToTestData(relative_path), "r") as f:
        return f.read()


class TestSoongConfigBoilerplateInserter(unittest.TestCase):

    def apply_transformations(self, src, transformations, expected):
        producer = mm.SdkDistProducer(script=self._testMethodName)

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "Android.bp")
            with open(path, "w") as f:
                f.write(src)

            mm.apply_transformations(producer, tmp_dir, transformations)

            with open(path, "r") as f:
                result = f.read()

        self.maxDiff = None
        self.assertEqual(expected, result)

    def test_common_mainline_module(self):
        """Tests the transformations applied to a common mainline module.

        This uses ipsec as an example of a common mainline module. This checks
        that the correct Soong config module types and variables are used and
        that it imports the definitions from the correct location.
        """
        src = readTestData("ipsec_Android.bp.input")

        expected = readTestData("ipsec_Android.bp.expected")

        module = mm.MAINLINE_MODULES_BY_APEX["com.android.ipsec"]
        transformations = module.transformations()

        self.apply_transformations(src, transformations, expected)

    def test_art(self):
        """Tests the transformations applied to a the ART mainline module.

        The ART mainline module uses a different Soong config setup to the
        common mainline modules. This checks that the ART specific Soong config
        module types, variable and imports are used.
        """
        src = readTestData("art_Android.bp.input")

        expected = readTestData("art_Android.bp.expected")

        module = mm.MAINLINE_MODULES_BY_APEX["com.android.art"]
        transformations = module.transformations()

        self.apply_transformations(src, transformations, expected)


class TestFilterModules(unittest.TestCase):

    def test_no_filter(self):
        modules = mm.filter_modules(mm.MAINLINE_MODULES)
        self.assertEqual(modules, mm.MAINLINE_MODULES)

    def test_with_filter(self):
        os.environ["TARGET_BUILD_APPS"] = "com.android.art"
        modules = mm.filter_modules(mm.MAINLINE_MODULES)
        expected = mm.MAINLINE_MODULES_BY_APEX["com.android.art"]
        self.assertEqual(modules, [expected])


if __name__ == "__main__":
    unittest.main(verbosity=2)
