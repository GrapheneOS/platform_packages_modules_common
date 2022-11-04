/*
 * Copyright (C) 2022 The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package com.android.modules.targetprep;

import com.android.tradefed.config.Option;
import com.android.tradefed.device.DeviceNotAvailableException;
import com.android.tradefed.device.ITestDevice;
import com.android.tradefed.invoker.TestInformation;
import com.android.tradefed.log.LogUtil.CLog;
import com.android.tradefed.targetprep.BaseTargetPreparer;
import com.android.tradefed.targetprep.TargetSetupError;
import com.android.tradefed.util.RunUtil;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

/*
 * Target preparer that fetches classpath relevant artifacts for a test in a 'reentrant' manner.
 *
 * <p>The preparer will fetch all <b>BOOTCLASSPATH</b>, <b>SYSTEMSERVERCLASSPATH</b> and shared
 * libraries from the device, parse their contents and dump the classnames into a temporary
 * directory.</p>
 *
 * <p>Additionally, the preparer <i>can</i> fetch, parse and dump data for module specific artifacts
 * (i.e. apk-in-apex) if specified.</p>
 *
 * <p>Nested runs of the artifact fetcher (i.e. in the case of a top-level test config xml and a
 * child test xml) will only fetch non-common elements, and remove temporary class dumps fetched
 * during that particular preparer run.</p>
 *
 * <p>Each module's conformance framework test config xml must run the preparer (with module
 * specific parameters) before the entrypoint test jar, and the top-level conformance framework
 * config xml must also run it before any other module xml.</p>
 *
 * <p>The upshot is that when running all conformance framework tests for all modules, the shared
 * artifacts are fetched and processed only once.</p>
 */
public class ClasspathFetcher extends BaseTargetPreparer {

    public static final String DEVICE_JAR_ARTIFACTS_TAG = "device-jar-artifacts";

    private boolean mFetchedArtifacts = false;

    @Override
    public void setUp(TestInformation testInfo)
            throws TargetSetupError, DeviceNotAvailableException {
        // The artifacts have been fetched already, no need to do anything else.
        if (testInfo.properties().containsKey(DEVICE_JAR_ARTIFACTS_TAG)) {
            return;
        }
        try {
            final Path tmpDir = Files.createTempDirectory("device_artifacts");
            testInfo.properties().put(DEVICE_JAR_ARTIFACTS_TAG, tmpDir.toAbsolutePath().toString());
            // TODO(b/254647172): Fetch data
            mFetchedArtifacts = true;
        } catch(IOException e) {
            throw new RuntimeException("Could not create temp artifacts dir!", e);
        }
    }

    @Override
    public void tearDown(TestInformation testInfo, Throwable e) {
        if (mFetchedArtifacts) {
            try {
                final String path = testInfo.properties().get(DEVICE_JAR_ARTIFACTS_TAG);
                if (path == null) {
                    throw new IllegalStateException("Target preparer has previously fetched"
                            + " artifacts, but the DEVICE_JAR_ARTIFACTS_TAG property was removed");
                }
                final File jarArtifactsDir = new File(path);
                if (!jarArtifactsDir.delete()) {
                    throw new RuntimeException("Failed to remove jar artifacts dir!");
                }
            } finally {
                testInfo.properties().remove(DEVICE_JAR_ARTIFACTS_TAG);
            }
        }
    }

}