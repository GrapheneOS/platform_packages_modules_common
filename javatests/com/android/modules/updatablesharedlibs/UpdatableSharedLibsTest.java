/*
 * Copyright (C) 2021 The Android Open Source Project
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

package com.android.modules.updatablesharedlibs;

import static org.junit.Assume.assumeTrue;

import com.android.internal.util.test.SystemPreparer;
import com.android.tradefed.testtype.DeviceJUnit4ClassRunner;
import com.android.tradefed.testtype.junit4.BaseHostJUnit4Test;

import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.RuleChain;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;

import android.cts.install.lib.host.InstallUtilsHost;

@RunWith(DeviceJUnit4ClassRunner.class)
public class UpdatableSharedLibsTest extends BaseHostJUnit4Test {

    private final InstallUtilsHost mHostUtils = new InstallUtilsHost(this);
    private final TemporaryFolder mTemporaryFolder = new TemporaryFolder();
    private final SystemPreparer mPreparer = new SystemPreparer(mTemporaryFolder, this::getDevice);

    @Rule
    public final RuleChain ruleChain = RuleChain.outerRule(mTemporaryFolder).around(mPreparer);

    @Test
    public void callOnDeviceApiFromHost() throws Exception {
        if (!getDevice().isAdbRoot()) {
            getDevice().enableAdbRoot();
        }
        assumeTrue("Device does not support updating APEX", mHostUtils.isApexUpdateSupported());
        assumeTrue("Device requires root", getDevice().isAdbRoot());

        String apex = "test_com.android.modules.updatablesharedlibs.apex";
        mPreparer.pushResourceFile(apex, "/system/apex/" + apex);
        mPreparer.reboot();
        getDevice().disableAdbRoot();

        installPackage("com.android.modules.updatablesharedlibs.apps.targetS.apk");
        installPackage("com.android.modules.updatablesharedlibs.apps.targetT.apk");
        installPackage("com.android.modules.updatablesharedlibs.apps.targetTWithLib.apk");

        runDeviceTests("com.android.modules.updatablesharedlibs.apps.targetS", null);
        runDeviceTests("com.android.modules.updatablesharedlibs.apps.targetT", null);
        runDeviceTests("com.android.modules.updatablesharedlibs.apps.targetTWithLib", null);
    }
}
