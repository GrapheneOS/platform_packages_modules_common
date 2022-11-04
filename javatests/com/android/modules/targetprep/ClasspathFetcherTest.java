/*
 * Copyright (C) 2022  The Android Open Source Project
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

import static com.android.modules.targetprep.ClasspathFetcher.DEVICE_JAR_ARTIFACTS_TAG;
import static com.google.common.truth.Truth.assertThat;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.fail;
import static org.junit.Assume.assumeTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;


import com.android.tradefed.build.IDeviceBuildInfo;
import com.android.tradefed.device.ITestDevice;
import com.android.tradefed.invoker.IInvocationContext;
import com.android.tradefed.invoker.InvocationContext;
import com.android.tradefed.invoker.TestInformation;

import org.junit.Assert;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.RuleChain;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.junit.runners.JUnit4;

import org.mockito.Mock;
import org.mockito.Mockito;
import org.mockito.MockitoAnnotations;

@RunWith(JUnit4.class)
public class ClasspathFetcherTest {

    private static final String SERIAL = "SERIAL";

    @Mock IDeviceBuildInfo mMockBuildInfo;
    @Mock ITestDevice mMockTestDevice;

    private TestInformation mTestInfo;

    @Before
    public void setUp() throws Exception {
        MockitoAnnotations.initMocks(this);

        when(mMockTestDevice.getSerialNumber()).thenReturn(SERIAL);
        when(mMockTestDevice.getDeviceDescriptor()).thenReturn(null);
        when(mMockTestDevice.isAppEnumerationSupported()).thenReturn(false);
        IInvocationContext context = new InvocationContext();
        context.addAllocatedDevice("device", mMockTestDevice);
        context.addDeviceBuildInfo("device", mMockBuildInfo);
        mTestInfo = TestInformation.newBuilder().setInvocationContext(context).build();
    }

    @Test
    public void testSingleArtifactFetcher() throws Exception {
        final ClasspathFetcher fetcher = new ClasspathFetcher();
        fetcher.setUp(mTestInfo);
        assertThat(mTestInfo.properties().containsKey(DEVICE_JAR_ARTIFACTS_TAG)).isTrue();
        fetcher.tearDown(mTestInfo, null);
        assertThat(mTestInfo.properties().containsKey(DEVICE_JAR_ARTIFACTS_TAG)).isFalse();
    }

    @Test
    public void testMultipleArtifactFetchers() throws Exception {
        final ClasspathFetcher fetcher1 = new ClasspathFetcher();
        final ClasspathFetcher fetcher2 = new ClasspathFetcher();

        fetcher1.setUp(mTestInfo);
        fetcher2.setUp(mTestInfo);
        assertThat(mTestInfo.properties().containsKey(DEVICE_JAR_ARTIFACTS_TAG)).isTrue();
        fetcher2.tearDown(mTestInfo, null);
        assertThat(mTestInfo.properties().containsKey(DEVICE_JAR_ARTIFACTS_TAG)).isTrue();
        fetcher1.tearDown(mTestInfo, null);
        assertThat(mTestInfo.properties().containsKey(DEVICE_JAR_ARTIFACTS_TAG)).isFalse();
    }
}
