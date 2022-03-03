#!/usr/bin/env python3
#
# Copyright (C) 2021 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Builds SDK snapshots.

If the environment variable TARGET_BUILD_APPS is nonempty then only the SDKs for
the APEXes in it are built, otherwise all configured SDKs are built.
"""

import dataclasses
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import typing
from typing import Callable, List
import zipfile


@dataclasses.dataclass(frozen=True)
class ConfigVar:
    """Represents a Soong configuration variable"""
    # The config variable namespace, e.g. ANDROID.
    namespace: str

    # The name of the variable within the namespace.
    name: str


@dataclasses.dataclass(frozen=True)
class FileTransformation:
    """Performs a transformation on a file within an SDK snapshot zip file."""

    # The path of the file within the SDK snapshot zip file.
    path: str

    def apply(self, producer, path):
        """Apply the transformation to the src_path to produce the dest_path."""
        raise NotImplementedError


@dataclasses.dataclass(frozen=True)
class SoongConfigBoilerplateInserter(FileTransformation):
    """Transforms an Android.bp file to add soong config boilerplate.

    The boilerplate allows the prefer setting of the modules to be controlled
    through a Soong configuration variable.
    """

    # The configuration variable that will control the prefer setting.
    configVar: ConfigVar

    # The bp file containing the definitions of the configuration module types
    # to use in the sdk.
    configBpDefFile: str

    # The prefix to use for the soong config module types.
    configModuleTypePrefix: str

    def apply(self, producer, path):
        with open(path, "r+") as file:
            self._apply_transformation(producer, file)

    def _apply_transformation(self, producer, file):
        # TODO(b/174997203): Remove this when we have a proper way to control
        #  prefer flags in Mainline modules.

        header_lines = []
        for line in file:
            line = line.rstrip("\n")
            if not line.startswith("//"):
                break
            header_lines.append(line)

        config_module_types = set()

        content_lines = []
        for line in file:
            line = line.rstrip("\n")

            # Check to see whether the line is the start of a new module type,
            # e.g. <module-type> {
            module_header = re.match("([a-z0-9_]+) +{$", line)
            if not module_header:
                # It is not so just add the line to the output and skip to the
                # next line.
                content_lines.append(line)
                continue

            module_type = module_header.group(1)
            module_content = []

            # Iterate over the Soong module contents
            for module_line in file:
                module_line = module_line.rstrip("\n")

                # When the end of the module has been reached then exit.
                if module_line == "}":
                    break

                # Check to see if the module is an unversioned module, i.e.
                # without @<version>. If it is then it needs to have the soong
                # config boilerplate added to control the setting of the prefer
                # property. Versioned modules do not need that because they are
                # never preferred.
                # At the moment this differentiation between versioned and
                # unversioned relies on the fact that the unversioned modules
                # set "prefer: false", while the versioned modules do not. That
                # is a little bit fragile so may require some additional checks.
                if module_line != "    prefer: false,":
                    # The line does not indicate that the module needs the
                    # soong config boilerplate so add the line and skip to the
                    # next one.
                    module_content.append(module_line)
                    continue

                # Add the soong config boilerplate instead of the line:
                #     prefer: false,
                namespace = self.configVar.namespace
                name = self.configVar.name
                module_content.append(f"""\
    // Do not prefer prebuilt if the Soong config variable "{name}" in namespace "{namespace}" is true.
    prefer: true,
    soong_config_variables: {{
        {name}: {{
            prefer: false,
        }},
    }},""")

                # Change the module type to the corresponding soong config
                # module type by adding the prefix.
                module_type = self.configModuleTypePrefix + module_type
                # Add the module type to the list of module types that need to
                # be imported into the bp file.
                config_module_types.add(module_type)

            # Generate the module, possibly with the new module type and
            # containing the
            content_lines.append(module_type + " {")
            content_lines.extend(module_content)
            content_lines.append("}")

        # Add the soong_config_module_type_import module definition that imports
        # the soong config module types into this bp file to the header lines so
        # that they appear before any uses.
        module_types = "\n".join(
            [f'        "{mt}",' for mt in sorted(config_module_types)])
        header_lines.append(f"""
// Soong config variable stanza added by {producer.script}.
soong_config_module_type_import {{
    from: "{self.configBpDefFile}",
    module_types: [
{module_types}
    ],
}}
""")

        # Overwrite the file with the updated contents.
        file.seek(0)
        file.truncate()
        file.write("\n".join(header_lines + content_lines) + "\n")


@dataclasses.dataclass()
class SubprocessRunner:
    """Runs subprocesses"""

    # Destination for stdout from subprocesses.
    #
    # This (and the following stderr) are needed to allow the tests to be run
    # in Intellij. This ensures that the tests are run with stdout/stderr
    # objects that work when passed to subprocess.run(stdout/stderr). Without it
    # the tests are run with a FlushingStringIO object that has no fileno
    # attribute - https://youtrack.jetbrains.com/issue/PY-27883.
    stdout: io.TextIOBase = sys.stdout

    # Destination for stderr from subprocesses.
    stderr: io.TextIOBase = sys.stderr

    def run(self, *args, **kwargs):
        return subprocess.run(
            *args, check=True, stdout=self.stdout, stderr=self.stderr, **kwargs)


@dataclasses.dataclass()
class SnapshotBuilder:
    """Builds sdk snapshots"""

    # Used to run subprocesses for building snapshots.
    subprocess_runner: SubprocessRunner

    # The OUT_DIR environment variable.
    out_dir: str

    def get_mainline_sdks_path(self):
        """Get the path to the Soong mainline-sdks directory"""
        return os.path.join(self.out_dir, "soong/mainline-sdks")

    def get_sdk_path(self, sdk_name, sdk_version):
        """Get the path to the sdk snapshot zip file produced by soong"""
        return os.path.join(self.get_mainline_sdks_path(),
                            f"{sdk_name}-{sdk_version}.zip")

    def build_snapshots(self, build_release, sdk_versions, modules):
        # Build the SDKs once for each version.
        for sdk_version in sdk_versions:
            # Compute the paths to all the Soong generated sdk snapshot files
            # required by this script.
            paths = [
                self.get_sdk_path(sdk, sdk_version)
                for module in modules
                for sdk in module.sdks
            ]

            # Extra environment variables to pass to the build process.
            extraEnv = {
                # TODO(ngeoffray): remove SOONG_ALLOW_MISSING_DEPENDENCIES, but
                #  we currently break without it.
                "SOONG_ALLOW_MISSING_DEPENDENCIES": "true",
                # Set SOONG_SDK_SNAPSHOT_USE_SRCJAR to generate .srcjars inside
                # sdk zip files as expected by prebuilt drop.
                "SOONG_SDK_SNAPSHOT_USE_SRCJAR": "true",
                # Set SOONG_SDK_SNAPSHOT_VERSION to generate the appropriately
                # tagged version of the sdk.
                "SOONG_SDK_SNAPSHOT_VERSION": sdk_version,
            }
            extraEnv.update(build_release.soong_env)

            # Unless explicitly specified in the calling environment set
            # TARGET_BUILD_VARIANT=user.
            # This MUST be identical to the TARGET_BUILD_VARIANT used to build
            # the corresponding APEXes otherwise it could result in different
            # hidden API flags, see http://b/202398851#comment29 for more info.
            targetBuildVariant = os.environ.get("TARGET_BUILD_VARIANT", "user")
            cmd = [
                "build/soong/soong_ui.bash",
                "--make-mode",
                "--soong-only",
                f"TARGET_BUILD_VARIANT={targetBuildVariant}",
                "TARGET_PRODUCT=mainline_sdk",
                "MODULE_BUILD_FROM_SOURCE=true",
                "out/soong/apex/depsinfo/new-allowed-deps.txt.check",
            ] + paths
            print_command(extraEnv, cmd)
            env = os.environ.copy()
            env.update(extraEnv)
            self.subprocess_runner.run(cmd, env=env)


# A list of the sdk versions to build. Usually just current but can include a
# numeric version too.
SDK_VERSIONS = [
    # Suitable for overriding the source modules with prefer:true.
    # Unlike "unversioned" this mode also adds "@current" suffixed modules
    # with the same prebuilts (which are never preferred).
    "current",
    # Insert additional sdk versions needed for the latest build release.
]

# The initially empty list of build releases. Every BuildRelease that is created
# automatically appends itself to this list.
ALL_BUILD_RELEASES = []


@dataclasses.dataclass(frozen=True)
class BuildRelease:
    """Represents a build release"""

    # The name of the build release, e.g. Q, R, S, T, etc.
    name: str

    # The function to call to create the snapshot in the dist, that covers
    # building and copying the snapshot into the dist.
    creator: Callable[
        ["BuildRelease", "SdkDistProducer", List["MainlineModule"]], None]

    # The sub-directory of dist/mainline-sdks into which the build release
    # specific snapshots will be copied.
    #
    # Defaults to for-<name>-build.
    sub_dir: str = None

    # Additional environment variables to pass to Soong when building the
    # snapshots for this build release.
    #
    # Defaults to {
    #     "SOONG_SDK_SNAPSHOT_TARGET_BUILD_RELEASE": <name>,
    # }
    soong_env: typing.Dict[str, str] = None

    # The sdk versions that need to be generated for this build release.
    sdk_versions: List[str] = \
        dataclasses.field(default_factory=lambda: SDK_VERSIONS)

    # The position of this instance within the BUILD_RELEASES list.
    ordinal: int = dataclasses.field(default=-1, init=False)

    def __post_init__(self):
        # The following use object.__setattr__ as this object is frozen and
        # attempting to set the fields directly would cause an exception to be
        # thrown.
        object.__setattr__(self, "ordinal", len(ALL_BUILD_RELEASES))
        # Add this to the end of the list of all build releases.
        ALL_BUILD_RELEASES.append(self)
        # If no sub_dir was specified then set the default.
        if self.sub_dir is None:
            object.__setattr__(self, "sub_dir", f"for-{self.name}-build")
        # If no soong_env was specified then set the default.
        if self.soong_env is None:
            object.__setattr__(
                self,
                "soong_env",
                {
                    # Set SOONG_SDK_SNAPSHOT_TARGET_BUILD_RELEASE to generate a
                    # snapshot suitable for a specific target build release.
                    "SOONG_SDK_SNAPSHOT_TARGET_BUILD_RELEASE": self.name,
                })

    def __le__(self, other):
        return self.ordinal <= other.ordinal


def create_no_dist_snapshot(build_release: BuildRelease,
                            producer: "SdkDistProducer",
                            modules: List["MainlineModule"]):
    """A place holder dist snapshot creation function that does nothing."""
    print(f"create_no_dist_snapshot for modules {[m.apex for m in modules]}")
    return


def create_sdk_snapshots_in_Soong(build_release: BuildRelease,
                                  producer: "SdkDistProducer",
                                  modules: List["MainlineModule"]):
    """Builds sdks and populates the dist."""
    producer.produce_dist_for_build_release(build_release, modules)
    return


def reuse_latest_sdk_snapshots(build_release: BuildRelease,
                               producer: "SdkDistProducer",
                               modules: List["MainlineModule"]):
    """Copies the snapshots from the latest build."""
    producer.populate_dist(build_release, build_release.sdk_versions, modules)
    return


Q = BuildRelease(
    name="Q",
    # At the moment we do not generate a snapshot for Q.
    creator=create_no_dist_snapshot,
)
R = BuildRelease(
    name="R",
    # At the moment we do not generate a snapshot for R.
    creator=create_no_dist_snapshot,
)
S = BuildRelease(
    name="S",
    # Generate a snapshot for S using Soong.
    creator=create_sdk_snapshots_in_Soong,
)
Tiramisu = BuildRelease(
    name="Tiramisu",
    # Generate a snapshot for Tiramisu using Soong.
    creator=create_sdk_snapshots_in_Soong,
)

# Insert additional BuildRelease definitions for following releases here,
# before LATEST.

# The build release for the latest build supported by this build, i.e. the
# current build. This must be the last BuildRelease defined in this script,
# before LEGACY_BUILD_RELEASE.
LATEST = BuildRelease(
    name="latest",
    creator=create_sdk_snapshots_in_Soong,
    # There are no build release specific environment variables to pass to
    # Soong.
    soong_env={},
)

# The build release to populate the legacy dist structure that does not specify
# a particular build release. This MUST come after LATEST so that it includes
# all the modules for which sdk snapshot source is available.
LEGACY_BUILD_RELEASE = BuildRelease(
    name="legacy",
    # There is no build release specific sub directory.
    sub_dir="",
    # There are no build release specific environment variables to pass to
    # Soong.
    soong_env={},
    # Do not create new snapshots, simply use the snapshots generated for
    # latest.
    creator=reuse_latest_sdk_snapshots,
)


@dataclasses.dataclass(frozen=True)
class MainlineModule:
    """Represents a mainline module"""
    # The name of the apex.
    apex: str

    # The names of the sdk and module_exports.
    sdks: list[str]

    # The first build release in which the SDK snapshot for this module is
    # needed.
    #
    # Note: This is not necessarily the same build release in which the SDK
    #       source was first included. So, a module that was added in build T
    #       could potentially be used in an S release and so its SDK will need
    #       to be made available for S builds.
    #
    # Defaults to the latest build, i.e. the build on which this script is run
    # as the snapshot is assumed to be needed in the build containing the sdk
    # source.
    first_release: BuildRelease = LATEST

    # The configuration variable, defaults to ANDROID:module_build_from_source
    configVar: ConfigVar = ConfigVar(
        namespace="ANDROID",
        name="module_build_from_source",
    )

    # The bp file containing the definitions of the configuration module types
    # to use in the sdk.
    configBpDefFile: str = "packages/modules/common/Android.bp"

    # The prefix to use for the soong config module types.
    configModuleTypePrefix: str = "module_"

    def transformations(self):
        """Returns the transformations to apply to this module's snapshot(s)."""
        return [
            SoongConfigBoilerplateInserter(
                "Android.bp",
                configVar=self.configVar,
                configModuleTypePrefix=self.configModuleTypePrefix,
                configBpDefFile=self.configBpDefFile),
        ]

    def is_required_for(self, target_build_release):
        """True if this module is required for the target build release."""
        return self.first_release <= target_build_release


# List of mainline modules.
MAINLINE_MODULES = [
    MainlineModule(
        apex="com.android.art",
        sdks=[
            "art-module-sdk",
            "art-module-test-exports",
            "art-module-host-exports",
        ],
        first_release=S,
        # Override the config... fields.
        configVar=ConfigVar(
            namespace="art_module",
            name="source_build",
        ),
        configBpDefFile="prebuilts/module_sdk/art/SoongConfig.bp",
        configModuleTypePrefix="art_prebuilt_",
    ),
    MainlineModule(
        apex="com.android.conscrypt",
        sdks=[
            "conscrypt-module-sdk",
            "conscrypt-module-test-exports",
            "conscrypt-module-host-exports",
        ],
        first_release=Q,
    ),
    MainlineModule(
        apex="com.android.ipsec",
        sdks=["ipsec-module-sdk"],
        first_release=S,
    ),
    MainlineModule(
        apex="com.android.media",
        sdks=["media-module-sdk"],
        first_release=R,
    ),
    MainlineModule(
        apex="com.android.mediaprovider",
        sdks=["mediaprovider-module-sdk"],
        first_release=R,
    ),
    MainlineModule(
        apex="com.android.ondevicepersonalization",
        sdks=["ondevicepersonalization-module-sdk"],
        first_release=Tiramisu,
    ),
    MainlineModule(
        apex="com.android.permission",
        sdks=["permission-module-sdk"],
        first_release=R,
    ),
    MainlineModule(
        apex="com.android.scheduling",
        sdks=["scheduling-sdk"],
    ),
    MainlineModule(
        apex="com.android.sdkext",
        sdks=["sdkextensions-sdk"],
        first_release=R,
    ),
    MainlineModule(
        apex="com.android.os.statsd",
        sdks=["statsd-module-sdk"],
        first_release=R,
    ),
    MainlineModule(
        apex="com.android.tethering",
        sdks=["tethering-module-sdk"],
        first_release=R,
    ),
    MainlineModule(
        apex="com.android.uwb",
        sdks=["uwb-module-sdk"],
    ),
    MainlineModule(
        apex="com.android.wifi",
        sdks=["wifi-module-sdk"],
        first_release=R,
    ),
]


@dataclasses.dataclass
class SdkDistProducer:
    """Produces the DIST_DIR/mainline-sdks and DIST_DIR/stubs directories.

    Builds SDK snapshots for mainline modules and then copies them into the
    DIST_DIR/mainline-sdks directory. Also extracts the sdk_library txt, jar and
    srcjar files from each SDK snapshot and copies them into the DIST_DIR/stubs
    directory.
    """

    # Used to run subprocesses for this.
    subprocess_runner: SubprocessRunner

    # Builds sdk snapshots
    snapshot_builder: SnapshotBuilder

    # The DIST_DIR environment variable.
    dist_dir: str = "uninitialized-dist"

    # The path to this script. It may be inserted into files that are
    # transformed to document where the changes came from.
    script: str = sys.argv[0]

    # The path to the mainline-sdks dist directory.
    #
    # Initialized in __post_init__().
    mainline_sdks_dir: str = dataclasses.field(init=False)

    def __post_init__(self):
        self.mainline_sdks_dir = os.path.join(self.dist_dir, "mainline-sdks")

    def prepare(self):
        # Clear the mainline-sdks dist directory.
        shutil.rmtree(self.mainline_sdks_dir, ignore_errors=True)

    def produce_dist(self, modules, build_releases):
        # Prepare the dist directory for the sdks.
        self.prepare()

        for build_release in build_releases:
            # Only build modules that are required for this build release.
            filtered_modules = [
                m for m in modules if m.is_required_for(build_release)
            ]
            if filtered_modules:
                print(f"Building SDK snapshots for {build_release.name}"
                      f" build release")
                build_release.creator(build_release, self, filtered_modules)

        self.populate_stubs(modules)

    def produce_dist_for_build_release(self, build_release, modules):
        sdk_versions = build_release.sdk_versions
        self.snapshot_builder.build_snapshots(build_release, sdk_versions,
                                              modules)
        self.populate_dist(build_release, sdk_versions, modules)

    def unzip_current_stubs(self, sdk_name, apex_name):
        """Unzips stubs for "current" into {producer.dist_dir}/stubs/{apex}."""
        sdk_path = self.snapshot_builder.get_sdk_path(sdk_name, "current")
        dest_dir = os.path.join(self.dist_dir, "stubs", apex_name)
        print(
            f"Extracting java_sdk_library files from {sdk_path} to {dest_dir}")
        os.makedirs(dest_dir, exist_ok=True)
        extract_matching_files_from_zip(
            sdk_path, dest_dir, r"sdk_library/[^/]+/[^/]+\.(txt|jar|srcjar)")

    def populate_stubs(self, modules):
        # TODO(b/199759953): Remove stubs once it is no longer used by gantry.
        # Clear and populate the stubs directory.
        stubs_dir = os.path.join(self.dist_dir, "stubs")
        shutil.rmtree(stubs_dir, ignore_errors=True)

        for module in modules:
            apex = module.apex
            for sdk in module.sdks:
                # If the sdk's name ends with -sdk then extract sdk library
                # related files from its zip file.
                if sdk.endswith("-sdk"):
                    self.unzip_current_stubs(sdk, apex)

    def populate_dist(self, build_release, sdk_versions, modules):
        build_release_dist_dir = os.path.join(self.mainline_sdks_dir,
                                              build_release.sub_dir)

        for module in modules:
            apex = module.apex
            for sdk_version in sdk_versions:
                for sdk in module.sdks:
                    subdir = re.sub("^[^-]+-(module-)?", "", sdk)
                    if subdir not in ("sdk", "host-exports", "test-exports"):
                        raise Exception(
                            f"{sdk} is not a valid name, expected name in the"
                            f" format of"
                            f" ^[^-]+-(module-)?(sdk|host-exports|test-exports)"
                        )

                    sdk_dist_dir = os.path.join(build_release_dist_dir,
                                                sdk_version, apex, subdir)
                    sdk_path = self.snapshot_builder.get_sdk_path(
                        sdk, sdk_version)
                    self.dist_sdk_snapshot_zip(sdk_path, sdk_dist_dir,
                                               module.transformations())

    def dist_sdk_snapshot_zip(self, src_sdk_zip, sdk_dist_dir, transformations):
        """Copy the sdk snapshot zip file to a dist directory.

        If no transformations are provided then this simply copies the show sdk
        snapshot zip file to the dist dir. However, if transformations are
        provided then the files to be transformed are extracted from the
        snapshot zip file, they are transformed to files in a separate directory
        and then a new zip file is created in the dist directory with the
        original files replaced by the newly transformed files.
        """
        os.makedirs(sdk_dist_dir)
        dest_sdk_zip = os.path.join(sdk_dist_dir, os.path.basename(src_sdk_zip))
        print(f"Copying sdk snapshot {src_sdk_zip} to {dest_sdk_zip}")

        # If no transformations are provided then just copy the zip file
        # directly.
        if len(transformations) == 0:
            shutil.copy(src_sdk_zip, sdk_dist_dir)
            return

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create a single pattern that will match any of the paths provided
            # in the transformations.
            pattern = "|".join(
                [f"({re.escape(t.path)})" for t in transformations])

            # Extract the matching files from the zip into the temporary
            # directory.
            extract_matching_files_from_zip(src_sdk_zip, tmp_dir, pattern)

            # Apply the transformations to the extracted files in situ.
            apply_transformations(self, tmp_dir, transformations)

            # Replace the original entries in the zip with the transformed
            # files.
            paths = [transformation.path for transformation in transformations]
            copy_zip_and_replace(self, src_sdk_zip, dest_sdk_zip, tmp_dir,
                                 paths)


def print_command(env, cmd):
    print(" ".join([f"{name}={value}" for name, value in env.items()] + cmd))


def extract_matching_files_from_zip(zip_path, dest_dir, pattern):
    """Extracts files from a zip file into a destination directory.

    The extracted files are those that match the specified regular expression
    pattern.
    """
    with zipfile.ZipFile(zip_path) as zip_file:
        for filename in zip_file.namelist():
            if re.match(pattern, filename):
                zip_file.extract(filename, dest_dir)


def copy_zip_and_replace(producer, src_zip_path, dest_zip_path, src_dir, paths):
    """Copies a zip replacing some of its contents in the process.

     The files to replace are specified by the paths parameter and are relative
     to the src_dir.
    """
    # Get the absolute paths of the source and dest zip files so that they are
    # not affected by a change of directory.
    abs_src_zip_path = os.path.abspath(src_zip_path)
    abs_dest_zip_path = os.path.abspath(dest_zip_path)
    producer.subprocess_runner.run(
        ["zip", "-q", abs_src_zip_path, "--out", abs_dest_zip_path] + paths,
        # Change into the source directory before running zip.
        cwd=src_dir)


def apply_transformations(producer, tmp_dir, transformations):
    for transformation in transformations:
        path = os.path.join(tmp_dir, transformation.path)

        # Record the timestamp of the file.
        modified = os.path.getmtime(path)

        # Transform the file.
        transformation.apply(producer, path)

        # Reset the timestamp of the file to the original timestamp before the
        # transformation was applied.
        os.utime(path, (modified, modified))


def create_producer():
    # Variables initialized from environment variables that are set by the
    # calling mainline_modules_sdks.sh.
    out_dir = os.environ["OUT_DIR"]
    dist_dir = os.environ["DIST_DIR"]

    subprocess_runner = SubprocessRunner()
    snapshot_builder = SnapshotBuilder(
        subprocess_runner=subprocess_runner,
        out_dir=out_dir,
    )
    return SdkDistProducer(
        subprocess_runner=subprocess_runner,
        snapshot_builder=snapshot_builder,
        dist_dir=dist_dir,
    )


def filter_modules(modules):
    target_build_apps = os.environ.get("TARGET_BUILD_APPS")
    if target_build_apps:
        target_build_apps = target_build_apps.split()
        return [m for m in modules if m.apex in target_build_apps]
    else:
        return modules


def main():
    """Program entry point."""
    if not os.path.exists("build/make/core/Makefile"):
        sys.exit("This script must be run from the top of the tree.")

    producer = create_producer()
    modules = filter_modules(MAINLINE_MODULES)

    producer.produce_dist(modules, ALL_BUILD_RELEASES)


if __name__ == "__main__":
    main()
